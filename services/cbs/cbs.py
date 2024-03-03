"""
CBS
Author: stabbedbybrick

Info:
1080p, DDP5.1

"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
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
from utils.titles import Episode, Series
from utils.utilities import (
    append_id,
    force_numbering,
    get_wvd,
    in_cache,
    kid_to_pssh,
    set_filename,
    set_save_path,
    string_cleaning,
    update_cache,
)


class CBS(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        with self.config["download_cache"].open("r") as file:
            self.cache = json.load(file)

        self.get_options()

    def get_license(self, challenge: bytes, lic_url: str) -> json:
        r = self.client.post(lic_url, data=challenge)
        r.raise_for_status()
        return r.content

    def get_keys(self, pssh: str, lic_url: str):
        wvd = get_wvd(Path.cwd())
        widevine = LocalCDM(wvd)
        challenge = widevine.challenge(pssh)
        response = self.get_license(challenge, lic_url)
        return widevine.parse(response)

    async def fetch_data(
        self, async_client: httpx.AsyncClient, season: str, show: str
    ) -> json:
        response = await async_client.get(
            self.config["api"].format(show=show, season=season)
        )
        try:
            return response.json()
        except json.JSONDecodeError:
            raise ConnectionError("Failed to fetch season data")

    async def get_season_data(self, seasons: list, show: str) -> list:
        async with httpx.AsyncClient() as async_client:
            tasks = [self.fetch_data(async_client, season, show) for season in seasons]

            return await asyncio.gather(*tasks)

    def get_data(self, url: str) -> dict:
        show = urlparse(url).path.split("/")[2]
        r = self.client.get(url)
        if not r.ok:
            raise ConnectionError(r.text)

        soup = BeautifulSoup(r.text, "html.parser")
        tags = soup.find_all("a", {"data-value": True})
        seasons = [tag["data-value"] for tag in tags]

        return asyncio.run(self.get_season_data(seasons, show))

    def get_series(self, url: str) -> Series:
        data: list = self.get_data(url)

        return Series(
            [
                Episode(
                    id_=episode["content_id"],
                    service="CBS",
                    title=episode["series_title"],
                    season=int(episode.get("season_number")) or 0,
                    number=int(episode.get("episode_number")) or 0,
                    name=episode.get("label") + " (Premium)"
                    if episode["is_paid_content"]
                    else episode.get("label"),
                    year=None,
                    data=episode["streaming_url"],
                    premium=episode["is_paid_content"],
                )
                for seasons in data
                for episode in seasons["result"]["data"]
                if episode["type"] == "Full Episode"
            ]
        )

    def get_config(self, content_id: str) -> tuple:
        r = self.client.get(self.config["vod"].format(content_id=content_id))
        if not r.ok:
            raise ConnectionError(r.text)

        drm: str = re.search(r"player.drm = (.+?);", r.text).group(1)
        drm: dict = json.loads(drm)

        token = drm["widevine"]["header"]["Authorization"]
        lic_url = drm["widevine"]["url"]

        return lic_url, token

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        r = self.client.get(manifest)
        soup = BeautifulSoup(r.content, "xml")
        elements = soup.find_all("Representation")
        codecs = [x.attrs["codecs"] for x in elements if x.attrs.get("codecs")]
        heights = sorted(
            [
                int(x.attrs["height"])
                for x in elements
                if x.attrs.get("height") and "thumb" not in x.attrs.get("id")
            ],
            reverse=True,
        )
        resolution = heights[0]

        if "ec-3" in codecs and self.select_audio == "False":
            audio = "DDP5.1"
        else:
            audio = "AAC2.0"

        if quality is not None:
            if int(quality) in heights:
                resolution = quality
            else:
                resolution = min(heights, key=lambda x: abs(int(x) - int(quality)))

        return resolution, soup, audio

    def get_content(self, url: str) -> object:
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
            r = self.client.get(url)
            if not r.ok:
                raise ConnectionError(r.text)

            player_api: str = re.search(r"player.apiMetadata = (.+?);", r.text).group(1)
            player_drm: str = re.search(r"player.drm = (.+?);", r.text).group(1)
            episode: dict = json.loads(player_api)
            drm: dict = json.loads(player_drm)

            self.client.headers.update(
                {"authorization": drm["widevine"]["header"]["Authorization"]}
            )

            episode = Series(
                [
                    Episode(
                        id_=episode["contentId"],
                        service="CBS",
                        title=episode.get("seriesTitle"),
                        season=int(episode.get("seasonNum")) or 0,
                        number=int(episode.get("episodeNum")) or 0,
                        name=episode.get("label"),
                        year=None,
                        data=episode.get("streamingUrl"),
                        lic_url=drm["widevine"]["url"],
                        description=episode.get("description"),
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
        if stream.premium:
            self.log.error("Premium content is not supported")
            sys.exit(1)

        if not stream.lic_url:
            stream.lic_url, token = self.get_config(stream.id)
            self.client.headers.update({"authorization": token})

        self.res, soup, audio = self.get_mediainfo(stream.data, self.quality)
        pssh = kid_to_pssh(soup)

        keys = self.get_keys(pssh, stream.lic_url)
        with open(self.tmp / "keys.txt", "w") as file:
            file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio)
        self.save_path = set_save_path(stream, self, title)
        self.manifest = stream.data
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        self.log.info(f"{str(stream)}")
        click.echo("")

        if self.skip_download:
            self.log.info(f"Filename: {self.filename}")

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
