"""
Credit to Diazole(https://github.com/Diazole/my5-dl) for solving the keys 

Author: stabbedbybrick

Info:
Channel5 now offers up to 1080p

"""
from __future__ import annotations

import base64
import subprocess
import json
import hmac
import hashlib
import shutil
import re

from urllib.parse import urlparse, urlunparse
from collections import Counter
from datetime import datetime
from pathlib import Path

import click
import yaml

from bs4 import BeautifulSoup
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from utils.utilities import (
    info,
    error,
    is_url,
    string_cleaning,
    set_save_path,
    print_info,
    set_filename,
    get_wvd,
)
from utils.titles import Episode, Series, Movie, Movies
from utils.options import Options
from utils.args import get_args
from utils.config import Config
from utils.cdm import LocalCDM


class CHANNEL5(Config):
    def __init__(self, config, srvc_api, srvc_config, **kwargs):
        super().__init__(config, srvc_api, srvc_config, **kwargs)

        with open(self.srvc_api, "r") as f:
            self.config.update(yaml.safe_load(f))

        self.gist = self.client.get(
            self.config["gist"].format(timestamp=datetime.now().timestamp())
        ).json()

        self.get_options()

    def get_license(self, challenge: bytes, lic_url: str) -> bytes:
        r = self.client.post(url=lic_url, data=challenge)
        if not r.is_success:
            error(f"License request failed: {r.status_code}")
            exit(1)
        return r.content

    def get_keys(self, pssh: str, lic_url: str) -> bytes:
        wvd = get_wvd(Path.cwd())
        with self.console.status("Getting decryption keys..."):
            widevine = LocalCDM(wvd)
            challenge = widevine.challenge(pssh)
            response = self.get_license(challenge, lic_url)
            return widevine.parse(response)

    def get_data(self, url: str) -> json:
        show = urlparse(url).path.split("/")[2]
        url = self.config["content"].format(show=show)

        return self.client.get(url).json()

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
                    id_=None,
                    service="MY5",
                    title=episode.get("sh_title"),
                    season=int(episode.get("sea_num")) or 0,
                    number=int(episode.get("ep_num")) or 0,
                    name=episode.get("title"),
                    year=None,
                    data=episode.get("id"),
                    description=episode.get("s_desc"),
                )
                for episode in data["episodes"]
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)

        return Movies(
            [
                Movie(
                    id_=None,
                    service="MY5",
                    title=movie["sh_title"],
                    year=None,
                    name=movie["sh_title"],
                    data=movie.get("id"),
                    synopsis=movie.get("s_desc"),
                )
                for movie in data["episodes"]
            ]
        )

    def decrypt_data(self, media: str) -> dict:
        key = base64.b64decode(self.gist["key"])

        r = self.client.get(media)
        if not r.is_success:
            print(f"{r}\n{r.content}")
            shutil.rmtree(self.tmp)
            exit(1)

        content = r.json()

        iv = base64.urlsafe_b64decode(content["iv"])
        data = base64.urlsafe_b64decode(content["data"])

        cipher = AES.new(key=key, iv=iv, mode=AES.MODE_CBC)
        decrypted_data = unpad(cipher.decrypt(data), AES.block_size)
        return json.loads(decrypted_data)

    def get_playlist(self, asset_id: str) -> tuple:
        secret = self.gist["hmac"]

        timestamp = datetime.now().timestamp()
        vod = self.config["vod"].format(id=asset_id, timestamp=f"{timestamp}")
        sig = hmac.new(base64.b64decode(secret), vod.encode(), hashlib.sha256)
        auth = base64.urlsafe_b64encode(sig.digest()).decode()
        vod += f"&auth={auth}"

        data = self.decrypt_data(vod)

        asset = [x for x in data["assets"] if x["drm"] == "widevine"][0]
        rendition = asset["renditions"][0]
        mpd_url = rendition["url"]
        lic_url = asset["keyserver"]

        parse = urlparse(mpd_url)
        path = parse.path.split("/")
        path[-1] = path[-1].split("-")[0].split("_")[0]
        manifest = urlunparse(parse._replace(path="/".join(path)))
        manifest += ".mpd" if not manifest.endswith("mpd") else ""

        return manifest, lic_url

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

    def get_mediainfo(self, manifest: str, quality: str) -> tuple:
        self.soup = BeautifulSoup(self.client.get(manifest), "xml")
        pssh = self.get_pssh(self.soup)
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
                return closest_match, pssh

        return heights[0], pssh

    def get_content(self, url: str) -> tuple:
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
        url = url.lower()
        series_re = r"^(?:https?://(?:www\.)?channel5\.com/show/)?(?P<id>[a-z0-9-]+)"
        episode_re = r"https?://www.channel5.com/(?:show/)?(?P<id>[^/]+)/(?P<season>[^/]+)/(?P<episode>[^/]+)"

        series_match = re.search(series_re, url)
        episode_match = re.search(episode_re, url)

        if series_match:
            url = self.config["content"].format(show=series_match.group("id"))

        if episode_match:
            url = self.config["single"].format(
                show=episode_match.group("id"),
                season=episode_match.group("season"),
                episode=episode_match.group("episode"),
            )

        if not series_match and not episode_match:
            error("Invalid URL")
            exit(1)

        data = self.client.get(url).json()

        episodes = [data] if episode_match else data["episodes"]

        episode = Series(
            [
                Episode(
                    id_=None,
                    service="MY5",
                    title=episode.get("sh_title"),
                    season=int(episode.get("sea_num"))
                    if data.get("sea_num") is not None
                    else 0,
                    number=int(episode.get("ep_num"))
                    if data.get("ep_num") is not None
                    else 0,
                    name=episode.get("sh_title"),
                    year=None,
                    data=episode.get("id"),
                    description=episode.get("m_desc"),
                )
                for episode in episodes
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

        keys = self.get_keys(pssh, lic_url)
        with open(self.tmp / "keys.txt", "w") as file:
            file.write("\n".join(keys))

        if self.info:
            print_info(self, stream, keys)

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self.config, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        info(f"{str(stream)}")
        for key in keys:
            info(f"{key}")
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
