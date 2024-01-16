"""
Credit to rlaphoenix for the title storage

Author: stabbedbybrick

Info:
Quality: 1080p, AAC 2.0 max

"""
from __future__ import annotations

import json
import re
import subprocess
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import click

from utils.args import get_args
from utils.cdm import LocalCDM
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Series
from utils.utilities import (
    construct_pssh,
    force_numbering,
    get_heights,
    get_wvd,
    in_cache,
    set_filename,
    set_save_path,
    string_cleaning,
    update_cache,
)


class UKTVPLAY(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        with self.config["download_cache"].open("r") as file:
            self.cache = json.load(file)

        self.vod = self.config["vod"]
        self.api = self.config["api"]

        self.get_options()

    def get_license(self, challenge: bytes, lic_url: str) -> bytes:
        r = self.client.post(url=lic_url, data=challenge)
        r.raise_for_status()
        return r.content

    def get_keys(self, pssh: str, lic_url: str) -> bytes:
        wvd = get_wvd(Path.cwd())
        widevine = LocalCDM(wvd)
        challenge = widevine.challenge(pssh)
        response = self.get_license(challenge, lic_url)
        return widevine.parse(response)

    def get_data(self, url: str) -> list[dict]:
        slug = urlparse(url).path.split("/")[2]

        r = self.client.get(f"{self.vod}brand/?slug={slug}")
        r.raise_for_status()

        id_list = [series["id"] for series in r.json()["series"]]

        seasons = [
            self.client.get(f"{self.vod}series/?id={id}").json() for id in id_list
        ]
        return seasons

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
                    id_=episode["video_id"],
                    service="UKTV",
                    title=episode["brand_name"],
                    season=int(episode["series_number"]),
                    number=episode["episode_number"],
                    name=episode["name"],
                    year=None,
                    data=None,
                    description=episode.get("synopsis"),
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
        r.raise_for_status()

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

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        r = self.client.get(manifest)
        r.raise_for_status()
        heights, self.soup = get_heights(self.client, manifest)

        if quality is not None:
            if int(quality) in heights:
                return quality
            else:
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                return closest_match

        return heights[0]

    def get_content(self, url: str) -> object:
        if self.movie:
            with self.console.status("Fetching movie titles..."):
                content = self.get_movies(self.url)
                title = string_cleaning(str(content))

            self.log.info(f"{str(content)}\n")

        else:
            with self.console.status("Fetching series titles..."):
                content = self.get_series(url)

                title = string_cleaning(str(content))
                seasons = Counter(x.season for x in content)
                num_seasons = len(seasons)
                num_episodes = sum(seasons.values())

                if self.force_numbering:
                    content = force_numbering(content)

            self.log.info(
                f"{str(content)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"
            )

        return content, title

    def get_episode_from_url(self, url: str):
        with self.console.status("Getting episode from URL..."):
            html = self.client.get(url).text
            house_number = re.search(r'house_number="(.+?)"', html).group(1)

            data = self.client.get(
                f"{self.vod}episode/?house_number={house_number}"
            ).json()

            episode = Series(
                [
                    Episode(
                        id_=data["video_id"],
                        service="UKTV",
                        title=data["brand_name"],
                        season=int(data["series_number"]),
                        number=data["episode_number"],
                        name=data["name"],
                        year=None,
                        data=None,
                        description=data.get("synopsis"),
                    )
                ]
            )

        title = string_cleaning(str(episode))

        return [episode[0]], title

    def get_options(self) -> None:
        downloads, title = get_downloads(self)

        for download in downloads:
            if in_cache(self.cache, download):
                continue

            if self.slowdown:
                with self.console.status(
                    f"Slowing things down for {self.slowdown} seconds..."
                ):
                    time.sleep(self.slowdown)

            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        manifest, lic_url = self.get_playlist(stream.id)
        self.res = self.get_mediainfo(manifest, self.quality)
        pssh = construct_pssh(self.soup)

        keys = self.get_keys(pssh, lic_url)
        with open(self.tmp / "keys.txt", "w") as file:
            file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        self.log.info(f"{str(stream)}")
        for key in keys:
            self.log.info(f"{key}")
        click.echo("")

        args, file_path = get_args(self)

        try:
            subprocess.run(args, check=True)
        except Exception as e:
            self.sub_path.unlink() if self.sub_path else None
            raise ValueError(f"{e}")
        
        if not self.skip_download and file_path.exists():
            update_cache(self.cache, self.config, stream)
