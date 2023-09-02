"""
Credit to rlaphoenix for the title storage

Author: stabbedbybrick

Info:
Due to the inconsistency of STV's data structure, some titles currently don't work.
For those titles that do work, both encrypted and non-encrypted are supported. 

Quality: 1080p, AAC 2.0 max

"""

import base64
import re
import subprocess
import json
import shutil
import sys

from pathlib import Path
from collections import Counter

import click
import httpx

from bs4 import BeautifulSoup
from rich.console import Console

from helpers.utilities import stamp, string_cleaning, set_range
from helpers.cdm import local_cdm, remote_cdm
from helpers.titles import Episode, Series


class STV:
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

        self.vod = f"https://player.api.stv.tv/v1/episodes?series.guid="
        self.api = f"https://edge.api.brightcove.com/playback/v1/accounts"
        self.console = Console()
        self.client = httpx.Client(
            headers={"user-agent": "Chrome/113.0.0.0 Safari/537.36"}
        )

        self.tmp.mkdir(parents=True, exist_ok=True)

        self.episode = self.episode.upper() if self.episode else None
        self.season = self.season.upper() if self.season else None
        self.quality = self.quality.rstrip("p") if self.quality else None

        self.list_titles() if self.titles else None
        self.get_episode() if self.episode else None
        self.get_season() if self.season else None
        self.get_complete() if self.complete else None

    def get_data(self, url: str) -> tuple:
        soup = BeautifulSoup(self.client.get(url), "html.parser")
        props = soup.select_one("#__NEXT_DATA__").text
        data = json.loads(props)
        data = data["props"]["pageProps"]["data"]

        id_list = [x["id"] for x in data["tabs"] if x["type"] == "episode"]
        drm = data["programmeData"]["drmEnabled"]

        headers = {"stv-drm": "true"} if drm else None

        seasons = [
            self.client.get(f"{self.vod}{id}", headers=headers).json() for id in id_list
        ]

        return seasons, drm

    def account_config(self, drm: bool) -> tuple:
        pkey = {
            "Accept": "application/json;pk="
            "BCpkADawqM1WJ12PwtUWqGXx3nbAo2XVSxyAQxPRZKBc75svhrUB9qIMPN_"
            "d9US0Vib5smumeNMbntSmZIpzeVV1iUrnzYgf5k7UMaVN46PGYe_oSZ-xbPVnsm4"
        }

        pkey_drm = {
            "Accept": "application/json;pk="
            "BCpkADawqM1fQNUrQOvg-vTo4VGDTJ_lGjxp2zBSPcXJntYd5csQkjm7hBKviIVgfFoEJLW4_"
            "JPPsHUwXNEjZspbr3d1HqGDw2gUqGCBZ_9Y_BF7HJsh2n6PQcpL9b2kdbi103oXvmTNZWiQ"
        }

        headers = pkey_drm if drm else pkey
        account = "6204867266001" if drm else "1486976045"

        return headers, account

    def get_playlist(self, video_id: str, drm: bool):
        lic_url = None
        headers, account = self.account_config(drm)
        url = f"{self.api}/{account}/videos/{video_id}"

        r = self.client.get(url, headers=headers)
        if not r.is_success:
            print(f"\nError! {r.status_code}")
            shutil.rmtree(self.tmp)
            sys.exit(1)

        data = r.json()

        manifest = [
            source["src"]
            for source in data["sources"]
            if source.get("type") == "application/dash+xml"
        ][0]

        if drm:
            key_systems = [
                source
                for source in data["sources"]
                if source.get("type") == "application/dash+xml"
                and source.get("key_systems").get("com.widevine.alpha")
            ]

            lic_url = key_systems[0]["key_systems"]["com.widevine.alpha"]["license_url"]

        return manifest, lic_url

    def get_titles(self, data: list):
        return Series(
            [
                Episode(
                    id_=None,
                    service="STV",
                    title=episode["programme"]["name"],
                    season=int(episode["playerSeries"]["name"].split(" ")[1]),
                    number=episode["number"],
                    name=None,
                    year=None,
                    data=episode["video"]["id"],
                )
                for series in data
                for episode in series["results"]
            ]
        )

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

    def get_mediainfo(self, manifest: str, quality: str, drm: bool) -> str:
        soup = BeautifulSoup(self.client.get(manifest), "xml")
        pssh = self.get_pssh(soup) if drm else None
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
                stamp(f"Resolution not available. Getting closest match:")
                return closest_match, pssh

        return heights[0], pssh

    def get_info(self, url: str) -> object:
        with self.console.status("Fetching titles..."):
            data, drm = self.get_data(url)
            series = self.get_titles(data)
            for episode in series:
                episode.name = episode.get_filename()

        title = string_cleaning(str(series))
        seasons = Counter(x.season for x in series)
        num_seasons = len(seasons)
        num_episodes = sum(seasons.values())

        stamp(f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n")

        return series, title, drm

    def list_titles(self) -> str:
        series, title, drm = self.get_info(self.url)

        for episode in series:
            stamp(episode.name)

        shutil.rmtree(self.tmp)

    def get_episode(self) -> None:
        series, title, drm = self.get_info(self.url)

        if "-" in self.episode:
            self.get_range(series, self.episode, title, drm)
        if "," in self.episode:
            self.get_mix(series, self.episode, title, drm)

        target = next((i for i in series if self.episode in i.name), None)

        self.download(target, title, drm) if target else stamp(
            f"{self.episode} was not found"
        )

        shutil.rmtree(self.tmp)

    def get_range(self, series: object, episodes: str, title: str, drm: bool) -> None:
        episode_range = set_range(episodes)

        for episode in series:
            if any(i in episode.name for i in episode_range):
                self.download(episode, title, drm)

        shutil.rmtree(self.tmp)
        exit(0)

    def get_mix(self, series: object, episodes: str, title: str, drm: bool) -> None:
        episode_mix = [x for x in episodes.split(",")]

        for episode in series:
            if any(i in episode.name for i in episode_mix):
                self.download(episode, title, drm)

        shutil.rmtree(self.tmp)
        exit(0)

    def get_season(self) -> None:
        series, title, drm = self.get_info(self.url)

        for episode in series:
            if self.season in episode.name:
                self.download(episode, title, drm)

        shutil.rmtree(self.tmp)

    def get_complete(self) -> None:
        series, title, drm = self.get_info(self.url)

        for episode in series:
            self.download(episode, title, drm)

        shutil.rmtree(self.tmp)

    def download(self, stream: object, title: str, drm: bool) -> None:
        downloads = Path(self.config["save_dir"])
        save_path = downloads.joinpath(title)
        save_path.mkdir(parents=True, exist_ok=True)

        if stream.__class__.__name__ == "Episode" and self.config["seasons"] == "true":
            _season = f"season.{stream.season:02d}"
            save_path = save_path.joinpath(_season)
            save_path.mkdir(parents=True, exist_ok=True)

        with self.console.status("Getting media info..."):
            manifest, lic_url = self.get_playlist(stream.data, drm)
            resolution, pssh = self.get_mediainfo(manifest, self.quality, drm)

        if drm:
            with self.console.status("Getting decryption keys..."):
                keys = (
                    remote_cdm(pssh, lic_url, self.client)
                    if self.remote
                    else local_cdm(pssh, lic_url, self.client)
                )
                with open(self.tmp / "keys.txt", "w") as file:
                    file.write("\n".join(keys))

        stamp(f"{stream.name}")
        stamp(f"{keys[0]}") if drm else stamp("No encryption found")
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
            file = f"{stream.name}.{resolution}p.{stream.service}.WEB-DL.AAC2.0.H.264"
        else:
            file = f"{stream.name}.{resolution}p"

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
            file,
            "--tmp-dir",
            _temp,
            "--save-dir",
            save_path,
            "--no-log",
            # "--log-level",
            # "OFF",
        ]

        args.extend(["--key-text-file", self.tmp / "keys.txt"]) if drm else None

        try:
            subprocess.run(args, check=True)
        except:
            raise ValueError(
                "Download failed. Install necessary binaries before downloading"
            )
