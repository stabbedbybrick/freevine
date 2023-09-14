"""
Credit to rlaphoenix for the title storage

CRACKLE
Author: stabbedbybrick

Info:

"""

import subprocess
import json
import shutil
import sys
import base64

from urllib.parse import urlparse
from pathlib import Path
from collections import Counter

import click
import httpx

from bs4 import BeautifulSoup
from rich.console import Console

from helpers.utilities import info, string_cleaning, set_range
from helpers.cdm import local_cdm, remote_cdm
from helpers.titles import Episode, Series, Movie, Movies


class CRACKLE:
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
        self.api = "https://prod-api.crackle.com"
        self.client = httpx.Client(
            headers={
                "user-agent": "Chrome/113.0.0.0 Safari/537.36",
                "x-crackle-platform": "5FE67CCA-069A-42C6-A20F-4B47A8054D46",
            },
            follow_redirects=True,
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
        self.video_id = urlparse(url).path.split("/")[2]

        r = self.client.get(f"{self.api}/content/{self.video_id}")
        if not r.is_success:
            print(f"\nError! {r.status_code}\n{r.json()['error']['message']}")
            shutil.rmtree(self.tmp)
            sys.exit(1)

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

    def get_pssh(self, soup: str) -> str:
        kid = (
            soup.select_one("ContentProtection")
            .attrs.get("cenc:default_KID")
            .replace("-", "")
        )
        array_of_bytes = bytearray(b"\x00\x00\x002pssh\x00\x00\x00\x00")
        array_of_bytes.extend(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
        array_of_bytes.extend(b"\x00\x00\x00\x12\x12\x10")
        array_of_bytes.extend(bytes.fromhex(kid.replace("-", "")))
        return base64.b64encode(bytes.fromhex(array_of_bytes.hex())).decode("utf-8")

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        soup = BeautifulSoup(self.client.get(manifest), "xml")
        new_manifest = soup.select_one("BaseURL").text + "index.mpd"
        soup = BeautifulSoup(self.client.get(new_manifest), "xml")
        pssh = self.get_pssh(soup)
        elements = soup.find_all("Representation")
        heights = sorted(
            [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
            reverse=True,
        )

        if quality is not None:
            if int(quality) in heights:
                return quality, pssh
            else:
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                info(f"Resolution not available. Getting closest match:")
                return closest_match, pssh

        return heights[0], pssh

    def get_info(self, url: str) -> object:
        with self.console.status("Fetching titles..."):
            series = self.get_series(url)
            for episode in series:
                episode.name = episode.get_filename()

        title = string_cleaning(str(series))
        seasons = Counter(x.season for x in series)
        num_seasons = len(seasons)
        num_episodes = sum(seasons.values())

        info(f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n")

        return series, title

    def list_titles(self) -> str:
        series, title = self.get_info(self.url)

        for episode in series:
            info(episode.name)

    def get_episode(self) -> None:
        series, title = self.get_info(self.url)

        if "-" in self.episode:
            self.get_range(series, self.episode, title)
        if "," in self.episode:
            self.get_mix(series, self.episode, title)

        target = next((i for i in series if self.episode in i.name), None)

        self.download(target, title) if target else info(
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

        info(f"{str(movies)}\n")

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
            lic_url, manifest = self.get_playlist(stream.data)
            resolution, pssh = self.get_mediainfo(manifest, self.quality)

        with self.console.status("Getting decryption keys..."):
            keys = (
                remote_cdm(pssh, lic_url, self.client)
                if self.remote
                else local_cdm(pssh, lic_url, self.client)
            )
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        info(f"{stream.name}")
        for key in keys:
            info(f"{key}")
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
