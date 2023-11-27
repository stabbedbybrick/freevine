"""
Thanks to yt-dlp devs for the authentication flow

CBC
Author: stabbedbybrick

Quality: up to 1080p and DDP5.1 audio

"""
from __future__ import annotations

import subprocess
import re

from urllib.parse import urlparse
from collections import Counter

import click
import yaml
import m3u8

from bs4 import BeautifulSoup

from utils.utilities import (
    info,
    error,
    is_url,
    string_cleaning,
    set_save_path,
    set_filename,
    geo_error,
    premium_error,
)
from utils.titles import Episode, Series, Movie, Movies
from utils.options import Options
from utils.args import get_args
from utils.info import print_info
from utils.config import Config


class CBC(Config):
    def __init__(self, config, srvc_api, srvc_config, **kwargs):
        super().__init__(config, srvc_api, srvc_config, **kwargs)

        if self.sub_only:
            info("Subtitle downloads are not supported on this service")
            exit(1)

        with open(self.srvc_api, "r") as f:
            self.config.update(yaml.safe_load(f))

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
            'CODECS="avc1.4d401f,mp4a.40.2",'
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
            self.xml = BeautifulSoup(self.client.get(smooth), "xml")
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

                        m3u8_text += (
                            video_stream.format(
                                bandwidth=level.attrs.get("Bitrate", 0),
                                width=level.attrs.get("MaxWidth", 0),
                                height=level.attrs.get("MaxHeight", 0),
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

        self.hls = m3u8.loads(m3u8_text)
        return url, m3u8_text

    def get_playlist(self, playsession: str) -> tuple:
        response = self.client.get(playsession).json()

        if response["errorCode"] == 1:
            geo_error(403, None, location="CA")

        if response["errorCode"] == 35:
            premium_error(403)

        return self.get_hls(response.get("url"))

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

        if self.url and not any(
            [self.episode, self.season, self.complete, self.movie, self.titles]
        ):
            error("URL is missing an argument. See --help for more information")
            return

        if is_url(self.episode):
            error("Episode URL not supported. Use standard method")
            return

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

        if not downloads:
            error("Requested data returned empty. See --help for more information")
            return
            
        for download in downloads:
            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        with self.console.status("Getting media info..."):
            mpd_url, m3u8 = self.get_playlist(stream.data)
            self.res, audio = self.get_mediainfo(self.quality, m3u8)

        if self.info:
            print_info(self, stream)

        self.filename = set_filename(self, stream, self.res, audio)
        self.save_path = set_save_path(stream, self, title)
        self.manifest = self.tmp / "manifest.m3u8" if self.xml else mpd_url
        self.key_file = None  # Not encrypted
        self.sub_path = None

        info(f"{str(stream)}")
        click.echo("")

        args, file_path = get_args(self)

        if not file_path.exists():
            try:
                subprocess.run(args, check=True)
            except Exception as e:
                raise ValueError(f"{e}")
        else:
            info(f"{self.filename} already exist. Skipping download\n")
            self.sub_path.unlink() if self.sub_path else None
            pass
