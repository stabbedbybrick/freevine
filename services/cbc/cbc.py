"""
Thanks to yt-dlp devs for the authentication flow

CBC
Author: stabbedbybrick

Quality: up to 1080p and DDP5.1 audio

"""
from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from urllib.parse import urlparse

import click
from bs4 import BeautifulSoup

from utils.args import get_args
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    is_url,
    set_filename,
    set_save_path,
    string_cleaning,
    force_numbering,
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

        self.get_options()

    def get_claims_token(self):
        payload = {
            "email": self.config["email"],
            "password": self.config["password"],
        }
        headers = {"content-type": "application/json"}
        params = {"apikey": self.config["apikey"]}
        resp = self.client.post(
            "https://api.loginradius.com/identity/v2/auth/login",
            json=payload,
            params=params,
        ).json()

        access_token = resp["access_token"]

        params = {
            "access_token": access_token,
            "apikey": self.config["apikey"],
            "jwtapp": "jwt",
        }
        resp = self.client.get(
            "https://cloud-api.loginradius.com/sso/jwt/api/token",
            headers=headers,
            params=params,
        ).json()

        sig = resp["signature"]

        payload = {"jwt": sig}
        headers = {"content-type": "application/json", "ott-device-type": "web"}
        resp = self.client.post(
            "https://services.radio-canada.ca/ott/cbc-api/v2/token",
            headers=headers,
            json=payload,
        ).json()

        cbc_access_token = resp["accessToken"]

        headers = {
            "content-type": "application/json",
            "ott-device-type": "web",
            "ott-access-token": cbc_access_token,
        }
        resp = self.client.get(
            "https://services.radio-canada.ca/ott/cbc-api/v2/profile",
            headers=headers,
        ).json()

        return resp["claimsToken"]

    def get_data(self, url: str):
        show_id = urlparse(url).path.split("/")[1]

        claims_token = self.get_claims_token()
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

    def get_options(self) -> None:
        downloads, title = get_downloads(self)

        for download in downloads:
            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        with self.console.status("Getting media info..."):
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

        if not file_path.exists():
            try:
                subprocess.run(args, check=True)
            except Exception as e:
                raise ValueError(f"{e}")
        else:
            self.log.info(f"{self.filename} already exist. Skipping download\n")
            self.sub_path.unlink() if self.sub_path else None
            pass
