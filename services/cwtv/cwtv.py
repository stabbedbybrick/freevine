"""
The CW
Author: stabbedbybrick

Info:
CWTV is 1080p, AAC 2.0 max

"""
from __future__ import annotations

import subprocess
import asyncio
import re

from collections import Counter
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import click
import m3u8
import yaml
import httpx

from bs4 import BeautifulSoup

from utils.utilities import (
    info,
    error,
    is_url,
    string_cleaning,
    set_save_path,
    print_info,
    set_filename,
    get_wvd,
)
from utils.titles import Episode, Series, Movie, Movies
from utils.options import Options
from utils.args import get_args
from utils.config import Config
from utils.cdm import LocalCDM


class CW(Config):
    def __init__(self, config, srvc_api, srvc_config, **kwargs):
        super().__init__(config, srvc_api, srvc_config, **kwargs)

        with open(self.srvc_api, "r") as f:
            self.config.update(yaml.safe_load(f))

        self.use_shaka_packager = True
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

    def get_data(self, url: str) -> dict:
        r = self.client.get(url)
        if not r.is_success:
            error(f"Response: {r.status_code}")
            exit(1)

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
                    id_=None,
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
                    id_=None,
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
        soup = BeautifulSoup(self.client.get(mpx).text, "xml")

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
            self.soup = BeautifulSoup(self.client.get(manifest), "xml")
            pssh = self.get_pssh(self.soup)
            res = self.get_dash_quality(self.soup, quality)

        if manifest.endswith(".m3u8"):
            self.hls = True
            pssh = None
            res = self.get_hls_quality(manifest, quality)

        return res, pssh

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
        episode = self.get_series(url)
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
        with self.console.status("Getting media info..."):
            manifest, lic_url = self.get_playlist(stream.data)
            self.res, pssh = self.get_mediainfo(manifest, self.quality)

        keys = None
        if lic_url:
            keys = self.get_keys(pssh, lic_url)
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        if self.info:
            print_info(self, stream, keys)

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self.config, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt" if keys else None
        self.sub_path = None

        info(f"{str(stream)}")
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
