"""
Credit to rlaphoenix for the title storage

ROKU
Author: stabbedbybrick

Info:
This program will grab higher 1080p bitrate and Dolby 5.1 audio (if available)

"""
from __future__ import annotations

import concurrent.futures
import json
import re
import subprocess
import time
import urllib
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import click
from bs4 import BeautifulSoup

from utils.args import get_args
from utils.cdm import LocalCDM
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    append_id,
    force_numbering,
    get_wvd,
    in_cache,
    set_filename,
    set_save_path,
    string_cleaning,
    update_cache,
)


class ROKU(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        with self.config["download_cache"].open("r") as file:
            self.cache = json.load(file)

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

        try:
            data = json.loads(r.content)
        except json.JSONDecodeError:
            raise ConnectionError("Roku video is unavailable in your location")

        return data

    def fetch_episode(self, episode: dict) -> json:
        return self.client.get(f"{self.api}" + episode["meta"]["id"]).json()

    def fetch_episodes(self, data: dict) -> list:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            tasks = list(executor.map(self.fetch_episode, data["episodes"]))
        return tasks

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)
        episodes = self.fetch_episodes(data)

        return Series(
            [
                Episode(
                    id_=episode["meta"]["id"],
                    service="ROKU",
                    title=data["title"],
                    season=int(episode["seasonNumber"]),
                    number=int(episode["episodeNumber"]),
                    name=episode["title"],
                    year=data["releaseYear"],
                    data=None,
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
                    id_=data["meta"]["id"],
                    service="ROKU",
                    title=data["title"],
                    year=data["releaseYear"],
                    name=data["title"],
                    data=None,
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

        lic_url = next(
            (
                x["drmParams"]["licenseServerURL"]
                for x in videos
                if x.get("drmParams") and x["drmParams"]["keySystem"] == "Widevine"
            ),
            None,
        )

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

        else:
            with self.console.status("Fetching series titles..."):
                content = self.get_series(url)

                title = string_cleaning(str(content))
                seasons = Counter(x.season for x in content)
                num_seasons = len(seasons)
                num_episodes = sum(seasons.values())

                if self.force_numbering:
                    content = force_numbering(content)
                if self.append_id:
                    content = append_id(content)

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
                        id_=episode_id,
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
            if not self.no_cache and in_cache(self.cache, download):
                continue

            if self.slowdown:
                with self.console.status(
                    f"Slowing things down for {self.slowdown} seconds..."
                ):
                    time.sleep(self.slowdown)

            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        pssh = "AAAAKXBzc2gAAAAA7e+LqXnWSs6jyCfc1R0h7QAAAAkiASpI49yVmwY="

        lic_url, manifest = self.get_playlist(stream.id)
        self.res, audio = self.get_mediainfo(manifest, self.quality)

        keys = None
        if lic_url is not None:
            keys = self.get_keys(pssh, lic_url)
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio)
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest
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
            self.log.warning(f"{self.filename} already exists. Skipping download...\n")
            self.sub_path.unlink() if self.sub_path else None
        
        if not self.skip_download and file_path.exists():
            update_cache(self.cache, self.config, stream)
