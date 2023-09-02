"""
Credit to rlaphoenix for the title storage

ROKU
Author: stabbedbybrick

Info:
This program will grab higher 1080p bitrate and Dolby 5.1 audio (if available)

"""

import subprocess
import urllib
import json
import asyncio
import shutil

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

TMP = Path("tmp")
TMP.mkdir(parents=True, exist_ok=True)


class ROKU:
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

        self.console = Console()
        self.api = (
            f"https://therokuchannel.roku.com/api/v2/homescreen/content/"
            f"https%3A%2F%2Fcontent.sr.roku.com%2Fcontent%2Fv1%2Froku-trc%2F"
        )
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

    def get_data(self, url: str) -> json:
        video_id = urlparse(url).path.split("/")[2]

        try:
            return self.client.get(f"{self.api}{video_id}").json()
        except:
            raise KeyError(
                "Request failed. IP-address is either blocked or content is paywalled"
            )

    async def fetch_titles(self, async_client: httpx.AsyncClient, id: str) -> json:
        response = await async_client.get(f"{self.api}{id}")
        return response.json()

    async def get_titles(self, data: dict) -> list:
        async with httpx.AsyncClient() as async_client:
            tasks = [
                self.fetch_titles(async_client, x["meta"]["id"])
                for x in data["episodes"]
            ]

            return await asyncio.gather(*tasks)

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)
        episodes = asyncio.run(self.get_titles(data))

        return Series(
            [
                Episode(
                    id_=None,
                    service="ROKU",
                    title=data["title"],
                    season=int(episode["seasonNumber"]),
                    number=int(episode["episodeNumber"]),
                    name=episode["title"],
                    year=data["releaseYear"],
                    data=episode["meta"]["id"],
                )
                for episode in episodes
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)

        return Movies(
            [
                Movie(
                    id_=None,
                    service="ROKU",
                    title=data["title"],
                    year=data["releaseYear"],
                    name=data["title"],
                    data=data["meta"]["id"],
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

        url = f"https://therokuchannel.roku.com/api/v3/playback"

        response = self.client.post(
            url, headers=headers, cookies=self.client.cookies, json=payload
        ).json()

        try:
            videos = response["playbackMedia"]["videos"]
        except:
            raise KeyError(
                "Request failed. IP-address is either blocked or content is paywalled"
            )

        lic_url = [
            x["drmParams"]["licenseServerURL"]
            for x in videos
            if x["drmParams"]["keySystem"] == "Widevine"
        ][0]

        mpd = [x["url"] for x in videos if x["streamFormat"] == "dash"][0]
        manifest = urllib.parse.unquote(mpd).split("=")[1].split("?")[0]

        return lic_url, manifest

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        soup = BeautifulSoup(self.client.get(manifest), "xml")
        elements = soup.find_all("Representation")
        codecs = [x.attrs["codecs"] for x in elements if x.attrs.get("codecs")]
        heights = sorted(
            [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
            reverse=True,
        )

        audio = "DD5.1" if "ac-3" in codecs else "AAC2.0"

        if quality is not None:
            if quality in heights:
                return quality, audio
            else:
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                stamp(f"Resolution not available. Getting closest match:")
                return closest_match, audio

        return heights[0], audio

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

        shutil.rmtree(self.tmp)

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

        shutil.rmtree(self.tmp)

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

        shutil.rmtree(self.tmp)

    def get_complete(self) -> None:
        series, title = self.get_info(self.url)

        for episode in series:
            self.download(episode, title)

        shutil.rmtree(self.tmp)

    def get_movie(self) -> None:
        with self.console.status("Fetching titles..."):
            movies = self.get_movies(self.url)
            title = string_cleaning(str(movies))

        stamp(f"{str(movies)}\n")

        for movie in movies:
            movie.name = movie.get_filename()
            self.download(movie, title)

        shutil.rmtree(self.tmp)

    def download(self, stream: object, title: str) -> None:
        pssh = "AAAAKXBzc2gAAAAA7e+LqXnWSs6jyCfc1R0h7QAAAAkiASpI49yVmwY="

        downloads = Path(self.config["save_dir"])
        save_path = downloads.joinpath(title)
        save_path.mkdir(parents=True, exist_ok=True)

        if stream.__class__.__name__ == "Episode" and self.config["seasons"] == "true":
            _season = f"season.{stream.season:02d}"
            save_path = save_path.joinpath(_season)
            save_path.mkdir(parents=True, exist_ok=True)

        with self.console.status("Getting media info..."):
            lic_url, manifest = self.get_playlist(stream.data)
            resolution, audio = self.get_mediainfo(manifest, self.quality)

        with self.console.status("Getting decryption keys..."):
            keys = (
                remote_cdm(pssh, lic_url, self.client)
                if self.remote
                else local_cdm(pssh, lic_url, self.client)
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
            file = f"{stream.name}.{resolution}p.{stream.service}.WEB-DL.{audio}.H.264"
        else:
            file = f"{stream.name}.{resolution}p"

        args = [
            m3u8dl,
            "--key-text-file",
            self.tmp / "keys.txt",
            manifest,
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
            file,
            "--tmp-dir",
            _temp,
            "--save-dir",
            f"{save_path}",
            "--no-log",
            # "--log-level",
            # "OFF",
        ]

        try:
            subprocess.run(args, check=True)
        except:
            raise ValueError(
                "Download failed. Install necessary binaries before downloading"
            )
