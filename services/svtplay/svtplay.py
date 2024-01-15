"""
SVTPlay
Author: stabbedbybrick

Quality: up to 1080p and Dolby 5.1 audio

"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections import Counter
from urllib.parse import urlparse

import click
from bs4 import BeautifulSoup

from utils.args import get_args
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    force_numbering,
    from_m3u8,
    in_cache,
    set_filename,
    set_save_path,
    string_cleaning,
    update_cache,
)


FORMATS = [
    "dash-full", 
    "hls-ts-full", 
    "dash-hbbtv-avc",
    "hls-cmaf-full",
    "dash",
    "hls"
]

class SVTPlay(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        with self.config["download_cache"].open("r") as file:
            self.cache = json.load(file)

        self.get_options()

    def get_title_path(self, url: str) -> str:
        return urlparse(url).path

    def get_data(self, title_path: str) -> json:
        payload = {
            "extensions": {
                "persistedQuery": {
                    "sha256Hash": "db7dbde4e147ad2dde7384c864eb08e4b7140bd36d5ba80ed884ca77427d37d5",
                    "version": 1,
                },
            },
            "operationName": "DetailsPageQuery",
            "variables": {
                "history": [],
                "includeFullOppetArkiv": True,
                "path": f"{title_path}",
            },
        }

        return self.client.post(self.config["content"], json=payload).json()["data"][
            "detailsPageByPath"
        ]

    def get_series(self, url: str) -> Series:
        title_path = self.get_title_path(url)
        data = self.get_data(title_path)
        seasons = [
            x["items"]
            for x in data["associatedContent"]
            if not x["selectionType"] == "upcoming"
        ]

        return Series(
            [
                Episode(
                    id_=episode["item"]["videoSvtId"],
                    service="SVT",
                    title=data["item"]["name"],
                    season=int(re.search(
                    r"\w+ (\d+)", episode["item"]["positionInSeason"]).group(1))
                    if episode["item"].get("positionInSeason")
                    else 0,
                    number=int(re.search(
                    r"Avsnitt (\d+)", episode["item"]["positionInSeason"]).group(1))
                    if episode["item"].get("positionInSeason")
                    else 0,
                    name=episode["item"].get("nameRaw") or episode["item"].get("name"),
                    year=data["moreDetails"].get("productionYearRange")[:4],
                    data=None,
                )
                for season in seasons
                for episode in season
                if episode["item"]["__typename"] == "Episode"
            ]
        )

    def get_movies(self, url: str) -> Movies:
        title_path = self.get_title_path(url)
        data = self.get_data(title_path)

        return Movies(
            [
                Movie(
                    id_=data["video"]["svtId"],
                    service="SVT",
                    title=data["moreDetails"]["titleHeading"],
                    year=data["moreDetails"].get("productionYearRange")[:4],
                    name=data["moreDetails"]["titleHeading"],
                    data=None,
                )
            ]
        )
    

    def get_playlist(self, video_id: str) -> tuple:
        data = self.client.get(self.config["vod"].format(id=video_id)).json()
        manifest = next(
            (
                x["url"]
                for format in FORMATS
                for x in data["videoReferences"]
                if x["format"] == format
            ),
            None,
        )

        if not manifest:
            raise ValueError("Could not find a valid manifest")

        return manifest

    def get_dash_info(self, manifest: str, quality: str) -> tuple:
        r = self.client.get(manifest)
        self.soup = BeautifulSoup(r.text, "xml")

        tags = self.soup.find_all("Representation")
        codecs = [x.attrs["codecs"] for x in tags if x.attrs.get("codecs")]
        heights = sorted(
            [int(x.attrs["height"]) for x in tags if x.attrs.get("height")],
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

    def get_hls_info(self, manifest: str, quality: str) -> tuple:
        r = self.client.get(manifest)
        r.raise_for_status()
        heights, codecs = from_m3u8(r.text)

        heights = sorted(heights, reverse=True)
        audio = "DD5.1" if "ac-3" in codecs[0] else "AAC2.0"

        self.log.info("Subtitles for this format are currently not supported")
        self.drop_subtitle = "all" # TODO

        if quality is not None:
            if int(quality) in heights:
                return quality, audio
            else:
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                return closest_match, audio

        return heights[0], audio

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        if manifest.endswith(".mpd"):
            return self.get_dash_info(manifest, quality)
        if manifest.endswith(".m3u8"):
            return self.get_hls_info(manifest, quality)

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
            title_path = self.get_title_path(url)
            data = self.get_data(title_path)
            video_id = data["video"]["svtId"]

            seasons = [
                x["items"]
                for x in data["associatedContent"]
                if not x["selectionType"] == "upcoming"
            ]

            episode = Series(
                [
                    Episode(
                        id_=episode["item"]["videoSvtId"],
                        service="SVT",
                        title=data["item"]["parent"]["name"],
                        season=int(re.search(
                        r"\w+ (\d+)", episode["item"]["positionInSeason"]).group(1))
                        if episode["item"].get("positionInSeason")
                        else 0,
                        number=int(re.search(
                        r"Avsnitt (\d+)", episode["item"]["positionInSeason"]).group(1))
                        if episode["item"].get("positionInSeason")
                        else 0,
                        name=episode["item"].get("nameRaw")
                        or episode["item"].get("name"),
                        year=data["moreDetails"].get("productionYearRange")[:4],
                        data=None,
                    )
                    for season in seasons
                    for episode in season
                    if episode["item"]["videoSvtId"] == video_id
                ]
            )

        title = string_cleaning(str(episode))

        try:
            return [episode[0]], title
        except IndexError:
            self.log.error(
                "Episode not found. If this is a standalone episode, try the '--movie' argument instead")
            sys.exit(1)

    def get_options(self) -> None:
        downloads, title = get_downloads(self)

        for download in downloads:
            if in_cache(self.cache, download):
                continue

            if self.slowdown:
                with self.console.status(f"Slowing things down for {self.slowdown} seconds..."):
                    time.sleep(self.slowdown)

            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        manifest = self.get_playlist(stream.id)
        self.res, audio = self.get_mediainfo(manifest, self.quality)

        self.filename = set_filename(self, stream, self.res, audio)
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest
        self.key_file = None  # Not encrypted
        self.sub_path = None

        self.log.info(self.filename)
        click.echo("")

        try:
            subprocess.run(get_args(self), check=True)
        except Exception as e:
            self.sub_path.unlink() if self.sub_path else None
            raise ValueError(f"{e}")

        if not self.skip_download:
            update_cache(self.cache, self.config, stream)
