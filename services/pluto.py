"""
Credit to rlaphoenix for the title storage

PlutoTV
Author: stabbedbybrick

Info:
This program will download ad-free streams with highest available quality and subtitles
Quality: 720p, AAC 2.0 max
Some titles are encrypted, some are not. Both versions are supported

Notes:
While functional, it's still considered in beta
Labeling for resolution is currently missing
Pluto's library is very spotty, so it's highly recommended to use --titles before downloading

"""

import base64
import re
import subprocess
import shutil
import uuid
import sys

from urllib.parse import urlparse
from pathlib import Path
from collections import Counter

import click
import httpx

from bs4 import BeautifulSoup
from rich.console import Console

from helpers.utilities import info, error, string_cleaning, set_range
from helpers.cdm import local_cdm, remote_cdm
from helpers.titles import Episode, Series, Movie, Movies


class PLUTO:
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

        self.lic_url = "https://service-concierge.clusters.pluto.tv/v1/wv/alt"
        self.api = "https://service-vod.clusters.pluto.tv/v4/vod"

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

    def get_data(self, url: str) -> dict:
        type = urlparse(url).path.split("/")[3]
        video_id = urlparse(url).path.split("/")[4]

        params = {
            "appName": "web",
            "appVersion": "na",
            "clientID": str(uuid.uuid1()),
            "deviceDNT": 0,
            "deviceId": "unknown",
            "clientModelNumber": "na",
            "serverSideAds": "false",
            "deviceMake": "unknown",
            "deviceModel": "web",
            "deviceType": "web",
            "deviceVersion": "unknown",
            "sid": str(uuid.uuid1()),
            "drmCapabilities": "widevine:L3",
        }

        response = self.client.get(
            "https://boot.pluto.tv/v4/start", params=params
        ).json()

        self.token = response["sessionToken"]

        info = (
            f"{self.api}/series/{video_id}/seasons"
            if type == "series"
            else f"{self.api}/items?ids={video_id}"
        )
        self.client.headers.update({"Authorization": f"Bearer {self.token}"})
        self.client.params = params

        return self.client.get(info).json()

    def get_titles(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
                    service="PLUTO",
                    title=data["name"],
                    season=int(episode.get("season")),
                    number=int(episode.get("number")),
                    name=episode.get("name"),
                    year=None,
                    data=[x["path"] for x in episode["stitched"]["paths"]],
                )
                for series in data["seasons"]
                for episode in series["episodes"]
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)

        return Movies(
            [
                Movie(
                    service="PLUTO",
                    title=movie["name"],
                    year=movie["slug"].split("-")[-3],  # TODO
                    name=movie["name"],
                    data=[x["path"] for x in movie["stitched"]["paths"]],
                )
                for movie in data
            ]
        )

    def get_dash(self, stitch: str):
        base = "https://cfd-v4-service-stitcher-dash-use1-1.prd.pluto.tv/v2"

        url = f"{base}{stitch}"
        soup = BeautifulSoup(self.client.get(url), "xml")
        base_urls = soup.find_all("BaseURL")
        for base_url in base_urls:
            if base_url.text.endswith("end/"):
                new_base = base_url.text

        parse = urlparse(new_base)
        _path = parse.path.split("/")
        _path = "/".join(_path[:-3])
        new_path = f"{_path}/dash/0-end/main.mpd"

        return parse._replace(
            scheme="http",
            netloc="silo-hybrik.pluto.tv.s3.amazonaws.com",
            path=f"{new_path}",
        ).geturl()

    def get_hls(self, stitch: str):
        base = "https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv"

        url = f"{base}{stitch}"
        response = self.client.get(url).text
        pattern = r"#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=(\d+)"
        matches = re.findall(pattern, response)

        max_bandwidth = sorted(matches, key=int, reverse=True)
        url = url.replace("master.m3u8", f"{max_bandwidth[0]}/playlist.m3u8")

        response = self.client.get(url).text
        segment = re.search(
            r"^(https?://.*/)0\-(end|[0-9]+)/[^/]+\.ts$", response, re.MULTILINE
        ).group(1)

        parse = urlparse(f"{segment}0-end/master.m3u8")

        master = parse._replace(
            scheme="http",
            netloc="silo-hybrik.pluto.tv.s3.amazonaws.com",
        ).geturl()

        self.client.headers.pop("Authorization")
        response = self.client.get(master).text

        matches = re.findall(r"hls_(\d+).m3u8", response)
        hls = sorted(matches, key=int, reverse=True)[0]

        manifest = master.replace("master.m3u8", f"hls_{hls}.m3u8")
        return manifest

    def get_playlist(self, playlists: str) -> tuple:
        stitched = next((x for x in playlists if x.endswith(".mpd")), None)
        if not stitched:
            stitched = next((x for x in playlists if x.endswith(".m3u8")), None)

        if stitched.endswith(".mpd"):
            return self.get_dash(stitched)

        if stitched.endswith(".m3u8"):
            return self.get_hls(stitched)

    def generate_pssh(self, kid: str):
        array_of_bytes = bytearray(b"\x00\x00\x002pssh\x00\x00\x00\x00")
        array_of_bytes.extend(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
        array_of_bytes.extend(b"\x00\x00\x00\x12\x12\x10")
        array_of_bytes.extend(bytes.fromhex(kid.replace("-", "")))
        return base64.b64encode(bytes.fromhex(array_of_bytes.hex())).decode("utf-8")

    def get_pssh(self, manifest: str) -> str:
        self.client.headers.pop("Authorization")
        soup = BeautifulSoup(self.client.get(manifest), "xml")
        tags = soup.find_all("ContentProtection")
        kids = set(
            [
                x.attrs.get("cenc:default_KID").replace("-", "")
                for x in tags
                if x.attrs.get("cenc:default_KID")
            ]
        )

        return [self.generate_pssh(kid) for kid in kids]

    def get_mediainfo(self, manifest: str) -> str:
        return self.get_pssh(manifest) if manifest.endswith(".mpd") else None

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

        shutil.rmtree("tmp")
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
            manifest = self.get_playlist(stream.data)
            pssh = self.get_mediainfo(manifest)
            self.client.headers.update({"Authorization": f"Bearer {self.token}"})

        if pssh is not None:
            with self.console.status("Getting decryption keys..."):
                keys = [
                    remote_cdm(key, self.lic_url, self.client)
                    if self.remote
                    else local_cdm(key, self.lic_url, self.client)
                    for key in pssh
                ]
                with open(self.tmp / "keys.txt", "w") as file:
                    file.write("\n".join(key[0] for key in keys))

        info(f"{stream.name}")
        click.echo("")

        m3u8dl = shutil.which("N_m3u8DL-RE") or shutil.which("n-m3u8dl-re")

        _temp = self.config["temp_dir"]

        # _video = f"res='{resolution}'" if self.quality else "for=best"
        _audio = "all" if self.all_audio else "for=best"

        _threads = self.config["threads"]
        _format = self.config["format"]
        _muxer = self.config["muxer"]
        _sub = self.config["skip_sub"]

        if self.config["filename"] == "default":
            filename = f"{stream.name}.{stream.service}.WEB-DL.AAC2.0.H.264"
        else:
            filename = f"{stream.name}"

        args = [
            m3u8dl,
            f"{manifest}",
            "--append-url-params",
            "-sv",
            "for=best",
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
        ) if pssh is not None else None

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
