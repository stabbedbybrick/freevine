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
from rich.console import Console

from helpers.utilities import stamp, string_cleaning, set_range
from helpers.cdm import local_cdm, remote_cdm
from helpers.titles import Episode, Series, Movie, Movies


class CTV:
    def __init__(self, config, **kwargs) -> None:
        self.config = config
        self.tmp = Path("tmp")
        self.url = kwargs.get("url")
        self.quality = kwargs.get("quality")
        self.remote = kwargs.get("remote")
        self.titles = kwargs.get("titles")
        self.episode = kwargs.get("episode")
        self.season = kwargs.get("season")
        self.movie = kwargs.get("movie")
        self.complete = kwargs.get("complete")
        self.all_audio = kwargs.get("all_audio")

        self.lic_url = "https://license.9c9media.ca/widevine"
        self.api = "https://api.ctv.ca/space-graphql/graphql"
        self.console = Console()
        self.client = httpx.Client(
            headers={"user-agent": "Chrome/113.0.0.0 Safari/537.36"}
        )

        self.tmp.mkdir(parents=True, exist_ok=True)

        self.episode = self.episode.upper() if self.episode else None
        self.season = self.season.upper() if self.season else None
        self.quality = self.quality.rstrip("p") if self.quality else None

        self.list_titles() if self.titles else None
        self.get_episode() if self.episode else None
        self.get_season() if self.season else None
        self.get_complete() if self.complete else None
        self.get_movie() if self.movie else None

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
                        firstAirYear
                        firstPlayableContent {
                            axisId
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
                    data="ctvmovies_hub",  # TODO: Don't hardcode
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

    def get_mediainfo(self, manifest: str, quality: str) -> str:
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

        with open(self.tmp / "manifest.mpd", "w") as f:
            f.write(str(soup.prettify()))

        if quality is not None:
            if int(quality) in heights:
                return quality, pssh, audio
            else:
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                click.echo(stamp(f"Resolution not available. Getting closest match:"))
                return closest_match, pssh, audio

        return heights[0], pssh, audio

    def get_info(self, url: str) -> object:
        with self.console.status("Fetching titles..."):
            series = self.get_series(url)
            for episode in series:
                episode.name = episode.get_filename()

        title = string_cleaning(str(series))
        seasons = Counter(x.season for x in series)
        num_seasons = len(seasons)
        num_episodes = sum(seasons.values())

        stamp(f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n")

        return series, title

    def list_titles(self) -> str:
        series, title = self.get_info(self.url)

        for episode in series:
            stamp(episode.name)


    def get_episode(self) -> None:
        series, title = self.get_info(self.url)

        if "-" in self.episode:
            self.get_range(series, self.episode, title)
        if "," in self.episode:
            self.get_mix(series, self.episode, title)

        target = next((i for i in series if self.episode in i.name), None)

        self.download(target, title) if target else stamp(
            f"{self.episode} was not found"
        )


    def get_range(self, series: object, episodes: str, title: str) -> None:
        episode_range = set_range(episodes)

        for episode in series:
            if any(i in episode.name for i in episode_range):
                self.download(episode, title)

        shutil.rmtree(self.tmp)
        exit(0)

    def get_mix(self, series: object, episodes: str, title: str) -> None:
        episode_mix = [x for x in episodes.split(",")]

        for episode in series:
            if any(i in episode.name for i in episode_mix):
                self.download(episode, title)

        shutil.rmtree(self.tmp)
        exit(0)

    def get_season(self) -> None:
        series, title = self.get_info(self.url)

        for episode in series:
            if self.season in episode.name:
                self.download(episode, title)


    def get_complete(self) -> None:
        series, title = self.get_info(self.url)

        for episode in series:
            self.download(episode, title)


    def get_movie(self) -> None:
        with self.console.status("Fetching titles..."):
            movies = self.get_movies(self.url)
            title = string_cleaning(str(movies))

        stamp(f"{str(movies)}\n")

        for movie in movies:
            movie.name = movie.get_filename()
            self.download(movie, title)


    def download(self, stream: object, title: str) -> None:
        downloads = Path(self.config["save_dir"])
        save_path = downloads.joinpath(title)
        save_path.mkdir(parents=True, exist_ok=True)

        if stream.__class__.__name__ == "Episode" and self.config["seasons"] == "true":
            _season = f"season.{stream.season:02d}"
            save_path = save_path.joinpath(_season)
            save_path.mkdir(parents=True, exist_ok=True)

        with self.console.status("Getting media info..."):
            manifest, subtitle = self.get_playlist(stream.data, stream.id)
            resolution, pssh, audio = self.get_mediainfo(manifest, self.quality)
            if self.config["filename"] == "default":
                filename = (
                    f"{stream.name}.{resolution}p.{stream.service}.WEB-DL.AAC2.0.H.264"
                )
            else:
                filename = f"{stream.name}.{resolution}p"

            sub_path = save_path / f"{filename}.vtt"

            r = self.client.get(url=f"{subtitle}")
            if r.status_code != 200:
                stamp("No subtitle found")
                sub = None
            else:
                sub = True
                with open(sub_path, "wb") as f:
                    f.write(r.content)

        with self.console.status("Getting decryption keys..."):
            keys = (
                remote_cdm(pssh, self.lic_url, self.client)
                if self.remote
                else local_cdm(pssh, self.lic_url, self.client)
            )
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        stamp(f"{stream.name}")
        for key in keys:
            stamp(f"{key}")
        click.echo("")

        m3u8dl = shutil.which("N_m3u8DL-RE") or shutil.which("n-m3u8dl-re")

        _temp = self.config["temp_dir"]

        _video = f"res='{resolution}'" if self.quality else "for=best"
        _audio = "all" if self.all_audio else "for=best"

        _threads = self.config["threads"]
        _format = self.config["format"]
        _muxer = self.config["muxer"]
        _sub = self.config["skip_sub"]

        if self.config["filename"] == "default":
            file = f"{stream.name}.{resolution}p.{stream.service}.WEB-DL.AAC2.0.H.264"
        else:
            file = f"{stream.name}.{resolution}p"

        args = [
            m3u8dl,
            "--key-text-file",
            self.tmp / "keys.txt",
            self.tmp / "manifest.mpd",
            "-sv",
            _video,
            "-sa",
            _audio,
            "-ss",
            "all",
            "-mt",
            "-M",
            f"format={_format}:muxer={_muxer}:skip_sub={_sub}",
            "--thread-count",
            _threads,
            "--save-name",
            filename,
            "--tmp-dir",
            _temp,
            "--save-dir",
            f"{save_path}",
            "--no-log",
            # "--log-level",
            # "OFF",
        ]

        args.extend(
            [f"--mux-import", f"path={sub_path}:lang=eng:name='English'"]
        ) if sub and _sub == "false" else None

        try:
            subprocess.run(args, check=True)
        except:
            raise ValueError(
                "Download failed. Install necessary binaries before downloading"
            )
