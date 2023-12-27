"""
CTV
Author: stabbedbybrick

Quality: up to 1080p and Dolby 5.1 audio

"""
from __future__ import annotations

import asyncio
import json
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
    from_mpd,
    get_wvd,
    pssh_from_init,
    set_filename,
    set_save_path,
    string_cleaning,
    force_numbering,
)


class CTV(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        self.lic_url = self.config["lic"]
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

    def get_title_id(self, url: str) -> str:
        path = urlparse(url).path

        payload = {
            "operationName": "resolvePath",
            "variables": {"path": f"{path}"},
            "query": """
            query resolvePath($path: String!) {
                resolvedPath(path: $path) {
                    lastSegment {
                        content {
                            id
                        }
                    }
                }
            }
            """,
        }
        r = self.client.post(self.api, json=payload).json()
        return r["data"]["resolvedPath"]["lastSegment"]["content"]["id"]

    def get_series_data(self, url: str) -> json:
        title_id = self.get_title_id(url)

        payload = {
            "operationName": "axisMedia",
            "variables": {"axisMediaId": f"{title_id}"},
            "query": """
                query axisMedia($axisMediaId: ID!) {
                    contentData: axisMedia(id: $axisMediaId) {
                        title
                        description
                        originalSpokenLanguage
                        mediaType
                        firstAirYear
                        seasons {
                            title
                            id
                            seasonNumber
                        }
                    }
                }
                """,
        }

        return self.client.post(self.api, json=payload).json()["data"]

    def get_movie_data(self, url: str) -> json:
        title_id = self.get_title_id(url)

        payload = {
            "operationName": "axisMedia",
            "variables": {"axisMediaId": f"{title_id}"},
            "query": """
                query axisMedia($axisMediaId: ID!) {
                    contentData: axisMedia(id: $axisMediaId) {
                        title
                        description
                        firstAirYear
                        firstPlayableContent {
                            axisId
                            axisPlaybackLanguages {
                                destinationCode
                            }
                        }
                    }
                }
                """,
        }

        return self.client.post(self.api, json=payload).json()["data"]

    async def fetch_titles(self, async_client: httpx.AsyncClient, id: str) -> json:
        payload = {
            "operationName": "season",
            "variables": {"seasonId": f"{id}"},
            "query": """
                query season($seasonId: ID!) {
                    axisSeason(id: $seasonId) {
                        episodes {
                            axisId
                            title
                            description
                            contentType
                            seasonNumber
                            episodeNumber
                            axisPlaybackLanguages {
                                language
                                destinationCode
                            }
                        }
                    }
                }
                """,
        }
        response = await async_client.post(self.api, json=payload)
        return response.json()["data"]["axisSeason"]["episodes"]

    async def get_titles(self, data: dict) -> list:
        async with httpx.AsyncClient() as async_client:
            tasks = [self.fetch_titles(async_client, x["id"]) for x in data]
            titles = await asyncio.gather(*tasks)
            return [episode for episodes in titles for episode in episodes]

    def get_series(self, url: str) -> Series:
        data = self.get_series_data(url)
        titles = asyncio.run(self.get_titles(data["contentData"]["seasons"]))

        return Series(
            [
                Episode(
                    id_=episode["axisId"],
                    service="CTV",
                    title=data["contentData"]["title"],
                    season=int(episode["seasonNumber"]),
                    number=int(episode["episodeNumber"]),
                    name=episode["title"],
                    year=data["contentData"]["firstAirYear"],
                    data=episode["axisPlaybackLanguages"][0]["destinationCode"],
                    synopsis=data["contentData"].get("description"),
                    description=episode.get("description"),
                )
                for episode in titles
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_movie_data(url)

        return Movies(
            [
                Movie(
                    id_=data["contentData"]["firstPlayableContent"]["axisId"],
                    service="CTV",
                    title=data["contentData"]["title"],
                    year=data["contentData"]["firstAirYear"],
                    name=data["contentData"]["title"],
                    data=data["contentData"]["firstPlayableContent"][
                        "axisPlaybackLanguages"
                    ][0]["destinationCode"],
                    synopsis=data["contentData"].get("description"),
                )
            ]
        )

    def get_playlist(self, hub: str, id: str) -> tuple:
        base = f"https://capi.9c9media.com/destinations/{hub}/platforms/desktop"

        r = self.client.get(f"{base}/contents/{id}/contentPackages")
        r.raise_for_status()

        pkg_id = r.json()["Items"][0]["Id"]
        base += "/playback/contents"

        manifest = f"{base}/{id}/contentPackages/{pkg_id}/manifest.mpd?filter="
        subtitle = f"{base}/{id}/contentPackages/{pkg_id}/manifest.vtt"
        return manifest, subtitle

    def get_init(self, soup):
        base = soup.select_one("BaseURL").text

        rep_id = soup.select_one("Representation").attrs.get("id")
        template = (
            soup.select_one("SegmentTemplate")
            .attrs.get("initialization")
            .replace("$RepresentationID$", f"{rep_id}")
        )

        r = self.client.get(f"{base}{template}")
        r.raise_for_status()

        with open(self.tmp / "init.mp4", "wb") as f:
            f.write(r.content)

        return pssh_from_init(Path(self.tmp / "init.mp4"))

    async def fetch_manifests(self, async_client: httpx.AsyncClient, url: str):
        try:
            response = await async_client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError:
            pass

        return from_mpd(response.text, url)

    async def parse_manifests(self, data: dict) -> list:
        async with httpx.AsyncClient() as async_client:
            tasks = [self.fetch_manifests(async_client, x) for x in data]
            return await asyncio.gather(*tasks)

    def get_mediainfo(self, manifest: str, quality: str, subtitle: str) -> str:
        content = asyncio.run(
            self.parse_manifests([manifest + num for num in ["14", "3", "25"]])
        )

        for streams in content:
            for track in streams:
                height = track.get("height", "")

                if "1080" in height or "720" in height:
                    manifest = streams[0].get("url")
                else:
                    manifest = manifest

        r = self.client.get(manifest)
        self.soup = BeautifulSoup(r.text, "xml")

        tags = self.soup.find_all("Representation")
        codecs = [x.attrs["codecs"] for x in tags if x.attrs.get("codecs")]
        heights = sorted(
            [int(x.attrs["height"]) for x in tags if x.attrs.get("height")],
            reverse=True,
        )

        audio = "DD5.1" if "ac-3" in codecs else "AAC2.0"

        self.soup = add_subtitles(self.soup, subtitle)

        with open(self.tmp / "manifest.mpd", "w") as f:
            f.write(str(self.soup.prettify()))

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

                if self.force_numbering:
                    content = force_numbering(content)

            self.log.info(
                f"{str(content)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"
            )

        return content, title

    def get_episode_from_url(self, url: str):
        with self.console.status("Getting episode from URL..."):
            title_id = self.get_title_id(url)

            payload = {
                "operationName": "axisContent",
                "variables": {"id": f"{title_id}"},
                "query": """
                    query axisContent($id: ID!) {
                        axisContent(id: $id) {
                            axisId
                            title
                            description
                            contentType
                            seasonNumber
                            episodeNumber
                            axisMedia {
                                title
                            }
                            axisPlaybackLanguages {
                                    language
                                    destinationCode
                            }
                        }
                    }
                    """,
            }

            data = self.client.post(self.api, json=payload).json()["data"]["axisContent"]

            episode = Series(
                [
                    Episode(
                        id_=data["axisId"],
                        service="CTV",
                        title=data["axisMedia"]["title"],
                        season=int(data["seasonNumber"]),
                        number=int(data["episodeNumber"]),
                        name=data["title"],
                        year=None,
                        data=data["axisPlaybackLanguages"][0]["destinationCode"],
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
            manifest, subtitle = self.get_playlist(stream.data, stream.id)
            self.res, audio = self.get_mediainfo(manifest, self.quality, subtitle)
            pssh = self.get_init(self.soup)

        keys = self.get_keys(pssh, self.lic_url)
        with open(self.tmp / "keys.txt", "w") as file:
            file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio)
        self.save_path = set_save_path(stream, self, title)
        self.manifest = self.tmp / "manifest.mpd"
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
