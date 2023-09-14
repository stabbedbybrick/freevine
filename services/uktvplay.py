"""
Credit to rlaphoenix for the title storage

Author: stabbedbybrick

Info:
Quality: 1080p, AAC 2.0 max

"""

import base64
import shutil
import subprocess
import sys

from urllib.parse import urlparse
from pathlib import Path
from collections import Counter

import click
import httpx

from bs4 import BeautifulSoup
from rich.console import Console

from helpers.utilities import info, string_cleaning, set_range
from helpers.cdm import local_cdm, remote_cdm
from helpers.titles import Episode, Series


class UKTVPLAY:
    def __init__(self, config, **kwargs) -> None:
        self.config = config
        self.tmp = Path("tmp")
        self.url = kwargs.get("url")
        self.quality = kwargs.get("quality")
        self.remote = kwargs.get("remote")
        self.titles = kwargs.get("titles")
        self.episode = kwargs.get("episode")
        self.season = kwargs.get("season")
        self.movie = kwargs.get("movie")
        self.complete = kwargs.get("complete")
        self.all_audio = kwargs.get("all_audio")

        self.vod = f"https://vschedules.uktv.co.uk/vod/"
        self.api = f"https://edge.api.brightcove.com/playback/v1/accounts/"
        self.console = Console()
        self.client = httpx.Client(
            headers={"user-agent": "Chrome/118.0.0.0 Safari/537.36"}
        )

        self.tmp.mkdir(parents=True, exist_ok=True)

        self.episode = self.episode.upper() if self.episode else None
        self.season = self.season.upper() if self.season else None
        self.quality = self.quality.rstrip("p") if self.quality else None

        self.list_titles() if self.titles else None
        self.get_episode() if self.episode else None
        self.get_season() if self.season else None
        self.get_complete() if self.complete else None

    def get_data(self, url: str) -> list[dict]:
        slug = urlparse(url).path.split("/")[2]

        response = self.client.get(f"{self.vod}brand/?slug={slug}").json()

        id_list = [series["id"] for series in response["series"]]

        seasons = [
            self.client.get(f"{self.vod}series/?id={id}").json() for id in id_list
        ]
        return seasons

    def get_titles(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
                    id_=None,
                    service="UKTV",
                    title=episode["brand_name"],
                    season=int(episode["series_number"]),
                    number=episode["episode_number"],
                    name=episode["name"],
                    year=None,
                    data=episode["video_id"],
                )
                for season in data
                for episode in season["episodes"]
            ]
        )

    def get_playlist(self, video_id: str) -> tuple:
        account = "1242911124001"
        headers = {
            "Accept": "application/json;pk="
            "BCpkADawqM3vt2DxMZ94FyjAfheKk_-e92F-hnuKgoJMh2hgaASJJV_gUeYm710md2yS24_"
            "4PfOEbF_SSTNM4PijWNnwZG8Tlg4Y40XyFQh_T9Vq2460u3GXCUoSQOYlpfhbzmQ8lEwUmmte"
        }
        url = f"{self.api}{account}/videos/{video_id}"

        r = self.client.get(url, headers=headers)
        if not r.is_success:
            print(f"\nError! {r.status_code}")
            shutil.rmtree(self.tmp)
            sys.exit(1)

        data = r.json()

        manifest = [
            x["src"]
            for x in data["sources"]
            if x.get("key_systems").get("com.widevine.alpha")
        ][0]

        lic_url = [
            x["key_systems"]["com.widevine.alpha"]["license_url"]
            for x in data["sources"]
            if x.get("key_systems").get("com.widevine.alpha")
        ][0]

        return manifest, lic_url

    def get_pssh(self, soup: str) -> str:
        kid = (
            soup.select_one("ContentProtection")
            .attrs.get("cenc:default_KID")
            .replace("-", "")
        )
        version = "3870737368"
        system_id = "EDEF8BA979D64ACEA3C827DCD51D21ED"
        data = "48E3DC959B06"
        s = f"000000{version}00000000{system_id}000000181210{kid}{data}"
        return base64.b64encode(bytes.fromhex(s)).decode()

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        soup = BeautifulSoup(self.client.get(manifest), "xml")
        pssh = self.get_pssh(soup)
        elements = soup.find_all("Representation")
        heights = sorted(
            [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
            reverse=True,
        )

        if quality is not None:
            if int(quality) in heights:
                return quality, pssh
            else:
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                info(f"Resolution not available. Getting closest match:")
                return closest_match, pssh

        return heights[0], pssh

    def get_info(self, url: str) -> object:
        with self.console.status("Fetching titles..."):
            series = self.get_titles(url)
            for episode in series:
                episode.name = episode.get_filename()

        title = string_cleaning(str(series))
        seasons = Counter(x.season for x in series)
        num_seasons = len(seasons)
        num_episodes = sum(seasons.values())

        info(f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n")

        return series, title

    def list_titles(self) -> str:
        series, title = self.get_info(self.url)

        for episode in series:
            info(episode.name)

    def get_episode(self) -> None:
        series, title = self.get_info(self.url)

        if "-" in self.episode:
            self.get_range(series, self.episode, title)
        if "," in self.episode:
            self.get_mix(series, self.episode, title)

        target = next((i for i in series if self.episode in i.name), None)

        self.download(target, title) if target else info(
            f"{self.episode} was not found"
        )

    def get_range(self, series: object, episodes: str, title: str) -> None:
        episode_range = set_range(episodes)

        for episode in series:
            if any(i in episode.name for i in episode_range):
                self.download(episode, title)

        shutil.rmtree(self.tmp)
        exit(0)

    def get_mix(self, series: object, episodes: str, title: str) -> None:
        episode_mix = [x for x in episodes.split(",")]

        for episode in series:
            if any(i in episode.name for i in episode_mix):
                self.download(episode, title)

        shutil.rmtree(self.tmp)
        exit(0)

    def get_season(self) -> None:
        series, title = self.get_info(self.url)

        for episode in series:
            if self.season in episode.name:
                self.download(episode, title)

    def get_complete(self) -> None:
        series, title = self.get_info(self.url)

        for episode in series:
            self.download(episode, title)

    def download(self, stream: object, title: str) -> None:
        downloads = Path(self.config["save_dir"])
        save_path = downloads.joinpath(title)
        save_path.mkdir(parents=True, exist_ok=True)

        if stream.__class__.__name__ == "Episode" and self.config["seasons"] == "true":
            _season = f"season.{stream.season:02d}"
            save_path = save_path.joinpath(_season)
            save_path.mkdir(parents=True, exist_ok=True)

        with self.console.status("Getting media info..."):
            manifest, lic_url = self.get_playlist(stream.data)
            resolution, pssh = self.get_mediainfo(manifest, self.quality)

        with self.console.status("Getting decryption keys..."):
            keys = (
                remote_cdm(pssh, lic_url, self.client)
                if self.remote
                else local_cdm(pssh, lic_url, self.client)
            )
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        info(f"{stream.name}")
        for key in keys:
            info(f"{key}")
        click.echo("")

        m3u8dl = shutil.which("N_m3u8DL-RE") or shutil.which("n-m3u8dl-re")

        _temp = self.config["temp_dir"]

        _video = f"res='{resolution}'" if self.quality else "for=best"
        _audio = "all" if self.all_audio else "for=best"

        _threads = self.config["threads"]
        _format = self.config["format"]
        _muxer = self.config["muxer"]
        _sub = self.config["skip_sub"]

        if self.config["filename"] == "default":
            _file = f"{stream.name}.{resolution}p.{stream.service}.WEB-DL.AAC2.0.H.264"
        else:
            _file = f"{stream.name}.{resolution}p"

        args = [
            m3u8dl,
            "--key-text-file",
            self.tmp / "keys.txt",
            manifest,
            "-sv",
            _video,
            "-sa",
            _audio,
            "-ss",
            "all",
            "-mt",
            "-M",
            f"format={_format}:muxer={_muxer}:skip_sub={_sub}",
            "--thread-count",
            _threads,
            "--save-name",
            _file,
            "--tmp-dir",
            _temp,
            "--save-dir",
            save_path,
            "--no-log",
            # "--log-level",
            # "OFF",
        ]

        try:
            subprocess.run(args, check=True)
        except:
            raise ValueError(
                "Download failed. Install necessary binaries before downloading"
            )
