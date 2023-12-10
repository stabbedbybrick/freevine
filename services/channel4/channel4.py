"""
Credit to Diazole and rlaphoenix for paving the way

Author: stabbedbybrick

Info:
This program will grab higher 1080p bitrate (if available)

"""
from __future__ import annotations

import base64
import re
import subprocess
import json
import sys

from pathlib import Path
from collections import Counter

import click
import yaml

from bs4 import BeautifulSoup
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from utils.utilities import (
    info,
    error,
    string_cleaning,
    set_save_path,
    set_filename,
    kid_to_pssh,
    get_wvd,
    geo_error,
)
from utils.titles import Episode, Series, Movie, Movies
from utils.options import get_downloads
from utils.args import get_args
from utils.info import print_info
from utils.config import Config
from utils.cdm import LocalCDM


class CHANNEL4(Config):
    def __init__(self, config, srvc_api, srvc_config, **kwargs):
        super().__init__(config, srvc_api, srvc_config, **kwargs)

        with open(self.srvc_api, "r") as f:
            self.config.update(yaml.safe_load(f))

        self.get_options()

    def get_license(self, challenge: bytes, lic_url: str, assets: tuple) -> str:
        manifest, token, asset = assets
        payload = {
            "message": base64.b64encode(challenge).decode("utf8"),
            "token": token,
            "request_id": asset,
            "video": {"type": "ondemand", "url": manifest},
        }

        r = self.client.post(lic_url, json=payload)
        if not r.is_success:
            error(f"License request failed: {r.json()['status']['type']}")
            sys.exit(1)

        return r.json()["license"]

    def get_keys(self, pssh: str, lic_url: str, assets: tuple):
        wvd = get_wvd(Path.cwd())
        with self.console.status("Getting decryption keys..."):
            widevine = LocalCDM(wvd)
            challenge = widevine.challenge(pssh)
            response = self.get_license(challenge, lic_url, assets)
            return widevine.parse(response)

    def decrypt_token(self, token: str) -> tuple:
        if self.config["client"] == "android":
            key = self.config["android"]["key"]
            iv = self.config["android"]["iv"]

        if self.config["client"] == "web":
            key = self.config["web"]["key"]
            iv = self.config["web"]["iv"]

        if isinstance(token, str):
            token = base64.b64decode(token)
            cipher = AES.new(
                key=base64.b64decode(key),
                iv=base64.b64decode(iv),
                mode=AES.MODE_CBC,
            )
            data = unpad(cipher.decrypt(token), AES.block_size)
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

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
                    id_=episode.get("programmeId"),
                    service="ALL4",
                    title=data["brand"]["title"],
                    season=episode["seriesNumber"],
                    number=episode["episodeNumber"],
                    name=episode["originalTitle"],
                    year=None,
                    data=episode.get("assetId"),
                    description=episode.get("summary"),
                )
                for episode in data["brand"]["episodes"]
                if episode["showPlayLabel"] == True
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
                    synopsis=movie.get("summary"),
                )
                for movie in data["brand"]["episodes"]
            ]
        )

    def authenticate(self):
        login = self.config["login"]

        headers = {
            "authorization": f"Basic {self.config['android']['auth']}",
            "x-c4-platform-name": "android",
            "x-c4-device-type": "mobile",
            "x-c4-app-version": "android_app:9.4.2",
            "x-c4-device-name": "Sony C6903 (C6903)",
            "x-c4-optimizely-datafile": "2908",
        }

        data = {
            "grant_type": "password",
            "username": "ol.ivea.gu.ilar.4.1.2@gmail.com",
            "password": "Ol.ivea.gu.ilar.4.1.2",
        }

        r = self.client.post(login, headers=headers, data=data)
        if not r.is_success:
            error(f"{r} {r.text}")
            sys.exit(1)

        return r.json()["accessToken"]

    def get_playlist(self, episode_id: str) -> tuple:
        if self.config["client"] == "android":
            url = self.config["android"]["vod"].format(episode_id=episode_id)

            token = self.authenticate()

            headers = {
                "authorization": f"Bearer {token}",
                "x-c4-platform-name": "android",
                "x-c4-device-type": "mobile",
                "x-c4-app-version": '"android_app:9.4.2"',
                "x-c4-device-name": "Sony C6903 (C6903)",
                "x-c4-optimizely-datafile": "2908",
            }

            r = self.client.get(url=url, headers=headers)
            if not r.is_success:
                error(f"{r} {r.text}")
                sys.exit(1)

            manifest = r.json()["videoProfiles"][0]["streams"][0]["uri"]
            token = r.json()["videoProfiles"][0]["streams"][0]["token"]

        else:
            url = self.config["web"]["vod"].format(programmeId=episode_id)

            r = self.client.get(url)
            if not r.is_success:
                geo_error(r.status_code, r.json().get("message"), location="UK")

            data = json.loads(r.content)

            for item in data["videoProfiles"]:
                if item["name"] == "dashwv-dyn-stream-1":
                    token = item["streams"][0]["token"]
                    manifest = item["streams"][0]["uri"]

        return manifest, token

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        self.soup = BeautifulSoup(self.client.get(manifest), "xml")
        elements = self.soup.find_all("Representation")
        heights = sorted(
            [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
            reverse=True,
        )

        if quality is not None:
            if int(quality) in heights:
                return quality
            else:
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                return closest_match

        return heights[0]

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

    def get_episode_from_url(self, url: str):
        brand = self.get_data(url)

        episode = Series(
            [
                Episode(
                    id_=brand["selectedEpisode"]["programmeId"],
                    service="ALL4",
                    title=brand["brand"]["title"],
                    season=brand["selectedEpisode"]["seriesNumber"] or 0,
                    number=brand["selectedEpisode"]["episodeNumber"] or 0,
                    name=brand["selectedEpisode"]["originalTitle"],
                    year=None,
                    data=brand["selectedEpisode"].get("assetId"),
                    description=brand["selectedEpisode"].get("summary"),
                )
            ]
        )

        title = string_cleaning(str(episode))

        return [episode[0]], title

    def get_options(self) -> None:
        downloads, title = get_downloads(self)

        for download in downloads:
            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        with self.console.status("Getting media info..."):
            manifest, token = self.get_playlist(stream.id)
            self.res = self.get_mediainfo(manifest, self.quality)
            pssh = kid_to_pssh(self.soup)
            token, lic_url = self.decrypt_token(token)
            assets = manifest, token, stream.data

        keys = self.get_keys(pssh, lic_url, assets)
        with open(self.tmp / "keys.txt", "w") as file:
            file.write("\n".join(keys))

        if self.info:
            print_info(self, stream, keys)

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        info(f"{str(stream)}")
        info(f"{keys[0]}")
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
