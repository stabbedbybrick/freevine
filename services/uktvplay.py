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

from helpers.utilities import (
    info,
    string_cleaning,
    set_save_path,
    print_info,
    set_filename,
)
from helpers.cdm import local_cdm, remote_cdm
from helpers.titles import Episode, Series
from helpers.args import Options, get_args


class UKTVPLAY:
    def __init__(self, config, **kwargs) -> None:
        self.config = config
        self.tmp = Path("tmp")
        self.url = kwargs.get("url")
        self.quality = kwargs.get("quality")
        self.remote = kwargs.get("remote")
        self.titles = kwargs.get("titles")
        self.info = kwargs.get("info")
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

        self.get_options()

    def get_data(self, url: str) -> list[dict]:
        slug = urlparse(url).path.split("/")[2]

        response = self.client.get(f"{self.vod}brand/?slug={slug}").json()

        id_list = [series["id"] for series in response["series"]]

        seasons = [
            self.client.get(f"{self.vod}series/?id={id}").json() for id in id_list
        ]
        return seasons

    def get_series(self, url: str) -> Series:
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
                    description=episode.get("synopsis")
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
        self.soup = BeautifulSoup(self.client.get(manifest), "xml")
        pssh = self.get_pssh(self.soup)
        elements = self.soup.find_all("Representation")
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

    def get_content(self, url: str) -> object:
        if self.movie:
            with self.console.status("Fetching titles..."):
                content = self.get_movies(self.url)
                title = string_cleaning(str(content))

            info(f"{str(content)}\n")

        else:
            with self.console.status("Fetching titles..."):
                content = self.get_series(url)
                for episode in content:
                    episode.name = episode.get_filename()

                title = string_cleaning(str(content))
                seasons = Counter(x.season for x in content)
                num_seasons = len(seasons)
                num_episodes = sum(seasons.values())

            info(
                f"{str(content)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"
            )

        return content, title

    def get_options(self) -> None:
        opt = Options(self)
        content, title = self.get_content(self.url)

        if self.episode:
            downloads = opt.get_episode(content)
        if self.season:
            downloads = opt.get_season(content)
        if self.complete:
            downloads = opt.get_complete(content)
        if self.movie:
            downloads = opt.get_movie(content)
        if self.titles:
            opt.list_titles(content)

        for download in downloads:
            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        with self.console.status("Getting media info..."):
            manifest, lic_url = self.get_playlist(stream.data)
            res, pssh = self.get_mediainfo(manifest, self.quality)

        with self.console.status("Getting decryption keys..."):
            keys = (
                remote_cdm(pssh, lic_url, self.client)
                if self.remote
                else local_cdm(pssh, lic_url, self.client)
            )
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        self.filename = set_filename(self, stream, res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self.config, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        if self.info:
            print_info(self, stream, keys)

        info(f"{stream.name}")
        for key in keys:
            info(f"{key}")
        click.echo("")

        args, file_path = get_args(self, res)

        if not file_path.exists():
            try:
                subprocess.run(args, check=True)
            except:
                raise ValueError("Download failed or was interrupted")
        else:
            info(f"{self.filename} already exist. Skipping download\n")
            self.sub_path.unlink() if self.sub_path.exists() else None
            pass