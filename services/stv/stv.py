"""
Credit to rlaphoenix for the title storage

Author: stabbedbybrick

Info:

Quality: 1080p, AAC 2.0 max

"""
from __future__ import annotations

import json
import subprocess
import urllib.parse
import re
from collections import Counter
from pathlib import Path

import click
from bs4 import BeautifulSoup

from utils.args import get_args
from utils.cdm import LocalCDM
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Series
from utils.utilities import (
    construct_pssh,
    get_wvd,
    set_filename,
    set_save_path,
    string_cleaning,
)


class STV(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        self.vod = self.config["vod"]
        self.api = self.config["api"]

        self.get_options()

    def get_license(self, challenge: bytes, lic_url: str) -> bytes:
        r = self.client.post(url=lic_url, data=challenge)
        r.raise_for_status()
        return r.content

    def get_keys(self, pssh: str, lic_url: str) -> bytes:
        wvd = get_wvd(Path.cwd())
        widevine = LocalCDM(wvd)
        challenge = widevine.challenge(pssh)
        response = self.get_license(challenge, lic_url)
        return widevine.parse(response)

    def get_data(self, url: str) -> tuple:
        r = self.client.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        props = soup.select_one("#__NEXT_DATA__").text
        data = json.loads(props)
        data = data["props"]["pageProps"]["data"]

        params = [
            urllib.parse.urlencode(x["params"]["query"])
            for x in data["tabs"]
            if x["params"]["path"] == "/episodes"
        ]

        self.drm = data["programmeData"]["drmEnabled"]

        headers = {"stv-drm": "true"} if self.drm else None

        seasons = [
            self.client.get(f"{self.vod}{param}", headers=headers).json()
            for param in params
        ]

        return seasons

    def account_config(self, drm: bool) -> tuple:
        pkey = {
            "Accept": "application/json;pk="
            "BCpkADawqM1WJ12PwtUWqGXx3nbAo2XVSxyAQxPRZKBc75svhrUB9qIMPN_"
            "d9US0Vib5smumeNMbntSmZIpzeVV1iUrnzYgf5k7UMaVN46PGYe_oSZ-xbPVnsm4"
        }

        pkey_drm = {
            "Accept": "application/json;pk="
            "BCpkADawqM1fQNUrQOvg-vTo4VGDTJ_lGjxp2zBSPcXJntYd5csQkjm7hBKviIVgfFoEJLW4_"
            "JPPsHUwXNEjZspbr3d1HqGDw2gUqGCBZ_9Y_BF7HJsh2n6PQcpL9b2kdbi103oXvmTNZWiQ"
        }

        headers = pkey_drm if drm else pkey
        account = "6204867266001" if drm else "1486976045"

        return headers, account

    def get_playlist(self, video_id: str):
        lic_url = None
        headers, account = self.account_config(self.drm)
        url = f"{self.api}/{account}/videos/{video_id}"

        r = self.client.get(url, headers=headers)
        r.raise_for_status()

        data = r.json()

        manifest = [
            source["src"]
            for source in data["sources"]
            if source.get("type") == "application/dash+xml"
        ][0]

        if self.drm:
            key_systems = [
                source
                for source in data["sources"]
                if source.get("type") == "application/dash+xml"
                and source.get("key_systems").get("com.widevine.alpha")
            ]

            lic_url = key_systems[0]["key_systems"]["com.widevine.alpha"]["license_url"]

        return manifest, lic_url

    def get_series(self, data: list):
        return Series(
            [
                Episode(
                    id_=None,
                    service="STV",
                    title=episode["programme"]["name"],
                    season=int(episode["playerSeries"]["name"].split(" ")[1])
                    if episode["playerSeries"] is not None
                    and re.match(r"Series \d+", episode["playerSeries"]["name"])
                    else 0,
                    number=episode.get("number") or 0,
                    name=episode.get("title"),
                    year=None,
                    data=episode["video"]["id"],
                    description=episode.get("summary"),
                )
                for series in data
                for episode in series["results"]
            ]
        )

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
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                return closest_match

        return heights[0]

    def get_content(self, url: str) -> object:
        with self.console.status("Fetching series titles..."):
            data = self.get_data(url)
            content = self.get_series(data)

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
            r = self.client.get(url)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            props = soup.select_one("#__NEXT_DATA__").text
            data = json.loads(props)

            episode_id = data["props"]["pageProps"]["episodeId"]
            content = data["props"]["initialReduxState"]["playerApiCache"][
                f"/episodes/{episode_id}"
            ]["results"]

            self.drm = content["programme"]["drmEnabled"]

            episode = Series(
                [
                    Episode(
                        id_=None,
                        service="STV",
                        title=content["programme"]["name"],
                        season=int(content["playerSeries"]["name"].split(" ")[1])
                        if content["playerSeries"] is not None
                        and "movie" not in content["playerSeries"]["name"]
                        else 0,
                        number=content.get("number") or 0,
                        name=content.get("title"),
                        year=None,
                        data=content["video"]["id"],
                        description=content.get("summary"),
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
            manifest, lic_url = self.get_playlist(stream.data)
            self.res = self.get_mediainfo(manifest, self.quality)
            pssh = construct_pssh(self.soup) if self.drm else None

        keys = None
        if self.drm:
            keys = self.get_keys(pssh, lic_url)
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt" if keys else None
        self.sub_path = None

        self.log.info(f"{str(stream)}")
        self.log.info(f"{keys[0]}") if keys else self.log.info("No encryption found")
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
