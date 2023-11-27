"""
Credit to rlaphoenix for the title storage

ROKU
Author: stabbedbybrick

Info:
This program will grab higher 1080p bitrate and Dolby 5.1 audio (if available)

"""
from __future__ import annotations

import subprocess
import urllib
import json
import asyncio
import re

from urllib.parse import urlparse
from collections import Counter
from pathlib import Path

import click
import httpx
import yaml

from bs4 import BeautifulSoup

from utils.utilities import (
    info,
    error,
    is_url,
    string_cleaning,
    set_save_path,
    set_filename,
    get_wvd,
    geo_error,
    premium_error,
)
from utils.titles import Episode, Series, Movie, Movies
from utils.options import Options
from utils.args import get_args
from utils.info import print_info
from utils.config import Config
from utils.cdm import LocalCDM

class ROKU(Config):
    def __init__(self, config, srvc_api, srvc_config, **kwargs):
        super().__init__(config, srvc_api, srvc_config, **kwargs)

        with open(self.srvc_api, "r") as f:
            self.config.update(yaml.safe_load(f))

        self.api = self.config["api"]
        self.get_options()

    def get_license(self, challenge: bytes, lic_url: str) -> bytes:
        r = self.client.post(url=lic_url, data=challenge)
        if not r.is_success:
            error(f"License request failed: {r.status_code}")
            exit(1)
        return r.content

    def get_keys(self, pssh: str, lic_url: str) -> bytes:
        wvd = get_wvd(Path.cwd())
        with self.console.status("Getting decryption keys..."):
            widevine = LocalCDM(wvd)
            challenge = widevine.challenge(pssh)
            response = self.get_license(challenge, lic_url)
            return widevine.parse(response)

    def get_data(self, url: str) -> json:
        video_id = urlparse(url).path.split("/")[2]

        r = self.client.get(f"{self.api}{video_id}")
        if not r.is_success:
            geo_error(r.status_code, None, location="US")
        
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
                    description=episode["description"]
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
                    synopsis=data["description"]
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

        r = self.client.post(url, headers=headers, cookies=self.client.cookies, json=payload)
        if not r.is_success:
            premium_error(r.status_code)

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
        self.soup = BeautifulSoup(self.client.get(manifest), "xml")
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
            with self.console.status("Fetching titles..."):
                content = self.get_movies(self.url)
                title = string_cleaning(str(content))

            info(f"{str(content)}\n")

        else:
            with self.console.status("Fetching titles..."):
                content = self.get_series(url)

                title = string_cleaning(str(content))
                seasons = Counter(x.season for x in content)
                num_seasons = len(seasons)
                num_episodes = sum(seasons.values())

            info(
                f"{str(content)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"
            )

        return content, title

    def get_episode_from_url(self, url: str):
        with self.console.status("Fetching title..."):
            episode_id = urlparse(url).path.split("/")[2]

            data = self.client.get(f"{self.api}{episode_id}").json()
            title = self.client.get(f"{self.api}{data['series']['meta']['id']}").json()["title"]
        
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
                    description=data.get("description")
                )
            ]
        )

        title = string_cleaning(str(episode))

        return [episode[0]], title

    def get_options(self) -> None:
        opt = Options(self)

        if self.url and not any(
            [self.episode, self.season, self.complete, self.movie, self.titles]
        ):
            error("URL is missing an argument. See --help for more information")
            return

        if is_url(self.episode):
            downloads, title = self.get_episode_from_url(self.episode)

        else: 
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

        if not downloads:
            error("Requested data returned empty. See --help for more information")
            return
            
        for download in downloads:
            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        pssh = "AAAAKXBzc2gAAAAA7e+LqXnWSs6jyCfc1R0h7QAAAAkiASpI49yVmwY="

        with self.console.status("Getting media info..."):
            lic_url, manifest = self.get_playlist(stream.data)
            self.res, audio = self.get_mediainfo(manifest, self.quality)

        keys = self.get_keys(pssh, lic_url)
        with open(self.tmp / "keys.txt", "w") as file:
            file.write("\n".join(keys))

        if self.info:
            print_info(self, stream, keys)

        self.filename = set_filename(self, stream, self.res, audio)
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        info(f"{str(stream)}")
        for key in keys:
            info(f"{key}")
        click.echo("")

        args, file_path = get_args(self)

        if not file_path.exists():
            try:
                subprocess.run(args, check=True)
            except Exception as e:
                raise ValueError(f"{e}")
        else:
            info(f"{self.filename} already exist. Skipping download\n")
            self.sub_path.unlink() if self.sub_path else None
            pass