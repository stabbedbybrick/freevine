"""
TVNZ
Author: stabbedbybrick

Info:
720p, AAC2.0

"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import click
import httpx
import yaml

from utils.args import get_args
from utils.cdm import LocalCDM
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    append_id,
    force_numbering,
    get_heights,
    get_wvd,
    in_cache,
    kid_to_pssh,
    set_filename,
    set_save_path,
    string_cleaning,
    update_cache,
)


class TVNZ(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        self.username = self.config.get("credentials", {}).get("username")
        self.password = self.config.get("credentials", {}).get("password")

        with self.config["download_cache"].open("r") as file:
            self.cache = json.load(file)

        self.get_options()

    def get_auth_token(self):
        cache = self.config.get("cache")

        if not cache:
            self.log.info("Cache is empty, aquiring new tokens...")
            token = self.authenticate()
        elif cache and cache.get("expiry") < datetime.now():
            self.log.info("Token expired, logging in...")
            token = self.authenticate()
        else:
            self.log.info("Using cached tokens")
            token = cache.get("token")

        return token

    def get_license(self, challenge: bytes, lic_url: str) -> str:
        r = self.client.post(url=lic_url, data=challenge)
        r.raise_for_status()
        return r.content

    def get_keys(self, pssh: str, lic_url: str):
        wvd = get_wvd(Path.cwd())
        widevine = LocalCDM(wvd)
        challenge = widevine.challenge(pssh)
        response = self.get_license(challenge, lic_url)
        return widevine.parse(response)

    def get_data(self, url: str) -> dict:
        title_id = urlparse(url).path.split("/")[2]
        r = self.client.get(self.config["show"].format(title_id=title_id))
        if not r.ok:
            raise ConnectionError(f"{r} - {r.json().get('message')}")

        content = r.json()["layout"]["slots"]["main"]["modules"][0]["lists"]
        title = r.json()["title"].replace("Episodes", "").replace("Movie", "").strip()

        return content, title

    async def season_data(self, href: str, async_client: httpx.AsyncClient) -> json:
        r = await async_client.get(href)
        if not r.is_success:
            raise ConnectionError(r.content)

        return r.json()["_embedded"]

    async def get_season_data(self, hrefs: list) -> list:
        async with httpx.AsyncClient(headers=self.client.headers) as async_client:
            tasks = [
                self.season_data(self.config["api"] + x, async_client) for x in hrefs
            ]
            return await asyncio.gather(*tasks)

    def create_episode(self, episode: dict, title: str):
        season = episode.get("seasonNumber", 0)
        season_number = 0 if "Special" in season else int(season)
        number = episode.get("episodeNumber")
        episode_number = 0 if "Special" in number else int(number)

        account_id = episode["publisherMetadata"]["brightcoveAccountId"]
        video_id = episode["publisherMetadata"]["brightcoveVideoId"]

        return Episode(
            id_=episode.get("videoId"),
            service="TVNZ",
            title=title,
            season=season_number,
            number=episode_number,
            name=episode.get("title"),
            data=(video_id, account_id),
        )

    def get_series(self, url: str) -> Series:
        data, title = self.get_data(url)
        hrefs = [x["href"] for x in data if x.get("href")]
        seasons = asyncio.run(self.get_season_data(hrefs))

        return Series(
            [
                self.create_episode(episode, title)
                for season in seasons
                for episode in season.values()
                if episode.get("videoType") == "EPISODE"
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data, _ = self.get_data(url)
        href = [x["href"] for x in data if x.get("href")][0]

        r = self.client.get(self.config["api"] + href)
        if not r.ok:
            raise ConnectionError(r)

        data = r.json()["_embedded"]
        for x in data.values():
            account_id = x["publisherMetadata"]["brightcoveAccountId"]
            video_id = x["publisherMetadata"]["brightcoveVideoId"]

        return Movies(
            [
                Movie(
                    id_=movie.get("videoId"),
                    service="TVNZ",
                    title=movie.get("title"),
                    year=None,
                    name=movie.get("title"),
                    data=(video_id, account_id),
                    synopsis=movie.get("summary"),
                )
                for movie in data.values()
            ]
        )

    def authenticate(self):
        if not self.username and not self.password:
            self.log.error(
                "Required credentials were not found. See 'freevine.py profile --help'"
            )
            sys.exit(1)

        self.log.info("Authenticating with service...")

        headers = {
            "auth0_client": self.config["auth0_client"],
            "referer": "https://www.tvnz.co.nz/",
        }

        payload = {
            "client_id": self.config["client_id"],
            "credential_type": "password",
            "password": self.password,
            "username": self.username,
        }

        r = self.client.post(self.config["login"], headers=headers, json=payload)
        if not r.ok:
            raise ConnectionError(f"{r} {r.text}")

        params = {
            "client_id": self.config["client_id"],
            "response_type": "token",
            "redirect_uri": "https://www.tvnz.co.nz/login",
            "audience": "tvnz-apis",
            "state": base64.b64encode(os.urandom(24)).decode(),
            "response_mode": "web_message",
            "login_ticket": r.json()["login_ticket"],
            "prompt": "none",
            "auth0Client": self.config["auth0_client"],
        }

        r = self.client.get(self.config["authorize"], params=params)
        if not r.ok:
            raise ConnectionError(f"{r} {r.text}")

        json_str = re.search(r"response: ({.*};)", r.text).group(1).replace("}};", "}")

        auth = json.loads(json_str)
        token = auth.get("access_token")

        expiry = datetime.now() + timedelta(seconds=auth.get("expires_in"))

        profile = Path("services") / "tvnz" / "profile.yaml"
        with open(profile, "r") as f:
            data = yaml.safe_load(f)

        data["cache"] = {"token": token, "expiry": expiry, "refresh": None}

        with open(profile, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)

        self.log.info("+ New tokens placed in cache")

        return token

    def get_playlist(self, data: tuple) -> tuple:
        video_id, account_id = data
        headers = {
            "Accept": "application/json;pk=BCpkADawqM1N12WMDn4W-_"
            "kPR1HP17qWAzLwRMnN2S11amDldHxufQMiBfcXaYthGVkx1iJgFCAkbCAJ0R-"
            "z8S-gWFcZg7BcmerduckK-Lycyvgpe4prhFDj6jCMrXMq4F5lS5FVEymSDlpMK2-"
            "lK87-RK62ifeRgK7m_Q"
        }
        url = self.config["play"].format(account_id=account_id, video_id=video_id)

        r = self.client.get(url, headers=headers)
        if not r.ok:
            raise ConnectionError(f"{r.text}")

        content = json.loads(r.content)

        manifest = [
            source["src"]
            for source in content["sources"]
            if source.get("type") == "application/dash+xml"
        ][0]

        key_systems = [
            source
            for source in content["sources"]
            if source.get("type") == "application/dash+xml"
            and source.get("key_systems").get("com.widevine.alpha")
        ]

        lic_url = key_systems[0]["key_systems"]["com.widevine.alpha"]["license_url"]

        return manifest, lic_url

    def get_mediainfo(self, quality: str, manifest: str) -> str:
        heights, soup = get_heights(self.client, manifest)
        resolution = heights[0]

        if quality is not None:
            if int(quality) in heights:
                resolution = quality
            else:
                resolution = min(heights, key=lambda x: abs(int(x) - int(quality)))

        return resolution, soup

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
                if self.append_id:
                    content = append_id(content)

            self.log.info(
                f"{str(content)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"
            )

        return content, title

    def get_episode_from_url(self, url: str):
        with self.console.status("Getting episode from URL..."):
            data, title = self.get_data(url)
            href = [x["href"] for x in data if x.get("href")][0]

            r = self.client.get(self.config["api"] + href)
            if not r.ok:
                raise ConnectionError(r)

            data = r.json()["_embedded"]
            for x in data.values():
                if x["page"]["url"] in url:
                    account_id = x["publisherMetadata"]["brightcoveAccountId"]
                    video_id = x["publisherMetadata"]["brightcoveVideoId"]

                    season = x.get("seasonNumber", 0)
                    season_number = 0 if "Special" in season else int(season)
                    number = x.get("episodeNumber")
                    episode_number = 0 if "Special" in number else int(number)

            episode = Series(
                [
                    Episode(
                        id_=episode.get("videoId"),
                        service="TVNZ",
                        title=title,
                        season=season_number,
                        number=episode_number,
                        name=episode.get("title"),
                        data=(video_id, account_id),
                    )
                    for episode in data.values()
                    if episode["page"]["url"] in url
                ]
            )

        title = string_cleaning(str(episode))

        return [episode[0]], title

    def get_options(self) -> None:
        token = self.get_auth_token()
        self.client.headers.update(
            {
                "authorization": f"Bearer {token}",
            }
        )
        downloads, title = get_downloads(self)

        for download in downloads:
            if not self.no_cache and in_cache(self.cache, download):
                continue

            if self.slowdown:
                with self.console.status(
                    f"Slowing things down for {self.slowdown} seconds..."
                ):
                    time.sleep(self.slowdown)

            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        manifest, lic_url = self.get_playlist(stream.data)
        self.res, self.soup = self.get_mediainfo(self.quality, manifest)
        pssh = kid_to_pssh(self.soup)

        keys = self.get_keys(pssh, lic_url)
        with open(self.tmp / "keys.txt", "w") as file:
            file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        click.echo("")
        self.log.info(f"{str(stream)}")
        click.echo("")

        args, file_path = get_args(self)

        if not file_path.exists():
            try:
                subprocess.run(args, check=True)
                click.echo("")
            except Exception as e:
                raise ValueError(f"{e}")
        else:
            self.log.warning(f"{self.filename} already exists. Skipping download...\n")
            self.sub_path.unlink() if self.sub_path else None

        if not self.skip_download and file_path.exists():
            update_cache(self.cache, self.config, stream)
