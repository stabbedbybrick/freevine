"""
Credit to Diazole and rlaphoenix for paving the way

Author: stabbedbybrick

Info:
This program will grab higher 1080p bitrate (if available)
Place blob and key file in pywidevine/L3/cdm/devices/android_generic

"""

import base64
import re
import subprocess
import json
import shutil
import sys

from pathlib import Path
from collections import Counter

import click
import httpx

from bs4 import BeautifulSoup
from rich.console import Console
from Crypto.Cipher import AES

from helpers.utilities import info, string_cleaning, set_range
from helpers.titles import Episode, Series, Movie, Movies

from pywidevine.L3.decrypt.wvdecryptcustom import WvDecrypt
from pywidevine.L3.cdm import deviceconfig


class CHANNEL4:
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

        self.episode = self.episode.upper() if self.episode else None
        self.season = self.season.upper() if self.season else None
        self.quality = self.quality.rstrip("p") if self.quality else None

        self.tmp.mkdir(parents=True, exist_ok=True)

        self.list_titles() if self.titles else None
        self.get_episode() if self.episode else None
        self.get_season() if self.season else None
        self.get_complete() if self.complete else None
        self.get_movie() if self.movie else None

    def local_cdm(
        self,
        pssh: str,
        lic_url: str,
        manifest: str,
        token: str,
        asset: str,
        cert_b64=None,
    ) -> str:
        wvdecrypt = WvDecrypt(
            init_data_b64=pssh,
            cert_data_b64=cert_b64,
            device=deviceconfig.device_android_generic,
        )
        lic = self.get_license(
            wvdecrypt.get_challenge(), lic_url, manifest, token, asset
        )

        wvdecrypt.update_license(lic)
        status, content = wvdecrypt.start_process()

        if status:
            return content
        else:
            raise ValueError("Unable to fetch decryption keys")

    def get_license(
        self,
        challenge: bytes,
        lic_url: str,
        manifest: str,
        token: str,
        asset: str,
    ) -> str:
        r = self.client.post(
            lic_url,
            data=json.dumps(
                {
                    "message": base64.b64encode(challenge).decode("utf8"),
                    "token": token,
                    "request_id": asset,
                    "video": {"type": "ondemand", "url": manifest},
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        if r.status_code != 200:
            click.echo(f"Failed to get license! Error: {r.json()['status']['type']}")
            sys.exit(1)
        return r.json()["license"]

    def decrypt_token(self, token: str) -> tuple:
        key = "QVlESUQ4U0RGQlA0TThESA=="
        iv = "MURDRDAzODNES0RGU0w4Mg=="

        if isinstance(token, str):
            token = base64.b64decode(token)
            cipher = AES.new(
                key=base64.b64decode(key),
                iv=base64.b64decode(iv),
                mode=AES.MODE_CBC,
            )
            data = cipher.decrypt(token)[:-2]
            license_api, dec_token = data.decode().split("|")
            return dec_token.strip(), license_api.strip()

    def get_data(self, url: str) -> dict:
        r = self.client.get(url)
        init_data = re.search(
            "<script>window\.__PARAMS__ = (.*)</script>",
            "".join(
                r.content.decode()
                .replace("\u200c", "")
                .replace("\r\n", "")
                .replace("undefined", "null")
            ),
        )
        data = json.loads(init_data.group(1))
        return data["initialData"]

    def get_titles(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
                    id_=None,
                    service="ALL4",
                    title=data["brand"]["title"],
                    season=episode["seriesNumber"],
                    number=episode["episodeNumber"],
                    name=episode["originalTitle"],
                    year=None,
                    data=episode.get("assetId"),
                )
                for episode in data["brand"]["episodes"]
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)

        return Movies(
            [
                Movie(
                    id_=None,
                    service="ALL4",
                    title=data["brand"]["title"],
                    year=data["brand"]["summary"].split(" ")[0].strip().strip("()"),
                    name=data["brand"]["title"],
                    data=movie.get("assetId"),
                )
                for movie in data["brand"]["episodes"]
            ]
        )

    def get_playlist(self, asset_id: str) -> tuple:
        url = f"https://ais.channel4.com/asset/{asset_id}?client=android-mod"
        r = self.client.get(url)
        if not r.is_success:
            shutil.rmtree(self.tmp)
            raise ValueError("Invalid assetID")
        soup = BeautifulSoup(r.text, "xml")
        token = soup.select_one("token").text
        manifest = soup.select_one("uri").text
        return manifest, token

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
            manifest, token = self.get_playlist(stream.data)
            resolution, pssh = self.get_mediainfo(manifest, self.quality)
            token, license_url = self.decrypt_token(token)

        with self.console.status("Getting decryption keys..."):
            keys = self.local_cdm(pssh, license_url, manifest, token, stream.data)
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        info(f"{stream.name}")
        info(f"{keys[0]}")
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
            filename = (
                f"{stream.name}.{resolution}p.{stream.service}.WEB-DL.AAC2.0.H.264"
            )
        else:
            filename = f"{stream.name}.{resolution}p"

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
