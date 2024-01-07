"""
Plex
Author: stabbedbybrick

Info:
Quality: up to 1080p, AAC 2.0
Some titles are encrypted, some are not. Both versions are supported


"""
from __future__ import annotations

import asyncio
import re
import subprocess
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import click
import httpx
from bs4 import BeautifulSoup

from utils.args import get_args
from utils.cdm import LocalCDM
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    add_subtitles,
    force_numbering,
    get_wvd,
    kid_to_pssh,
    set_filename,
    set_save_path,
    string_cleaning,
    is_url
)


class Plex(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        if is_url(self.episode):
            self.log.error("Episode URL not supported. Use standard method")
            return

        self.client.headers.update(
            {
                "accept": "application/json",
                "x-plex-client-identifier": "d90522a0-52bd-4101-969e-58beaed3ab66",
                "x-plex-language": "en",
                "x-plex-product": "Plex Mediaverse",
                "x-plex-provider-version": "6.5.0",
            }
        )

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

    def get_auth_token(self) -> str:
        r = self.client.post(self.config["user"])
        if not r.ok:
            raise ConnectionError(r.json()["Error"].get("message"))

        self.auth_token = r.json()["authToken"]
        return self.auth_token


    def get_data(self, url: str) -> dict:
        kind = urlparse(url).path.split("/")[1]
        video_id = urlparse(url).path.split("/")[2]

        self.client.headers.update({"x-plex-token": self.get_auth_token()})

        r = self.client.get(f"{self.config['vod']}/library/metadata/{kind}:{video_id}")
        if not r.ok:
            raise ConnectionError(r.json()["Error"].get("message"))
        
        return r.json()

    async def fetch(self, session, url):
        response = await session.get(url)
        return response.json()["MediaContainer"]["Metadata"]

    async def fetch_all(self, urls):
        async with httpx.AsyncClient(headers=self.client.headers) as client:
            tasks = [self.fetch(client, url) for url in urls]
            responses = await asyncio.gather(*tasks)
        return responses

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)
        series = self.client.get(
            self.config["vod"] + data["MediaContainer"]["Metadata"][0]["key"]
        ).json()

        urls = [
            self.config["vod"] + item["key"]
            for item in series["MediaContainer"]["Metadata"]
            if item["type"] == "season"
        ]

        seasons = asyncio.run(self.fetch_all(urls))

        return Series(
            [
                Episode(
                    id_=next((x["id"] for x in episode["Media"]), None),
                    service="PLEX",
                    title=re.sub(r"\s*\(\d{4}\)", "", episode["grandparentTitle"]),
                    season=int(episode.get("parentIndex", 0)),
                    number=int(episode.get("index", 0)),
                    name=episode.get("title"),
                    year=episode.get("year"),
                    data=next(x["url"] for x in episode["Media"] if x.get("protocol") == "dash"),
                    drm=True if next((x["drm"] for x in episode["Media"]), None) else False,
                    subtitle=(next(x["key"] for x in episode["Media"][0]["Part"][0]["Stream"] 
                                   if x.get("streamType") == 3), None),
                )
                for season in seasons
                for episode in season
                if episode["type"] == "episode"
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)

        return Movies(
            [
                Movie(
                    id_=next((x["id"] for x in movie["Media"]), None),
                    service="PLEX",
                    title=movie["title"],
                    year=movie.get("year"),
                    name=movie["title"],
                    data=next(x["url"] for x in movie["Media"] if x.get("protocol") == "dash"),
                    drm=True if next((x["drm"] for x in movie["Media"]), None) else False,
                    subtitle=(next(x["key"] for x in movie["Media"][0]["Part"][0]["Stream"] 
                                   if x.get("streamType") == 3), None),
                )
                for movie in data["MediaContainer"]["Metadata"]
            ]
        )
    

    def get_dash_quality(self, soup: object, quality: str) -> str:
        elements = soup.find_all("Representation")
        heights = sorted(
            [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
            reverse=True,
        )

        if quality is not None:
            if int(quality) in heights:
                return quality
            else:
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                return closest_match

        return heights[0]

    def get_mediainfo(self, stream: object, quality: str) -> str:
        r = self.client.get(stream.data)
        r.raise_for_status()
        self.soup = BeautifulSoup(r.content, "xml")
        pssh = kid_to_pssh(self.soup) if stream.drm else None
        quality = self.get_dash_quality(self.soup, quality)

        if stream.subtitle:
            video_id = stream.id.split("-")[0]
            subtitle = self.config["subtitle"].format(id=video_id)
            self.soup = add_subtitles(self.soup, subtitle)

        self.base_url = re.sub(r"(\w+.mpd)", "", stream.data)

        with open(self.tmp / "manifest.mpd", "w") as f:
            f.write(str(self.soup.prettify()))

        return quality, pssh

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

    def get_options(self) -> None:
        downloads, title = get_downloads(self)

        for download in downloads:
            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        with self.console.status("Getting media info..."):
            self.res, pssh = self.get_mediainfo(stream, self.quality)

        keys = None
        if stream.drm:
            lic_url = self.config["license"].format(id=stream.id, token=self.auth_token)
            keys = self.get_keys(pssh, lic_url)
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self, title)
        self.manifest = self.tmp / "manifest.mpd"
        self.key_file = self.tmp / "keys.txt" if keys else None
        self.sub_path = None

        self.log.info(f"{str(stream)}")
        click.echo("")

        args, file_path = get_args(self)

        if not file_path.exists():
            try:
                subprocess.run(args, check=True)
            except Exception as e:
                raise ValueError(f"{e}")
        else:
            self.log.info(f"{self.filename} already exists. Skipping download\n")
            self.sub_path.unlink() if self.sub_path else None
            pass
