"""
Thanks to yt-dlp devs for the authentication flow

CBC
Author: stabbedbybrick

Quality: up to 1080p and DDP5.1 audio

"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import click
import yaml
from bs4 import BeautifulSoup

from utils.args import get_args
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    force_numbering,
    in_cache,
    is_url,
    set_filename,
    set_save_path,
    string_cleaning,
    update_cache,
)



class CBC(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        if is_url(self.episode):
            self.log.error("Episode URL not supported. Use standard method")
            return

        if self.sub_only:
            self.log.info("Subtitle downloads are not supported on this service")
            return

        with self.config["download_cache"].open("r") as file:
            self.cache = json.load(file)

        self.username = self.config.get("credentials", {}).get("username")
        self.password = self.config.get("credentials", {}).get("password")

        self.get_options()

    def login(self) -> str:
        if not self.username and not self.password:
            self.log.error(
                "Required credentials were not found. See 'freevine.py profile --help'"
            )
            sys.exit(1)

        payload = {
            "email": self.username,
            "password": self.password,
        }
        params = {"apikey": self.config["apikey"]}
        r = self.client.post(
            "https://api.loginradius.com/identity/v2/auth/login",
            json=payload,
            params=params,
        )
        if not r.ok:
            raise ConnectionError(f"{r.json().get('Description')}")

        auth = json.loads(r.content)
        access_token = auth.get("access_token")
        refresh_token = auth.get("refresh_token")
        expiry = datetime.strptime(auth.get("expires_in"), "%Y-%m-%dT%H:%M:%S.%fZ")

        profile = Path("services") / "cbc" / "profile.yaml"
        with open(profile, "r") as f:
            data = yaml.safe_load(f)

        data["cache"] = {}

        data["cache"]["login"] = {
            "token": access_token,
            "expiry": expiry,
            "refresh": refresh_token,
        }

        with open(profile, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)

        self.log.info("+ New login tokens placed in cache")
        return access_token

    def access_token(self, token: str) -> str:
        params = {
            "access_token": token,
            "apikey": self.config["apikey"],
            "jwtapp": "jwt",
        }
        headers = {"content-type": "application/json"}
        resp = self.client.get(
            "https://cloud-api.loginradius.com/sso/jwt/api/token",
            headers=headers,
            params=params,
        ).json()

        sig = resp["signature"]

        payload = {"jwt": sig}
        headers = {"content-type": "application/json", "ott-device-type": "web"}
        auth = self.client.post(
            "https://services.radio-canada.ca/ott/cbc-api/v2/token",
            headers=headers,
            json=payload,
        ).json()

        access_token = auth.get("accessToken")
        refresh_token = auth.get("refreshToken")

        expiry = datetime.now() + timedelta(seconds=auth.get("accessTokenExpiresIn"))

        profile = Path("services") / "cbc" / "profile.yaml"
        with open(profile, "r") as f:
            data = yaml.safe_load(f)

        data["cache"]["access"] = {
            "token": access_token,
            "expiry": expiry,
            "refresh": refresh_token,
        }

        with open(profile, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)

        self.log.info("+ New access tokens placed in cache")
        return access_token

    def claims_token(self, token: str) -> str:
        headers = {
            "content-type": "application/json",
            "ott-device-type": "web",
            "ott-access-token": token,
        }
        resp = self.client.get(
            "https://services.radio-canada.ca/ott/cbc-api/v2/profile",
            headers=headers,
        ).json()

        return resp["claimsToken"]

    def refresh_auth_token(self, token: str) -> str:
        payload = {
            "email": self.username,
            "password": self.password,
            "refresh_token": token,
        }
        params = {"apikey": self.config["apikey"]}
        auth = self.client.post(
            "https://api.loginradius.com/identity/v2/auth/login",
            json=payload,
            params=params,
        )

        access_token = auth.get("access_token")
        refresh_token = auth.get("refresh_token")
        expiry = datetime.strptime(auth.get("expires_in"), "%Y-%m-%dT%H:%M:%S.%fZ")

        profile = Path("services") / "cbc" / "profile.yaml"
        with open(profile, "r") as f:
            data = yaml.safe_load(f)

        data["cache"]["login"]["token"] = access_token
        data["cache"]["login"]["refresh"] = refresh_token
        data["cache"]["login"]["expiry"] = expiry

        with open(profile, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)

        self.log.info("+ Tokens refreshed")
        return access_token

    def authenticate(self):
        cache = self.config.get("cache")

        if not cache:
            self.log.info("Cache is empty, aquiring new login tokens...")
            auth_token = self.login()
            access_token = self.access_token(auth_token)

        elif cache and cache["login"]["expiry"] < datetime.now():
            self.log.info("Refreshing expired login tokens...")
            auth_token = self.refresh_auth_token(cache["login"]["refresh"])

        else:
            self.log.info("Using cached login tokens")
            auth_token = cache["login"].get("token")

        if not cache and access_token:
            access_token = access_token

        elif cache and cache["access"]["expiry"] < datetime.now():
            access_token = self.access_token(auth_token)

        else:
            access_token = cache["access"]["token"]

        return access_token

    def get_data(self, url: str):
        show_id = urlparse(url).path.split("/")[1]

        access_token = self.authenticate()
        claims_token = self.claims_token(access_token)
        self.client.headers.update({"x-claims-token": claims_token})
        url = self.config["shows"].format(show=show_id)

        return self.client.get(url).json()

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)

        seasons = [season for season in data["seasons"]]
        episodes = [
            episode
            for season in seasons
            for episode in season["assets"]
            if not episode["isTrailer"]
        ]

        return Series(
            [
                Episode(
                    id_=episode["id"],
                    service="CBC",
                    title=data["title"],
                    season=int(episode["season"]),
                    number=int(episode["episode"]),
                    name=episode["title"],
                    data=episode["playSession"]["url"],
                    description=episode.get("description"),
                )
                for episode in episodes
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)

        seasons = [season for season in data["seasons"]]
        episodes = [
            episode
            for season in seasons
            for episode in season["assets"]
            if not episode["isTrailer"]
        ]

        return Movies(
            [
                Movie(
                    id_=episode["id"],
                    service="CBC",
                    title=data["title"],
                    name=data["title"],
                    data=episode["playSession"]["url"],
                    synopsis=episode.get("description"),
                )
                for episode in episodes
            ]
        )

    def get_mediainfo(self, quality: int, m3u8: str) -> str:
        resolutions = []

        lines = m3u8.splitlines()

        for line in lines:
            if "RESOLUTION=" in line:
                resolution = re.search("RESOLUTION=\d+x(\d+)", line).group(1)
                resolutions.append(resolution)

        resolutions.sort(key=lambda x: int(x), reverse=True)

        for line in lines:
            if "ec3" in line and "best" in self.config["audio"]["select"]:
                audio = "DDP5.1"
            elif "ec3" in line and "ec3" in self.config["audio"]["select"]:
                audio = "DDP5.1"
            else:
                audio = "AAC2.0"

        if quality is not None:
            if quality in resolutions:
                return quality, audio
            else:
                closest_match = min(
                    resolutions, key=lambda x: abs(int(x) - int(quality))
                )
                return closest_match, audio

        return resolutions[0], audio

    def get_hls(self, url: str):
        base_url = url.split("desktop")[0]
        smooth = f"{base_url}QualityLevels(5999999)/Manifest(video,type=keyframes)"

        video_stream = (
            "#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},"
            "RESOLUTION={width}x{height},"
            'CODECS="avc1.{codec}",'
            'AUDIO="audio",'
            'CLOSED-CAPTIONS="CC"\n{uri}QualityLevels({bitrate})/Manifest(video,format=m3u8-aapl)'
        )
        audio_stream = (
            "#EXT-X-MEDIA:TYPE=AUDIO,"
            'GROUP-ID="{id}",'
            "BANDWIDTH={bandwidth},"
            'NAME="{name}",'
            'LANGUAGE="{language}",'
            'URI="{uri}QualityLevels({bitrate})/Manifest({codec},format=m3u8-aapl)"'
        )

        m3u8_text = self.client.get(url).text

        try:
            r = self.client.get(smooth)
            r.raise_for_status()
            self.xml = BeautifulSoup(r.content, "xml")
        except ValueError:
            self.xml = None

        if self.xml:
            m3u8_text = re.sub(r"QualityLevels", f"{base_url}QualityLevels", m3u8_text)

            indexes = self.xml.find_all("StreamIndex")
            for index in indexes:
                if index.attrs.get("Type") == "video":
                    for level in index:
                        if not level.attrs.get("Bitrate"):
                            continue

                        if level.attrs.get("MaxHeight") == "1080":
                            m3u8_text += (
                                video_stream.format(
                                    bandwidth=level.attrs.get("Bitrate", 0),
                                    width=level.attrs.get("MaxWidth", 0),
                                    height=level.attrs.get("MaxHeight", 0),
                                    codec=re.search(
                                        "0000000127(\w{6})",
                                        level.attrs.get("CodecPrivateData"),
                                    )
                                    .group(1)
                                    .lower(),
                                    uri=base_url,
                                    bitrate=level.attrs.get("Bitrate", 0),
                                )
                                + "\n"
                            )

                if index.attrs.get("Type") == "audio":
                    levels = index.find_all("QualityLevel")
                    for level in levels:
                        m3u8_text += (
                            audio_stream.format(
                                id=index.attrs.get("Name"),
                                bandwidth=level.attrs.get("Bitrate", 0),
                                name=level.attrs.get("FourCC"),
                                language=index.attrs.get("Language"),
                                uri=base_url,
                                bitrate=level.attrs.get("Bitrate", 0),
                                codec=index.attrs.get("Name"),
                            )
                            + "\n"
                        )

            with open(self.tmp / "manifest.m3u8", "w") as f:
                f.write(m3u8_text)

        return url, m3u8_text

    def get_playlist(self, playsession: str) -> tuple:
        response = self.client.get(playsession).json()

        if response.get("errorCode"):
            raise ConnectionError(response)

        return self.get_hls(response.get("url"))

    def get_content(self, url: str) -> object:
        if self.movie:
            content = self.get_movies(self.url)
            title = string_cleaning(str(content))

            self.log.info(f"{str(content)}\n")

        else:
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

    def get_options(self) -> None:
        downloads, title = get_downloads(self)

        for download in downloads:
            if in_cache(self.cache, download):
                continue

            if self.slowdown:
                with self.console.status(
                    f"Slowing things down for {self.slowdown} seconds..."
                ):
                    time.sleep(self.slowdown)

            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        mpd_url, m3u8 = self.get_playlist(stream.data)
        self.res, audio = self.get_mediainfo(self.quality, m3u8)

        self.filename = set_filename(self, stream, self.res, audio)
        self.save_path = set_save_path(stream, self, title)
        self.manifest = self.tmp / "manifest.m3u8" if self.xml else mpd_url
        self.key_file = None  # Not encrypted
        self.sub_path = None

        self.log.info(f"{str(stream)}")
        click.echo("")

        args, file_path = get_args(self)

        try:
            subprocess.run(args, check=True)
        except Exception as e:
            self.sub_path.unlink() if self.sub_path else None
            raise ValueError(f"{e}")
        
        if not self.skip_download and file_path.exists():
            update_cache(self.cache, self.config, stream)
