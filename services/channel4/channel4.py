"""
Credit to Diazole and rlaphoenix for paving the way

Author: stabbedbybrick

Info:
This program will grab higher 1080p bitrate (if available)

"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import click
import yaml
from bs4 import BeautifulSoup
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from utils.args import get_args
from utils.cdm import LocalCDM
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    expiration,
    get_wvd,
    info,
    kid_to_pssh,
    set_filename,
    set_save_path,
    string_cleaning,
)


class CHANNEL4(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        self.login = self.config["login"]
        self.username = self.config.get("credentials", {}).get("username")
        self.password = self.config.get("credentials", {}).get("password")

        self.client.headers = {
            "x-c4-platform-name": "android",
            "x-c4-device-type": "mobile",
            "x-c4-app-version": "android_app:9.4.2",
            "x-c4-device-name": "Sony C6903 (C6903)",
            "x-c4-optimizely-datafile": "2908",
        }

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
        if not r.ok:
            self.log.error(f"License request failed: {r.json()['status']['type']}")
            sys.exit(1)

        return r.json()["license"]

    def get_keys(self, pssh: str, lic_url: str, assets: tuple):
        wvd = get_wvd(Path.cwd())
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
            "<script>window.__PARAMS__ = (.*)</script>",
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
                if episode["showPlayLabel"] is True
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

    def refresh_token(self):
        self.client.headers.update(
            {
                "authorization": f"Basic {self.config['android']['auth']}",
            }
        )

        data = {
            "grant_type": "refresh_token",
            "username": self.username,
            "password": self.password,
            "refresh_token": self.config["cache"]["refresh"],
        }

        r = self.client.post(self.login, data=data)
        if not r.ok:
            self.log.error(f"{r} {r.text}")
            sys.exit(1)

        auth = json.loads(r.content)
        token = auth.get("accessToken")
        refresh = auth.get("refreshToken")

        expiry = expiration(auth.get("expiresIn"), auth.get("issuedAt"))

        profile = Path("services") / "channel4" / "profile.yaml"
        with open(profile, "r") as f:
            data = yaml.safe_load(f)

        data["cache"]["token"] = token
        data["cache"]["refresh"] = refresh
        data["cache"]["expiry"] = expiry

        with open(profile, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)

        self.log.info("+ Tokens refreshed")

        return token

    def authenticate(self):
        if not self.username and not self.password:
            self.log.error(
                "Required credentials were not found. See 'freevine.py profile --help'"
            )
            sys.exit(1)

        self.log.info("Authenticating with service...")

        self.client.headers.update(
            {
                "authorization": f"Basic {self.config['android']['auth']}",
            }
        )

        data = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
        }

        r = self.client.post(self.login, data=data)
        if not r.ok:
            self.log.error(f"{r} {r.text}")
            sys.exit(1)

        auth = json.loads(r.content)
        token = auth.get("accessToken")
        refresh = auth.get("refreshToken")

        expiry = expiration(auth.get("expiresIn"), auth.get("issuedAt"))

        profile = Path("services") / "channel4" / "profile.yaml"
        with open(profile, "r") as f:
            data = yaml.safe_load(f)

        data["cache"] = {"token": token, "expiry": expiry, "refresh": refresh}

        with open(profile, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)

        self.log.info("+ New tokens placed in cache")

        return token

    def get_playlist(self, episode_id: str) -> tuple:
        if self.config["client"] == "android":
            cache = self.config.get("cache")

            if not cache:
                self.log.info("Cache is empty, aquiring new tokens...")
                token = self.authenticate()
            elif cache and cache.get("expiry") < datetime.now():
                self.log.info("Refreshing expired tokens...")
                token = self.refresh_token()
            else:
                self.log.info("Using cached tokens")
                token = cache.get("token")

            url = self.config["android"]["vod"].format(episode_id=episode_id)

            self.client.headers.update({"authorization": f"Bearer {token}"})

            r = self.client.get(url=url)
            if not r.ok:
                self.log.error(f"{r} {r.text}")
                sys.exit(1)

            data = json.loads(r.content)
            manifest = data["videoProfiles"][0]["streams"][0]["uri"]
            token = data["videoProfiles"][0]["streams"][0]["token"]

        else:
            url = self.config["web"]["vod"].format(programmeId=episode_id)

            r = self.client.get(url)
            if not r.ok:
                self.log.error(f"{r} {r.json().get('message')}")
                sys.exit(1)

            data = json.loads(r.content)

            for item in data["videoProfiles"]:
                if item["name"] == "dashwv-dyn-stream-1":
                    token = item["streams"][0]["token"]
                    manifest = item["streams"][0]["uri"]

        return manifest, token

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        r = self.client.get(manifest)
        r.raise_for_status()

        self.soup = BeautifulSoup(r.text, "xml")
        elements = self.soup.find_all("Representation")
        heights = sorted(
            [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
            reverse=True,
        )

        if quality is not None:
            if int(quality) in heights:
                return quality
            else:
                self.log.info("Requested quality not available - getting closest match")
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                return closest_match

        return heights[0]

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

            self.log.info(
                f"{str(content)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"
            )

        return content, title

    def get_episode_from_url(self, url: str):
        with self.console.status("Getting episode from URL..."):
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

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        self.log.info(f"{str(stream)}")
        self.log.info(f"{keys[0]}")
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
