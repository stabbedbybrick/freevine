"""
Credit to rlaphoenix for the title storage

TubiTV
Author: stabbedbybrick

Info:
TubiTV WEB is 720p max
Some titles are encrypted, some are not. Both versions are supported


"""

import base64
import re
import subprocess
import json
import shutil
import sys

from urllib.parse import urlparse
from pathlib import Path
from collections import Counter

import click
import httpx

from rich.console import Console

from helpers.utilities import info, string_cleaning, set_range
from helpers.cdm import local_cdm, remote_cdm
from helpers.titles import Episode, Series, Movie, Movies


class TUBITV:
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
        type = urlparse(url).path.split("/")[1]
        video_id = urlparse(url).path.split("/")[2]

        content_id = f"0{video_id}" if type == "series" else video_id

        content = (
            f"https://tubitv.com/oz/videos/{content_id}/content?"
            f"video_resources=hlsv6_widevine_nonclearlead&video_resources=hlsv6"
        )

        r = self.client.get(f"{content}")
        if not r.is_success:
            print(f"\nError! {r.status_code}")
            shutil.rmtree(self.tmp)
            sys.exit(1)

        return r.json()

    def get_titles(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
                    service="TUBi",
                    title=data["title"],
                    season=int(season["id"]),
                    number=int(episode["episode_number"]),
                    name=episode["title"].split("-")[1],
                    year=data["year"],
                    data=episode["video_resources"][0]["manifest"]["url"],
                    subtitle=episode["subtitles"][0].get("url"),
                    lic_url=episode["video_resources"][0]["license_server"]["url"]
                    if episode["video_resources"][0].get("license_server")
                    else None,
                )
                for season in data["children"]
                for episode in season["children"]
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)

        return Movies(
            [
                Movie(
                    service="TUBi",
                    title=data["title"],
                    year=data["year"],
                    name=data["title"],
                    data=data["video_resources"][0]["manifest"]["url"],
                    subtitle=data["subtitles"][0].get("url"),
                    lic_url=data["video_resources"][0]["license_server"]["url"]
                    if data["video_resources"][0].get("license_server")
                    else None,
                )
            ]
        )

    def get_pssh(self, mpd: str) -> str:
        r = self.client.get(mpd)
        url = re.search('#EXT-X-MAP:URI="(.*?)"', r.text).group(1)

        headers = {"Range": "bytes=0-9999"}

        response = self.client.get(url, headers=headers)
        with open(self.tmp / "init.mp4", "wb") as f:
            f.write(response.read())

        raw = Path(self.tmp / "init.mp4").read_bytes()
        wv = raw.rfind(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
        if wv == -1:
            return None
        return base64.b64encode(raw[wv - 12 : wv - 12 + raw[wv - 9]]).decode("utf-8")

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        m3u8 = self.client.get(manifest).text
        url = urlparse(manifest)
        base = f"https://{url.netloc}/{url.path.split('/')[1]}"

        lines = m3u8.split("\n")
        playlist = [
            (re.search("RESOLUTION=([0-9x]+)", line).group(1), lines[i + 1])
            for i, line in enumerate(lines)
            if line.startswith("#EXT-X-STREAM-INF:")
            and re.search("RESOLUTION=([0-9x]+)", line)
        ]

        playlist.sort(key=lambda x: int(x[0].split("x")[1]), reverse=True)

        if quality is not None:
            for resolution, m3u8_link in playlist:
                if quality in resolution:
                    mpd = f"{base}/{m3u8_link}"
                    return mpd, quality

        mpd = f"{base}/{playlist[0][1]}"

        return mpd, playlist[0][0].split("x")[1]

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

    def download(self, stream: object, title: str) -> None:
        downloads = Path(self.config["save_dir"])
        save_path = downloads.joinpath(title)
        save_path.mkdir(parents=True, exist_ok=True)

        if stream.__class__.__name__ == "Episode" and self.config["seasons"] == "true":
            _season = f"season.{stream.season:02d}"
            save_path = save_path.joinpath(_season)
            save_path.mkdir(parents=True, exist_ok=True)

        with self.console.status("Getting media info..."):
            manifest, resolution = self.get_mediainfo(stream.data, self.quality)
            if self.config["filename"] == "default":
                filename = (
                    f"{stream.name}.{resolution}p.{stream.service}.WEB-DL.AAC2.0.H.264"
                )
            else:
                filename = f"{stream.name}.{resolution}p"

            sub_path = save_path / f"{filename}.srt"

            if stream.subtitle is not None:
                r = self.client.get(url=f"{stream.subtitle}")
                with open(sub_path, "wb") as f:
                    f.write(r.content)

        if stream.lic_url:
            with self.console.status("Getting decryption keys..."):
                pssh = self.get_pssh(manifest)
                keys = (
                    remote_cdm(pssh, stream.lic_url, self.client)
                    if self.remote
                    else local_cdm(pssh, stream.lic_url, self.client)
                )
                with open(self.tmp / "keys.txt", "w") as file:
                    file.write("\n".join(keys))

        info(f"{stream.name}")
        info(f"{keys[0]}") if stream.lic_url else None
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
            f"{stream.data}",
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
            ["--key-text-file", self.tmp / "keys.txt"]
        ) if stream.lic_url else None
        args.extend(
            [f"--mux-import", f"path={sub_path}:lang=eng:name='English'"]
        ) if stream.subtitle and _sub == "false" else None

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
            sub_path.unlink() if sub_path.exists() else None
            pass
