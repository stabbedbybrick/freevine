"""
Credit to rlaphoenix for the title storage

Author: stabbedbybrick

Info:

Quality: 1080p, AAC 2.0 max

"""

import base64
import subprocess
import json
import shutil
import sys
import urllib.parse

from collections import Counter
from pathlib import Path

import click
import yaml

from bs4 import BeautifulSoup

from utils.utilities import (
    info,
    error,
    is_url,
    string_cleaning,
    set_save_path,
    print_info,
    set_filename,
)
from utils.titles import Episode, Series
from utils.options import Options
from utils.args import get_args
from utils.config import Config
from utils.cdm import LocalCDM


class STV(Config):
    def __init__(self, config, srvc_api, srvc_config, wvd, **kwargs):
        super().__init__(config, srvc_api, srvc_config, wvd, **kwargs)

        with open(self.srvc_api, "r") as f:
            self.config.update(yaml.safe_load(f))

        self.vod = self.config["vod"]
        self.api = self.config["api"]

        self.get_options()

    def get_license(self, challenge: bytes, lic_url: str) -> bytes:
        r = self.client.post(url=lic_url, data=challenge)
        if not r.is_success:
            error(f"License request failed: {r.status_code}")
            exit(1)
        return r.content

    def get_keys(self, pssh: str, lic_url: str) -> bytes:
        with self.console.status("Getting decryption keys..."):
            widevine = LocalCDM(self.wvd)
            challenge = widevine.challenge(pssh)
            response = self.get_license(challenge, lic_url)
            return widevine.parse(response)

    def get_data(self, url: str) -> tuple:
        soup = BeautifulSoup(self.client.get(url), "html.parser")
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
        if not r.is_success:
            print(f"\nError! {r.status_code}")
            shutil.rmtree(self.tmp)
            sys.exit(1)

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
                    and "movie" not in episode["playerSeries"]["name"]
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

    def get_pssh(self, soup: str) -> str:
        kid = (
            soup.select_one("ContentProtection")
            .attrs.get("cenc:default_KID")
            .replace("-", "")
        )
        version = "3870737368"
        system_id = "EDEF8BA979D64ACEA3C827DCD51D21ED"
        data = "48E3DC959B06"
        s = f"000000{version}00000000{system_id}000000181210{kid}{data}"
        return base64.b64encode(bytes.fromhex(s)).decode()

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        self.soup = BeautifulSoup(self.client.get(manifest), "xml")
        pssh = self.get_pssh(self.soup) if self.drm else None
        elements = self.soup.find_all("Representation")
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

    def get_content(self, url: str) -> object:
        with self.console.status("Fetching titles..."):
            data = self.get_data(url)
            content = self.get_series(data)

            title = string_cleaning(str(content))
            seasons = Counter(x.season for x in content)
            num_seasons = len(seasons)
            num_episodes = sum(seasons.values())

        info(f"{str(content)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n")

        return content, title

    def get_episode_from_url(self, url: str):
        soup = BeautifulSoup(self.client.get(url), "html.parser")
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
        opt = Options(self)

        if self.url and not any(
            [self.episode, self.season, self.complete, self.movie, self.titles]
        ):
            error("URL is missing an argument. See --help for more information")
            return

        if is_url(self.episode):
            downloads, title = self.get_episode_from_url(self.episode)

        else:
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
            manifest, lic_url = self.get_playlist(stream.data)
            self.res, pssh = self.get_mediainfo(manifest, self.quality)

        keys = None
        if self.drm:
            keys = self.get_keys(pssh, lic_url)
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        if self.info:
            print_info(self, stream, keys)

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self.config, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt" if self.drm else None
        self.sub_path = None

        info(f"{str(stream)}")
        info(f"{keys[0]}") if self.drm else info("No encryption found")
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
