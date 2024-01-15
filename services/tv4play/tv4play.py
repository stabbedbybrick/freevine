"""
TV4Play
Author: stabbedbybrick

Quality: up to 1080p, AAC2.0

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
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    force_numbering,
    from_m3u8,
    get_cookie,
    get_wvd,
    kid_to_pssh,
    load_cookies,
    set_filename,
    set_save_path,
    string_cleaning,
    in_cache,
    update_cache,
)


class TV4Play(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        with self.config["download_cache"].open("r") as file:
            self.cache = json.load(file)

        self.authenticate()
        self.get_options()

    def get_license(self, challenge: bytes, lic_url: str, token: str) -> bytes:
        headers = {"x-dt-auth-token": token}
        r = self.client.post(url=lic_url, headers=headers, data=challenge)
        r.raise_for_status()
        return r.content

    def get_keys(self, pssh: str, lic_url: str, token: str) -> bytes:
        wvd = get_wvd(Path.cwd())
        widevine = LocalCDM(wvd)
        challenge = widevine.challenge(pssh)
        response = self.get_license(challenge, lic_url, token)
        return widevine.parse(response)

    def get_title_id(self, url: str) -> str:
        return urlparse(url).path.split("/")[2]

    def series_data(self, media_id: str) -> json:
        payload = {
            "operationName": "ContentDetailsPage",
            "variables": {
                "mediaId": f"{media_id}",
                "panelsInput": {"offset": 0, "limit": 20},
            },
            "query": """
                query ContentDetailsPage($mediaId: ID!) {
                    media(id: $mediaId) {
                        ... on Series {
                            allSeasonLinks {seasonId}}}}""",
        }

        r = self.client.post(self.config["content"], json=payload)
        if not r.ok:
            raise ConnectionError(r.content)

        return r.json()["data"]

    def movie_data(self, movie_id: str) -> json:
        payload = {
            "operationName": "Video",
            "variables": {"id": f"{movie_id}"},
            "query": """
                query Video($id: ID!) {
                    media(id: $id) {
                        ... on Movie {
                        id
                        title
                        productionYear
                        isDrmProtected
                        }
                    }
                }""",
        }

        r = self.client.post(self.config["content"], json=payload)
        if not r.ok:
            raise ConnectionError(r.content)

        return r.json()["data"]["media"]

    async def season_data(
        self, season_id: str, async_client: httpx.AsyncClient
    ) -> json:
        payload = {
            "operationName": "SeasonEpisodes",
            "variables": {
                "input": {"limit": 100, "offset": 0},
                "seasonId": season_id,
            },
            "query": """
                query SeasonEpisodes($seasonId: ID!, $input: SeasonEpisodesInput!) {
                    season(id: $seasonId) {
                        episodes(input: $input) {items {id}}}}""",
        }

        r = await async_client.post(self.config["content"], json=payload)
        if not r.is_success:
            raise ConnectionError(r.content)

        return r.json()["data"]

    async def episode_data(
        self, episode_id: str, async_client: httpx.AsyncClient
    ) -> json:
        payload = {
            "operationName": "Video",
            "variables": {"id": f"{episode_id}"},
            "query": """
                query Video($id: ID!) {
                    media(id: $id) {
                        ... on Episode {
                            id
                            title
                            extendedTitle
                            isDrmProtected
                            series {
                                title
                            }
                        }
                    }
                }""",
        }

        r = await async_client.post(self.config["content"], json=payload)
        if not r.is_success:
            raise ConnectionError(r.content)

        return r.json()["data"]

    async def get_season_data(self, season_ids: list) -> list:
        async with httpx.AsyncClient(headers=self.client.headers) as async_client:
            tasks = [self.season_data(x, async_client) for x in season_ids]
            titles = await asyncio.gather(*tasks)
            return titles

    async def get_episode_data(self, episode_ids: list) -> list:
        async with httpx.AsyncClient(headers=self.client.headers) as async_client:
            tasks = [self.episode_data(x, async_client) for x in episode_ids]
            titles = await asyncio.gather(*tasks)
            return titles

    def get_series(self, url: str) -> Series:
        media_id = self.get_title_id(url)
        data = self.series_data(media_id)

        season_ids = [x["seasonId"] for x in data["media"]["allSeasonLinks"]]
        seasons = asyncio.run(self.get_season_data(season_ids))

        episode_ids = [
            x["id"] for s in seasons for x in s["season"]["episodes"]["items"]
        ]
        episodes = asyncio.run(self.get_episode_data(episode_ids))

        return Series(
            [
                Episode(
                    id_=episode["media"]["id"],
                    service="TV4",
                    title=episode["media"]["series"]["title"],
                    season=int(re.search(r"Säsong (\d+)", episode["media"]["extendedTitle"]).group(1)),
                    number=int(re.search(r"Avsnitt (\d+)", episode["media"]["extendedTitle"]).group(1)),
                    name=episode["media"]["title"],
                    year=None,
                    drm=episode["media"]["isDrmProtected"],
                )
                for episode in episodes
            ]
        )

    def get_movies(self, url: str) -> Movies:
        media_id = self.get_title_id(url)
        movie = self.movie_data(media_id)

        return Movies(
            [
                Movie(
                    id_=movie["id"],
                    service="TV4",
                    title=movie["title"],
                    year=movie.get("productionYear"),
                    name=movie["title"],
                    drm=movie["isDrmProtected"],
                )
            ]
        )

    def get_playlist(self, video_id: str) -> tuple:
        lic_url = None
        token = None

        data = self.client.get(self.config["vod"].format(id=video_id)).json()
        manifest = data["playbackItem"]["manifestUrl"].split("?")[0]

        if data["metadata"]["isDrmProtected"]:
            self.log.warning("Video is DRM protected\n")
            lic_url = data["playbackItem"]["license"].get("castlabsServer")
            token = data["playbackItem"]["license"].get("castlabsToken")
            manifest = manifest.replace("m3u8", "mpd")


        return manifest, lic_url, token

    def get_dash_info(self, manifest: str, quality: str, pssh: str = None) -> tuple:
        r = self.client.get(manifest)
        soup = BeautifulSoup(r.text, "xml")
        pssh = kid_to_pssh(soup)

        tags = soup.find_all("Representation")
        heights = sorted(
            [int(x.attrs["height"]) for x in tags if x.attrs.get("height")],
            reverse=True,
        )
        
        if quality is not None:
            if int(quality) in heights:
                resolution = quality
            else:
                resolution = min(heights, key=lambda x: abs(int(x) - int(quality)))

        return resolution, pssh

    def get_hls_info(self, manifest: str, quality: str, pssh: str = None) -> tuple:
        r = self.client.get(manifest)
        r.raise_for_status()
        heights, codecs = from_m3u8(r.text)

        heights = sorted(heights, reverse=True)
        
        if quality is not None:
            if int(quality) in heights:
                resolution = quality
            else:
                resolution = min(heights, key=lambda x: abs(int(x) - int(quality)))

        return resolution, pssh

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
            media_id = self.get_title_id(url)
            episodes = asyncio.run(self.get_episode_data([media_id]))

            episode = Series(
                [
                    Episode(
                    id_=episode["media"]["id"],
                    service="TV4",
                    title=episode["media"]["series"]["title"],
                    season=int(re.search(r"Säsong (\d+)", episode["media"]["extendedTitle"]).group(1)),
                    number=int(re.search(r"Avsnitt (\d+)", episode["media"]["extendedTitle"]).group(1)),
                    name=episode["media"]["title"],
                    year=None,
                    drm=episode["media"]["isDrmProtected"],
                )
                    for episode in episodes
                ]
            )

        title = string_cleaning(str(episode))

        try:
            return [episode[0]], title
        except IndexError:
            self.log.error(
                "Episode not found. If this is a standalone episode, try the '--movie' argument instead"
            )
            sys.exit(1)

    def authenticate(self):
        if not self.config.get("cookies"):
            self.log.error("Required cookie file is missing")
            sys.exit(1)

        cookie_jar = load_cookies(self.config["cookies"])
        cookie = get_cookie(cookie_jar, "tv4-refresh-token")

        if time.time() > cookie["expires"]:
            self.log.error("Cookies have expired and need to be replaced")
            sys.exit(1)

        payload = {
            "refresh_token": cookie["value"],
            "client_id": "tv4-web",
            "profile_id": "default",
        }

        r = self.client.post(self.config["refresh"], json=payload)
        if not r.ok:
            raise ConnectionError(r.json())

        self.client.headers.update(
            {
                "content-type": "application/json",
                "authorization": f"Bearer {r.json()['access_token']}",
                "client-name": "tv4-web",
                "client-version": "4.0.0",
            }
        )

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
        manifest, lic_url, token = self.get_playlist(stream.id)
        self.res, pssh = self.get_mediainfo(manifest, self.quality)

        keys = None
        if stream.drm and lic_url:
            keys = self.get_keys(pssh, lic_url, token)
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt" if keys else None
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
