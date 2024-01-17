"""
Credit to Diazole(https://github.com/Diazole/my5-dl) for solving the keys 

Author: stabbedbybrick

Info:
Channel5 now offers up to 1080p

"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import click
from bs4 import BeautifulSoup
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from utils.args import get_args
from utils.cdm import LocalCDM
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    force_numbering,
    get_wvd,
    in_cache,
    kid_to_pssh,
    set_filename,
    set_save_path,
    string_cleaning,
    update_cache,
)


class CHANNEL5(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        with self.config["download_cache"].open("r") as file:
            self.cache = json.load(file)

        self.gist = self.client.get(
            self.config["gist"].format(timestamp=datetime.now().timestamp())
        ).json()

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

    def get_data(self, url: str) -> json:
        show = urlparse(url).path.split("/")[2]
        url = self.config["content"].format(show=show)

        return self.client.get(url).json()

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
                    id_=episode.get("id"),
                    service="MY5",
                    title=episode.get("sh_title"),
                    season=int(episode.get("sea_num")) or 0,
                    number=int(episode.get("ep_num")) or 0,
                    name=episode.get("title"),
                    year=None,
                    data=None,
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
                    id_=movie.get("id"),
                    service="MY5",
                    title=movie["sh_title"],
                    year=None,
                    name=movie["sh_title"],
                    data=None,
                    synopsis=movie.get("s_desc"),
                )
                for movie in data["episodes"]
            ]
        )

    def decrypt_data(self, media: str) -> dict:
        key = base64.b64decode(self.gist["key"])

        r = self.client.get(media)
        if not r.ok:
            raise ConnectionError(r.json().get("message"))

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

    def get_mediainfo(self, manifest: str, quality: str) -> tuple:
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

    def get_content(self, url: str) -> tuple:
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

    def get_episode_from_url(self, url: str):
        with self.console.status("Getting episode from URL..."):
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
                self.log.error("Invalid URL")
                sys.exit(1)

            data = self.client.get(url).json()

            episodes = [data] if episode_match else data["episodes"]

            episode = Series(
                [
                    Episode(
                        id_=episode.get("id"),
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
                        data=None,
                        description=episode.get("m_desc"),
                    )
                    for episode in episodes
                ]
            )

        title = string_cleaning(str(episode))

        return [episode[0]], title

    def get_options(self) -> None:
        downloads, title = get_downloads(self)

        for download in downloads:
            if in_cache(self.cache, download):
                continue

            if self.slowdown:
                with self.console.status(f"Slowing things down for {self.slowdown} seconds..."):
                    time.sleep(self.slowdown)

            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        manifest, lic_url = self.get_playlist(stream.id)
        self.res = self.get_mediainfo(manifest, self.quality)
        pssh = kid_to_pssh(self.soup)

        keys = self.get_keys(pssh, lic_url)
        with open(self.tmp / "keys.txt", "w") as file:
            file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        self.log.info(f"{str(stream)}")
        for key in keys:
            self.log.info(f"{key}")
        click.echo("")

        args, file_path = get_args(self)

        if not file_path.exists():
            try:
                subprocess.run(args, check=True)
            except Exception as e:
                raise ValueError(f"{e}")
        else:
            self.log.info(f"{self.filename} already exists. Skipping download...\n")
            self.sub_path.unlink() if self.sub_path else None
        
        if not self.skip_download and file_path.exists():
            update_cache(self.cache, self.config, stream)
