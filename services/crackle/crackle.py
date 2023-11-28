"""
Credit to rlaphoenix for the title storage

CRACKLE
Author: stabbedbybrick

Info:

"""
from __future__ import annotations

import subprocess
import json
import shutil
import sys
import base64

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
    kid_to_pssh,
    get_wvd,
    geo_error,
)
from utils.titles import Episode, Series, Movie, Movies
from utils.options import get_downloads
from utils.args import get_args
from utils.info import print_info
from utils.config import Config
from utils.cdm import LocalCDM


class CRACKLE(Config):
    def __init__(self, config, srvc_api, srvc_config, **kwargs):
        super().__init__(config, srvc_api, srvc_config, **kwargs)

        with open(self.srvc_api, "r") as f:
            self.config.update(yaml.safe_load(f))

        self.api = self.config["api"]
        self.client = httpx.Client(
            headers={
                "user-agent": "Chrome/117.0.0.0 Safari/537.36",
                "x-crackle-platform": self.config["key"],
            },
            follow_redirects=True,
        )

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
        self.video_id = urlparse(url).path.split("/")[2]

        r = self.client.get(f"{self.api}/content/{self.video_id}")
        if not r.is_success:
            geo_error(r.status_code, r.json()["error"]["message"], location="US")

        return r.json()["data"]

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)

        r = self.client.get(f"{self.api}/content/{self.video_id}/children").json()

        seasons = [
            self.client.get(f"{self.api}/content/{x['id']}/children").json()
            for x in r["data"]
        ]

        return Series(
            [
                Episode(
                    id_=None,
                    service="CRKL",
                    title=data["metadata"][0]["title"],
                    season=int(episode["seasonNumber"]),
                    number=int(episode["episodeNumber"]),
                    name=episode["title"],
                    year=None,
                    data=episode["id"],
                    description=episode.get("shortDescription"),
                )
                for season in seasons
                for episode in season["data"]
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)

        r = self.client.get(f"{self.api}/content/{self.video_id}/children").json()

        return Movies(
            [
                Movie(
                    id_=None,
                    service="CRKL",
                    title=data["metadata"][0]["title"],
                    year=data["metadata"][0]["releaseDate"].split("-")[0]
                    if data["metadata"][0]["releaseDate"] is not None
                    else None,
                    name=data["metadata"][0]["title"],
                    data=r["data"][0]["id"],
                    synopsis=data["metadata"][0].get("longDescription"),
                )
            ]
        )

    def get_playlist(self, id: str) -> tuple:
        r = self.client.get(f"{self.api}/playback/vod/{id}").json()

        manifest = [
            source["url"].replace("session", "dash")
            for source in r["data"]["streams"]
            if source.get("type") == "dash-widevine"
        ][0]

        lic_url = [
            source["drm"]["keyUrl"]
            for source in r["data"]["streams"]
            if source.get("type") == "dash-widevine"
        ][0]

        return lic_url, manifest


    def get_mediainfo(self, manifest: str, quality: str) -> str:
        soup = BeautifulSoup(self.client.get(manifest), "xml")
        new_manifest = soup.select_one("BaseURL").text + "index.mpd"
        self.soup = BeautifulSoup(self.client.get(new_manifest), "xml")
        elements = self.soup.find_all("Representation")
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
        parse = urlparse(url).path.split("/")
        s = parse[3].replace("-", " ")
        show = " ".join(word[0].upper() + word[1:] for word in s.split(" "))
        episode_id = parse[2]
        
        data = self.client.get(f"{self.api}/content/{episode_id}").json()["data"]["metadata"][0]

        episode = Series(
            [
                Episode(
                    id_=None,
                    service="CRKL",
                    title=show,
                    season=int(data["seasonNumber"]),
                    number=int(data["episodeNumber"]),
                    name=data["title"],
                    year=None,
                    data=episode_id,
                    description=data.get("shortDescription"),
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
            lic_url, manifest = self.get_playlist(stream.data)
            self.res = self.get_mediainfo(manifest, self.quality)
            pssh = kid_to_pssh(self.soup)

        keys = self.get_keys(pssh, lic_url)
        with open(self.tmp / "keys.txt", "w") as file:
            file.write("\n".join(keys))

        if self.info:
            print_info(self, stream, keys)

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
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