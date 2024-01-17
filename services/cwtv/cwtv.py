"""
The CW
Author: stabbedbybrick

Info:
CWTV is 1080p, AAC 2.0 max

"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import click
import httpx
import m3u8
from bs4 import BeautifulSoup

from utils.args import get_args
from utils.cdm import LocalCDM
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    force_numbering,
    get_wvd,
    in_cache,
    set_filename,
    set_save_path,
    string_cleaning,
    update_cache,
)



class CW(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        with self.config["download_cache"].open("r") as file:
            self.cache = json.load(file)

        self.use_shaka_packager = True
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

    def get_data(self, url: str) -> dict:
        r = self.client.get(url)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        container = soup.find("div", id="video-thumbs-container")
        thumbs = container.find_all("a", class_="thumbLink")
        return [x.get("href").split("=")[1] for x in thumbs if "play" in x.get("href")]

    async def get_title_data(self, async_client, id: str):
        r = await async_client.get(self.config["vod"].format(guid=id))
        return r.json()["video"]

    async def get_titles(self, data: list) -> list:
        async with httpx.AsyncClient() as async_client:
            tasks = [self.get_title_data(async_client, x) for x in data]

            return await asyncio.gather(*tasks)

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)
        episodes = asyncio.run(self.get_titles(data))

        return Series(
            [
                Episode(
                    id_=episode["guid"],
                    service="CW",
                    title=episode.get("series_name"),
                    season=int(episode.get("season")) or 0,
                    number=int(episode.get("episode")[1:]) or 0,
                    name=episode.get("title"),
                    year=None,
                    data=episode.get("mpx_url"),
                    description=episode.get("description_long"),
                )
                for episode in episodes
                if episode["fullep"] == 1
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)
        movies = asyncio.run(self.get_titles(data))

        return Movies(
            [
                Movie(
                    id_=movie["guid"],
                    service="CW",
                    title=movie.get("title"),
                    name=movie.get("title"),
                    year=movie.get("airdate", "").split("-")[0],
                    data=movie.get("mpx_url"),
                    synopsis=movie.get("description_long"),
                )
                for movie in movies
                if movie["fullep"] == 1
            ]
        )

    def get_playlist(self, playlist: str, lic_url=None) -> tuple:
        parse = urlparse(playlist)
        mpx = urlunparse(parse._replace(query=self.config["dash"]))
        r = self.client.get(mpx)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "xml")

        manifest = soup.video.get("src")
        drm = soup.find("param", {"name": "isDRM"}).get("value")

        if drm == "true":
            video_id = soup.find("param", {"name": "videoId"}).get("value")
            pid = soup.find("param", {"name": "pidHLSClear"}).get("value")
            tracker = soup.find("param", {"name": "trackingData"}).get("value")
            account, user = re.search(r"aid=(\d+).*d=(\d+)", tracker).groups()

            token = self.client.get(
                self.config["cred"].format(video_id=video_id, user=user)
            ).json()["signInResponse"]["token"]

            lic_url = self.config["lic"].format(acc=account, pid=pid, token=token)

        return manifest, lic_url

    def get_pssh(self, soup: str) -> str:
        system = re.compile(
            r"urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed", re.IGNORECASE
        )
        return soup.find("ContentProtection", {"schemeIdUri": system}).text

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

    def get_hls_quality(self, manifest: str, quality: str) -> str:
        r = self.client.get(manifest)
        r.raise_for_status()
        m3u8_obj = m3u8.loads(r.text)

        playlists = []
        if m3u8_obj.is_variant:
            for playlist in m3u8_obj.playlists:
                playlists.append(playlist.stream_info.resolution[1])

            heights = sorted([x for x in playlists], reverse=True)
            res = heights[0]

        if quality is not None:
            if int(quality) in heights:
                res = quality
            else:
                res = min(heights, key=lambda x: abs(int(x) - int(quality)))

        return res

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        if manifest.endswith(".mpd"):
            r = self.client.get(manifest)
            r.raise_for_status()
            self.soup = BeautifulSoup(r.content, "xml")
            pssh = self.get_pssh(self.soup)
            res = self.get_dash_quality(self.soup, quality)

        if manifest.endswith(".m3u8"):
            pssh = None
            res = self.get_hls_quality(manifest, quality)

        return res, pssh

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
            id = url.split("=")[1]
            r = self.client.get(self.config["vod"].format(guid=id))
            r.raise_for_status()

            data = r.json().get("video")

            episode = Series(
                [
                    Episode(
                        id_=data["guid"],
                        service="CW",
                        title=data.get("series_name"),
                        season=int(data.get("season")) or 0,
                        number=int(data.get("episode")[1:]) or 0,
                        name=data.get("title"),
                        year=None,
                        data=data.get("mpx_url"),
                        description=data.get("description_long"),
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
        manifest, lic_url = self.get_playlist(stream.data)
        self.res, pssh = self.get_mediainfo(manifest, self.quality)

        keys = None
        if lic_url:
            keys = self.get_keys(pssh, lic_url)
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
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
            self.log.info(f"{self.filename} already exists. Skipping download...\n")
            self.sub_path.unlink() if self.sub_path else None
        
        if not self.skip_download and file_path.exists():
            update_cache(self.cache, self.config, stream)
