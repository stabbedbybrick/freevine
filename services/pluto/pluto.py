"""
Credit to rlaphoenix for the title storage

PlutoTV
Author: stabbedbybrick

Info:
This program will download ad-free streams with highest available quality and subtitles

Notes:
Pluto's library is very spotty, so it's highly recommended to use --titles before downloading

"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import time
import uuid
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import click
import m3u8
import requests
from bs4 import BeautifulSoup

from utils.args import get_args
from utils.cdm import LocalCDM
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    append_id,
    force_numbering,
    get_wvd,
    in_cache,
    is_path,
    is_url,
    set_filename,
    set_save_path,
    string_cleaning,
    update_cache,
)


class PLUTO(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        if is_url(self.episode):
            self.log.error(
                "Downloading by episode URL not supported. Use standard method"
            )
            return

        with self.config["download_cache"].open("r") as file:
            self.cache = json.load(file)

        self.lic_url = self.config["lic"]
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

    def get_data(self, url: str) -> dict:
        type = urlparse(url).path.split("/")[3]
        video_id = urlparse(url).path.split("/")[4]

        params = {
            "appName": "web",
            "appVersion": "na",
            "clientID": str(uuid.uuid1()),
            "deviceDNT": 0,
            "deviceId": "unknown",
            "clientModelNumber": "na",
            "serverSideAds": "false",
            "deviceMake": "unknown",
            "deviceModel": "web",
            "deviceType": "web",
            "deviceVersion": "unknown",
            "sid": str(uuid.uuid1()),
            "drmCapabilities": "widevine:L3",
        }

        response = self.client.get("https://boot.pluto.tv/v4/start", params=params)
        response.raise_for_status()

        self.token = response.json()["sessionToken"]

        info = (
            f"{self.api}/series/{video_id}/seasons"
            if type == "series"
            else f"{self.api}/items?ids={video_id}"
        )
        self.client.headers.update({"Authorization": f"Bearer {self.token}"})
        self.client.params = params

        r = self.client.get(info)
        if not r.ok:
            raise ConnectionError(f"{r.status_code} - {r.json().get('message')}")

        return r.json()

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
                    id_=episode["_id"],
                    service="PLUTO",
                    title=data["name"],
                    season=int(episode.get("season")),
                    number=int(episode.get("number")),
                    name=episode.get("name"),
                    year=None,
                    data=[x["path"] for x in episode["stitched"]["paths"]],
                )
                for series in data["seasons"]
                for episode in series["episodes"]
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)

        return Movies(
            [
                Movie(
                    id_=movie["_id"],
                    service="PLUTO",
                    title=movie["name"],
                    year=movie["slug"].split("-")[-3],  # TODO
                    name=movie["name"],
                    data=[x["path"] for x in movie["stitched"]["paths"]],
                )
                for movie in data
            ]
        )

    def get_dash(self, stitch: str):
        base = "https://cfd-v4-service-stitcher-dash-use1-1.prd.pluto.tv/v2"

        url = f"{base}{stitch}"
        r = self.client.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "xml")
        base_urls = soup.find_all("BaseURL")
        ads = (
            "Pluto_TV_OandO",
            "_ad/",
            "/creative/",
            "Bumper",
            "Promo/",
            "WarningCard",
        )
        for base_url in base_urls:
            if not any(ad in base_url.text for ad in ads):
                new_base = base_url.text

        parse = urlparse(new_base)
        _path = parse.path.split("/")
        _path = "/".join(_path[:-3]) if new_base.endswith("end/") else "/".join(_path)
        new_path = (
            f"{_path}/dash/0-end/main.mpd"
            if new_base.endswith("end/")
            else f"{_path}main.mpd"
        )

        return parse._replace(
            scheme="http",
            netloc="silo-hybrik.pluto.tv.s3.amazonaws.com",
            path=f"{new_path}",
        ).geturl()

    def get_hls(self, stitch: str):
        base = "https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv"

        url = f"{base}{stitch}"
        response = self.client.get(url).text

        pattern = r"#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=(\d+)"
        matches = re.findall(pattern, response)

        max_bandwidth = sorted(matches, key=int, reverse=True)
        url = url.replace("master.m3u8", f"{max_bandwidth[0]}/playlist.m3u8")

        response = self.client.get(url).text
        playlist = m3u8.loads(response)
        ads = (
            "Pluto_TV_OandO",
            "_ad/",
            "/creative/",
            "Bumper",
            "Promo/",
            "WarningCard",
        )
        for seg in playlist.segments:
            if not any(ad in seg.uri for ad in ads):
                segment = seg.uri

        if "hls/hls" in segment:
            master = re.sub(r"hls_\d+-\d+\.ts$", "", segment)
            master += "master.m3u8"
        else:
            master = segment.split("hls/")[0]
            master += "hls/0-end/master.m3u8"

        parse = urlparse(master)
        master = parse._replace(
            scheme="http",
            netloc="silo-hybrik.pluto.tv.s3.amazonaws.com",
        ).geturl()

        # TODO: Determine DRM without extra request
        response = requests.get(master).text
        if re.search(r'#PLUTO-DRM:ID="fairplay"', response):
            self.base_url = master.rsplit("master.m3u8")[0]
            manifest = self.create_manifest(response, master.rsplit("master.m3u8")[0])
            with open(self.tmp / "manifest.m3u8", "w") as f:
                f.write(manifest)

            master = Path(self.tmp / "manifest.m3u8")

        return master

    def create_manifest(self, text, url) -> str:
        lines = text.split("\n")
        for i in range(len(lines)):
            lines[i] = lines[i].replace("fp/", "")

            if "hls_" in lines[i]:
                lines[i] = url + lines[i]

        text = "\n".join(lines)
        return text

    def get_playlist(self, playlists: str) -> Path | str:
        hls = next((x for x in playlists if x.endswith(".m3u8")), None)
        dash = next((x for x in playlists if x.endswith(".mpd")), None)

        if not hls and not dash:
            self.log.error("Unable to find manifest")
            sys.exit(1)

        if hls:
            manifest = self.get_hls(hls)
        elif dash:
            manifest = self.get_dash(dash)

        return manifest

    def get_dash_quality(self, soup: object, quality: str) -> str:
        elements = soup.find_all("Representation")
        heights = sorted(
            [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
            reverse=True,
        )

        # 720p on Pluto is in the adaptationset rather than representation
        adaptation_sets = soup.find_all("AdaptationSet")
        for item in adaptation_sets:
            if item.attrs.get("height"):
                heights.append(int(item.attrs["height"]))
                heights.sort(reverse=True)

        if quality is not None:
            if int(quality) in heights:
                return quality
            else:
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                return closest_match

        return heights[0]

    def get_hls_quality(self, manifest, quality: str) -> str:
        self.client.headers.pop("Authorization")
        if is_path(manifest):
            m3u8_obj = m3u8.load(str(manifest))
        else:
            r = self.client.get(manifest)
            r.raise_for_status()
            m3u8_obj = m3u8.loads(r.text)

        playlists = []
        if m3u8_obj.is_variant:
            for playlist in m3u8_obj.playlists:
                playlists.append((playlist.stream_info.resolution[1], playlist.uri))

            heights = sorted([x[0] for x in playlists], reverse=True)
            res = heights[0]

        if quality is not None:
            for playlist in playlists:
                if int(quality) in playlist:
                    res = playlist[0]
                else:
                    res = min(heights, key=lambda x: abs(int(x) - int(quality)))

        return res

    def generate_pssh(self, kid: str):
        array_of_bytes = bytearray(b"\x00\x00\x002pssh\x00\x00\x00\x00")
        array_of_bytes.extend(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
        array_of_bytes.extend(b"\x00\x00\x00\x12\x12\x10")
        array_of_bytes.extend(bytes.fromhex(kid.replace("-", "")))
        return base64.b64encode(bytes.fromhex(array_of_bytes.hex())).decode("utf-8")

    def get_pssh(self, soup) -> str:
        tags = soup.find_all("ContentProtection")
        kids = set(
            [
                x.attrs.get("cenc:default_KID").replace("-", "")
                for x in tags
                if x.attrs.get("cenc:default_KID")
            ]
        )

        return [self.generate_pssh(kid) for kid in kids]

    def get_mediainfo(self, manifest: str, quality: str, pssh=None) -> str:
        if is_path(manifest) or manifest.endswith(".m3u8"):
            quality = self.get_hls_quality(manifest, quality)
            return quality, pssh

        elif manifest.endswith(".mpd"):
            self.client.headers.pop("Authorization")
            r = self.client.get(manifest)
            r.raise_for_status()
            self.soup = BeautifulSoup(r.content, "xml")
            pssh = self.get_pssh(self.soup)
            quality = self.get_dash_quality(self.soup, quality)
            return quality, pssh

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

    def get_options(self) -> None:
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
        manifest = self.get_playlist(stream.data)
        self.res, pssh = self.get_mediainfo(manifest, self.quality)
        self.client.headers.update({"Authorization": f"Bearer {self.token}"})

        keys = None
        if pssh is not None:
            keys = [self.get_keys(key, self.lic_url) for key in pssh]
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(key[0] for key in keys))

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt" if keys else None
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
            self.log.warning(f"{self.filename} already exists. Skipping download...\n")
            self.sub_path.unlink() if self.sub_path else None

        if not self.skip_download and file_path.exists():
            update_cache(self.cache, self.config, stream)
