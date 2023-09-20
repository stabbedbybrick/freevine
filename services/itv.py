"""
Thanks to A_n_g_e_l_a for the cookies!

ITV
Author: stabbedbybrick

Info:
ITV L3 is 720p, AAC 2.0 max

"""

import base64
import subprocess
import json
import shutil
import sys

from pathlib import Path
from collections import Counter

import click
import httpx
import requests

from bs4 import BeautifulSoup
from rich.console import Console

from helpers.utilities import info, error, string_cleaning, set_range, add_subtitles
from helpers.cdm import local_cdm, remote_cdm
from helpers.titles import Episode, Series, Movie, Movies


class ITV:
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
        self.client = httpx.Client(
            headers={
                "authority": "www.itv.com",
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/118.0.0.0 Safari/537.36"
                ),
            }
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

    def get_data(self, url: str) -> dict:
        soup = BeautifulSoup(self.client.get(url), "html.parser")
        props = soup.select_one("#__NEXT_DATA__").text
        data = json.loads(props)
        return data["props"]["pageProps"]

    def get_titles(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
                    id_=None,
                    service="ITV",
                    title=data["programme"]["title"],
                    season=episode.get("series") or 0,
                    number=episode.get("episode") or 0,
                    name=episode["episodeTitle"],
                    year=None,
                    data=episode["playlistUrl"],
                )
                for series in data["seriesList"]
                for episode in series["titles"]
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)

        return Movies(
            [
                Movie(
                    id_=None,
                    service="ITV",
                    title=data["programme"]["title"],
                    year=movie.get("productionYear"),
                    name=data["programme"]["title"],
                    data=movie["playlistUrl"],
                )
                for movies in data["seriesList"]
                for movie in movies["titles"]
            ]
        )

    def get_playlist(self, playlist: str) -> tuple:
        featureset = {
            k: ("mpeg-dash", "widevine", "outband-webvtt", "hd", "single-track")
            for k in ("min", "max")
        }
        payload = {
            "client": {"id": "browser"},
            "variantAvailability": {"featureset": featureset, "platformTag": "dotcom"},
        }

        r = self.client.post(playlist, json=payload)
        if not r.is_success:
            click.echo(f"\n\nError! {r.status_code}\n{r.content}")
            shutil.rmtree(self.tmp)
            sys.exit(1)

        data = r.json()

        video = data["Playlist"]["Video"]
        media = video["MediaFiles"]
        mpd_url = f"{video.get('Base')}{media[0].get('Href')}"
        lic_url = f"{media[0].get('KeyServiceUrl')}"
        subtitle = video.get("Subtitles")
        subtitle = f"{subtitle[0].get('Href')}" if subtitle else None

        return mpd_url, lic_url, subtitle

    def get_pssh(self, soup: str) -> str:
        kid = (
            soup.select_one("ContentProtection")
            .attrs.get("cenc:default_KID")
            .replace("-", "")
        )
        version = "3870737368"
        system_id = "EDEF8BA979D64ACEA3C827DCD51D21ED"
        data = "48E3DC959B06"
        s = f"000000{version}00000000{system_id}000000181210{kid}{data}"
        return base64.b64encode(bytes.fromhex(s)).decode()

    def get_mediainfo(self, manifest: str, quality: str, subtitle: str) -> str:
        r = requests.get(manifest)
        if not r.ok:
            click.echo(f"\n\nError! {r.status_code}\n{r.content}")
            sys.exit(1)

        soup = BeautifulSoup(r.content, "xml")
        pssh = self.get_pssh(soup)
        elements = soup.find_all("Representation")
        heights = sorted(
            [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
            reverse=True,
        )

        new_base, params = manifest.split(".mpd")
        new_base += "dash/"
        soup.select_one("BaseURL").string = new_base

        segments = soup.find_all("SegmentTemplate")
        for segment in segments:
            segment["media"] += params
            segment["initialization"] += params

        if subtitle is not None:
            soup = add_subtitles(soup, subtitle)

        with open(self.tmp / "manifest.mpd", "w") as f:
            f.write(str(soup.prettify()))

        if quality is not None:
            if int(quality) in heights:
                return quality, pssh
            else:
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                return closest_match, pssh

        return heights[0], pssh

    def get_info(self, url: str) -> object:
        with self.console.status("Fetching titles..."):
            series = self.get_titles(url)
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

        shutil.rmtree(self.tmp)

    def download(self, stream: object, title: str) -> None:
        downloads = Path(self.config["save_dir"])
        save_path = downloads.joinpath(title)
        save_path.mkdir(parents=True, exist_ok=True)

        if stream.__class__.__name__ == "Episode" and self.config["seasons"] == "true":
            _season = f"season.{stream.season:02d}"
            save_path = save_path.joinpath(_season)
            save_path.mkdir(parents=True, exist_ok=True)

        with self.console.status("Getting media info..."):
            manifest, lic_url, subtitle = self.get_playlist(stream.data)
            resolution, pssh = self.get_mediainfo(manifest, self.quality, subtitle)
            if self.config["filename"] == "default":
                filename = (
                    f"{stream.name}.{resolution}p.{stream.service}.WEB-DL.AAC2.0.H.264"
                )
            else:
                filename = f"{stream.name}.{resolution}p"

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

        args = [
            m3u8dl,
            "--key-text-file",
            self.tmp / "keys.txt",
            self.tmp / "manifest.mpd",
            "--append-url-params",
            "-H",
            f"client.headers",
            "-H",
            "cookie: hdntl=~data=hdntl~hmac=*",
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
            save_path,
            "--no-log",
            # "--log-level",
            # "OFF",
        ]

        file_path = Path(save_path) / f"{filename}.{_format}"

        if not file_path.exists():
            try:
                subprocess.run(args, check=True)
            except:
                raise ValueError(
                    "Download failed. Install necessary binaries before downloading"
                )
        else:
            info(f"{filename} already exist. Skipping download\n")
            pass
