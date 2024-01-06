"""
Plex
Author: stabbedbybrick

Info:
Quality: up to 1080p, AAC 2.0
Some titles are encrypted, some are not. Both versions are supported


"""
from __future__ import annotations

import base64
import re
import subprocess
import uuid
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import click
import m3u8
from bs4 import BeautifulSoup

from utils.args import get_args
from utils.cdm import LocalCDM
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    get_wvd,
    set_filename,
    set_save_path,
    string_cleaning,
    force_numbering,
)


class Plex(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        self.lic_url = self.config["license"]

        self.client.headers.update(
            {
                "accept": "application/json",
                "x-plex-client-identifier": "490b079e-2dbf-4212-bf51-2aabaa54191f",
                "x-plex-language": "en",
                "x-plex-product": "Plex Mediaverse",
                "x-plex-provider-version": "6.5.0",
            }
        )

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

    def get_auth_token(self) -> str:
        r = self.client.post(self.config["user"])
        if not r.ok:
            raise ConnectionError(r.json()["Error"].get("message"))

        return r.json()["authToken"]

    def get_data(self, url: str) -> dict:
        kind = urlparse(url).path.split("/")[1]
        video_id = urlparse(url).path.split("/")[2]

        auth_token = self.get_auth_token()

        self.client.headers.update({"x-plex-token": auth_token})
        params = {
            "uri": self.config["provider"].format(path=f"{kind}:{video_id}"),
            "type": "video",
            "continuous": "1",
        }
        r = self.client.post(self.config["vod"], params=params)
        if not r.ok:
            raise ConnectionError(r.json()["Error"].get("message"))

        return r.json()["MediaContainer"]["Metadata"]

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
                    service="PLEX",
                    title=episode["grandparentTitle"].split()[0],
                    season=int(episode.get("parentIndex", 0)),
                    number=int(episode.get("index", 0)),
                    name=episode.get("title"),
                    year=episode.get("year"),
                    data=None,
                )
                for episode in data
                if episode["type"] == "episode"
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)

        return Movies(
            [
                Movie(
                    service="PLEX",
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
        ads = ("_ad", "Bumper", "Promo")
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
        segment = playlist.segments[0].uri

        if "hls/hls" in segment:
            master = re.sub(r"hls_\d+-\d+\.ts$", "", segment)
            master += "master.m3u8"
        else:
            master = segment.split("hls/")[0]
            master += "hls/0-end/master.m3u8"

        parse = urlparse(master)
        return parse._replace(
            scheme="http",
            netloc="silo-hybrik.pluto.tv.s3.amazonaws.com",
        ).geturl()

    def get_playlist(self, playlists: str) -> tuple:
        stitched = next((x for x in playlists if x.endswith(".mpd")), None)
        if not stitched:
            stitched = next((x for x in playlists if x.endswith(".m3u8")), None)

        if stitched.endswith(".mpd"):
            return self.get_dash(stitched)

        if stitched.endswith(".m3u8"):
            return self.get_hls(stitched)

        if not stitched:
            self.log.error("Unable to find manifest")
            return

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

    def get_hls_quality(self, manifest: str, quality: str) -> str:
        self.client.headers.pop("Authorization")
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

        return res, manifest

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

    def get_mediainfo(self, manifest: str, quality: str, pssh=None, hls=None) -> str:
        if manifest.endswith(".mpd"):
            self.client.headers.pop("Authorization")
            r = self.client.get(manifest)
            r.raise_for_status()
            self.soup = BeautifulSoup(r.content, "xml")
            pssh = self.get_pssh(self.soup)
            quality = self.get_dash_quality(self.soup, quality)
            return quality, pssh, hls

        if manifest.endswith(".m3u8"):
            quality, hls = self.get_hls_quality(manifest, quality)
            self.playlist = True
            return quality, pssh, hls

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
            manifest = self.get_playlist(stream.data)
            self.res, pssh, hls = self.get_mediainfo(manifest, self.quality)
            self.client.headers.update({"Authorization": f"Bearer {self.token}"})

        keys = None
        if pssh is not None:
            keys = [self.get_keys(key, self.lic_url) for key in pssh]
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(key[0] for key in keys))

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self, title)
        self.manifest = hls if hls else manifest
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
            self.log.info(f"{self.filename} already exist. Skipping download\n")
            self.sub_path.unlink() if self.sub_path else None
            pass
