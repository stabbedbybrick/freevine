"""
Credit to rlaphoenix for the title storage

ROKU
Author: stabbedbybrick

Info:
This program will grab higher 1080p bitrate and Dolby 5.1 audio (if available)

"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import urllib
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
    get_wvd,
    set_filename,
    set_save_path,
    string_cleaning,
)


class ROKU(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

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

    def get_data(self, url: str) -> json:
        video_id = urlparse(url).path.split("/")[2]

        r = self.client.get(f"{self.api}{video_id}")
        r.raise_for_status()

        return r.json()

    async def fetch_titles(self, async_client: httpx.AsyncClient, id: str) -> json:
        response = await async_client.get(f"{self.api}{id}")
        return response.json()

    async def get_titles(self, data: dict) -> list:
        async with httpx.AsyncClient() as async_client:
            tasks = [
                self.fetch_titles(async_client, x["meta"]["id"])
                for x in data["episodes"]
            ]

            return await asyncio.gather(*tasks)

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)
        episodes = asyncio.run(self.get_titles(data))

        return Series(
            [
                Episode(
                    id_=None,
                    service="ROKU",
                    title=data["title"],
                    season=int(episode["seasonNumber"]),
                    number=int(episode["episodeNumber"]),
                    name=episode["title"],
                    year=data["releaseYear"],
                    data=episode["meta"]["id"],
                    description=episode["description"],
                )
                for episode in episodes
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)

        return Movies(
            [
                Movie(
                    id_=None,
                    service="ROKU",
                    title=data["title"],
                    year=data["releaseYear"],
                    name=data["title"],
                    data=data["meta"]["id"],
                    synopsis=data["description"],
                )
            ]
        )

    def get_playlist(self, id: str) -> tuple:
        response = self.client.get("https://therokuchannel.roku.com/api/v1/csrf").json()

        token = response["csrf"]

        headers = {
            "csrf-token": token,
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
            (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
        }
        payload = {
            "rokuId": id,
            "mediaFormat": "mpeg-dash",
            "drmType": "widevine",
            "quality": "fhd",
            "providerId": "rokuavod",
        }

        url = self.config["vod"]

        r = self.client.post(
            url, headers=headers, cookies=self.client.cookies, json=payload
        )
        r.raise_for_status()

        videos = r.json()["playbackMedia"]["videos"]

        lic_url = [
            x["drmParams"]["licenseServerURL"]
            for x in videos
            if x["drmParams"]["keySystem"] == "Widevine"
        ][0]

        mpd = [x["url"] for x in videos if x["streamFormat"] == "dash"][0]
        mpd = re.sub(r"https:\/\/vod-playlist\.sr\.roku\.com\/1\.mpd\?origin=", "", mpd)
        manifest = urllib.parse.unquote(mpd).split("?")[0]

        return lic_url, manifest

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        r = self.client.get(manifest)
        self.soup = BeautifulSoup(r.content, "xml")
        elements = self.soup.find_all("Representation")
        codecs = [x.attrs["codecs"] for x in elements if x.attrs.get("codecs")]
        heights = sorted(
            [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
            reverse=True,
        )

        audio = "DD5.1" if "ac-3" in codecs else "AAC2.0"

        if quality is not None:
            if int(quality) in heights:
                return quality, audio
            else:
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                return closest_match, audio

        return heights[0], audio

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

            self.log.info(
                f"{str(content)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"
            )

        return content, title

    def get_episode_from_url(self, url: str):
        with self.console.status("Getting episode from URL..."):
            episode_id = urlparse(url).path.split("/")[2]

            data = self.client.get(f"{self.api}{episode_id}").json()
            title = self.client.get(f"{self.api}{data['series']['meta']['id']}").json()[
                "title"
            ]

            episode = Series(
                [
                    Episode(
                        id_=None,
                        service="ROKU",
                        title=title,
                        season=int(data["seasonNumber"]),
                        number=int(data["episodeNumber"]),
                        name=data["title"],
                        year=data.get("startYear"),
                        data=episode_id,
                        description=data.get("description"),
                    )
                ]
            )

        title = string_cleaning(str(episode))

        return [episode[0]], title

    def get_options(self) -> None:
        downloads, title = get_downloads(self)

        for download in downloads:
            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        with self.console.status("Getting media info..."):
            pssh = "AAAAKXBzc2gAAAAA7e+LqXnWSs6jyCfc1R0h7QAAAAkiASpI49yVmwY="

            lic_url, manifest = self.get_playlist(stream.data)
            self.res, audio = self.get_mediainfo(manifest, self.quality)

        keys = self.get_keys(pssh, lic_url)
        with open(self.tmp / "keys.txt", "w") as file:
            file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio)
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        self.log.info(f"{str(stream)}")
        for key in keys:
            self.log.info(f"{key}")
        click.echo("")

        args, file_path = get_args(self)

        if not file_path.exists():
            try:
                subprocess.run(args, check=True)
            except Exception as e:
                raise ValueError(f"{e}")
        else:
            self.log.info(f"{self.filename} already exist. Skipping download\n")
            self.sub_path.unlink() if self.sub_path else None
            pass
