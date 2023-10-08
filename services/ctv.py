"""
CTV
Author: stabbedbybrick

Quality: up to 1080p and Dolby 5.1 audio

"""

import base64
import subprocess
import json
import asyncio
import shutil
import sys

from urllib.parse import urlparse
from pathlib import Path
from collections import Counter

import click
import httpx

from bs4 import BeautifulSoup

from helpers.utilities import (
    info,
    string_cleaning,
    set_save_path,
    print_info,
    add_subtitles,
    set_filename,
)
from helpers.cdm import local_cdm, remote_cdm
from helpers.titles import Episode, Series, Movie, Movies
from helpers.args import Options, get_args
from helpers.config import Config


class CTV(Config):
    def __init__(self, config, srvc, **kwargs):
        super().__init__(config, srvc, **kwargs)

        self.lic_url = self.srvc["ctv"]["lic"]
        self.api = self.srvc["ctv"]["api"]
        
        self.get_options()

    def get_title_id(self, url: str) -> str:
        url = url.rstrip("/")
        parse = urlparse(url).path.split("/")
        type = parse[1]
        slug = parse[-1]

        payload = {
            "operationName": "resolvePath",
            "variables": {"path": f"/{type}/{slug}"},
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
        if not r.is_success:
            print(f"\nError! {r.status_code}")
            shutil.rmtree(self.tmp)
            sys.exit(1)

        pkg_id = r.json()["Items"][0]["Id"]
        base += "/playback/contents"

        manifest = f"{base}/{id}/contentPackages/{pkg_id}/manifest.mpd?filter=fe&mca=true&mta=true"
        subtitle = f"{base}/{id}/contentPackages/{pkg_id}/manifest.vtt"
        return manifest, subtitle

    def get_pssh(self, soup):
        try:
            base = soup.select_one("BaseURL").text
        except AttributeError:
            raise AttributeError("Failed to fetch manifest. Possible GEO block")

        rep_id = soup.select_one("Representation").attrs.get("id")
        template = (
            soup.select_one("SegmentTemplate")
            .attrs.get("initialization")
            .replace("$RepresentationID$", f"{rep_id}")
        )

        r = self.client.get(f"{base}{template}")

        with open(self.tmp / "init.mp4", "wb") as f:
            f.write(r.content)

        path = Path(self.tmp / "init.mp4")
        raw = Path(path).read_bytes()
        wv = raw.rfind(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
        if wv == -1:
            return None
        return base64.b64encode(raw[wv - 12 : wv - 12 + raw[wv - 9]]).decode("utf-8")

    def get_mediainfo(self, manifest: str, quality: str, subtitle: str) -> str:
        soup = BeautifulSoup(self.client.get(manifest), "xml")
        pssh = self.get_pssh(soup)

        soup.find("AdaptationSet", {"contentType": "video"}).append(
            soup.new_tag(
                "Representation",
                id="h264-ffa6v1-30p-primary-7200000",
                codecs="avc1.64001f",
                mimeType="video/mp4",
                width="1920",
                height="1080",
                bandwidth="7200000",
            )
        )

        elements = soup.find_all("Representation")
        codecs = [x.attrs["codecs"] for x in elements if x.attrs.get("codecs")]
        heights = sorted(
            [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
            reverse=True,
        )

        audio = "DD5.1" if "ac-3" in codecs else "AAC2.0"

        self.soup = add_subtitles(soup, subtitle)

        with open(self.tmp / "manifest.mpd", "w") as f:
            f.write(str(self.soup.prettify()))

        if quality is not None:
            if int(quality) in heights:
                return quality, pssh, audio
            else:
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                info(f"Resolution not available. Getting closest match:")
                return closest_match, pssh, audio

        return heights[0], pssh, audio

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

    def get_options(self) -> None:
        opt = Options(self)
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

        for download in downloads:
            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        with self.console.status("Getting media info..."):
            manifest, subtitle = self.get_playlist(stream.data, stream.id)
            res, pssh, audio = self.get_mediainfo(manifest, self.quality, subtitle)

        with self.console.status("Getting decryption keys..."):
            keys = (
                remote_cdm(pssh, self.lic_url, self.client)
                if self.remote
                else local_cdm(pssh, self.lic_url, self.client)
            )
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        self.filename = set_filename(self, stream, res, audio)
        self.save_path = set_save_path(stream, self.config, title)
        self.manifest = self.tmp / "manifest.mpd"
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        if self.info:
            print_info(self, stream, keys)

        info(f"{str(stream)}")
        for key in keys:
            info(f"{key}")
        click.echo("")

        args, file_path = get_args(self, res)

        if not file_path.exists():
            try:
                subprocess.run(args, check=True)
            except:
                raise ValueError("Download failed or was interrupted")
        else:
            info(f"{self.filename} already exist. Skipping download\n")
            self.sub_path.unlink() if self.sub_path else None
            pass