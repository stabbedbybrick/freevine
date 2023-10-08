"""
Credit to rlaphoenix for the title storage

PlutoTV
Author: stabbedbybrick

Info:
This program will download ad-free streams with highest available quality and subtitles
Quality: 720p, AAC 2.0 max
Some titles are encrypted, some are not. Both versions are supported

Notes:
While functional, it's still considered in beta
Labeling for resolution is currently missing
Pluto's library is very spotty, so it's highly recommended to use --titles before downloading

"""

import base64
import re
import subprocess
import uuid

from urllib.parse import urlparse
from collections import Counter

import click

from bs4 import BeautifulSoup

from helpers.utilities import (
    info,
    string_cleaning,
    set_save_path,
    # print_info,
    set_filename,
)
from helpers.cdm import local_cdm, remote_cdm
from helpers.titles import Episode, Series, Movie, Movies
from helpers.args import Options, get_args
from helpers.config import Config


class PLUTO(Config):
    def __init__(self, config, srvc, **kwargs):
        super().__init__(config, srvc, **kwargs)

        if self.info:
            info("Info feature is not yet supported on this service")
            exit(1)

        self.lic_url = self.srvc["pluto"]["lic"]
        self.api = self.srvc["pluto"]["api"]

        self.get_options()

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

        response = self.client.get(
            "https://boot.pluto.tv/v4/start", params=params
        ).json()

        self.token = response["sessionToken"]

        info = (
            f"{self.api}/series/{video_id}/seasons"
            if type == "series"
            else f"{self.api}/items?ids={video_id}"
        )
        self.client.headers.update({"Authorization": f"Bearer {self.token}"})
        self.client.params = params

        return self.client.get(info).json()

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
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
        soup = BeautifulSoup(self.client.get(url), "xml")
        base_urls = soup.find_all("BaseURL")
        for base_url in base_urls:
            if base_url.text.endswith("end/"):
                new_base = base_url.text

        parse = urlparse(new_base)
        _path = parse.path.split("/")
        _path = "/".join(_path[:-3])
        new_path = f"{_path}/dash/0-end/main.mpd"

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
        segment = re.search(
            r"^(https?://.*/)0\-(end|[0-9]+)/[^/]+\.ts$", response, re.MULTILINE
        ).group(1)

        parse = urlparse(f"{segment}0-end/master.m3u8")

        master = parse._replace(
            scheme="http",
            netloc="silo-hybrik.pluto.tv.s3.amazonaws.com",
        ).geturl()

        self.client.headers.pop("Authorization")
        response = self.client.get(master).text

        matches = re.findall(r"hls_(\d+).m3u8", response)
        hls = sorted(matches, key=int, reverse=True)[0]

        manifest = master.replace("master.m3u8", f"hls_{hls}.m3u8")
        return manifest

    def get_playlist(self, playlists: str) -> tuple:
        stitched = next((x for x in playlists if x.endswith(".mpd")), None)
        if not stitched:
            stitched = next((x for x in playlists if x.endswith(".m3u8")), None)

        if stitched.endswith(".mpd"):
            return self.get_dash(stitched)

        if stitched.endswith(".m3u8"):
            return self.get_hls(stitched)

    def generate_pssh(self, kid: str):
        array_of_bytes = bytearray(b"\x00\x00\x002pssh\x00\x00\x00\x00")
        array_of_bytes.extend(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
        array_of_bytes.extend(b"\x00\x00\x00\x12\x12\x10")
        array_of_bytes.extend(bytes.fromhex(kid.replace("-", "")))
        return base64.b64encode(bytes.fromhex(array_of_bytes.hex())).decode("utf-8")

    def get_pssh(self, manifest: str) -> str:
        self.client.headers.pop("Authorization")
        soup = BeautifulSoup(self.client.get(manifest), "xml")
        tags = soup.find_all("ContentProtection")
        kids = set(
            [
                x.attrs.get("cenc:default_KID").replace("-", "")
                for x in tags
                if x.attrs.get("cenc:default_KID")
            ]
        )

        return [self.generate_pssh(kid) for kid in kids]

    def get_mediainfo(self, manifest: str) -> str:
        return self.get_pssh(manifest) if manifest.endswith(".mpd") else None

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

        for download in downloads:
            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        with self.console.status("Getting media info..."):
            manifest = self.get_playlist(stream.data)
            pssh = self.get_mediainfo(manifest)
            self.client.headers.update({"Authorization": f"Bearer {self.token}"})
        
        keys = None
        if pssh is not None:
            with self.console.status("Getting decryption keys..."):
                keys = [
                    remote_cdm(key, self.lic_url, self.client)
                    if self.remote
                    else local_cdm(key, self.lic_url, self.client)
                    for key in pssh
                ]
                with open(self.tmp / "keys.txt", "w") as file:
                    file.write("\n".join(key[0] for key in keys))

        self.filename = set_filename(self, stream, res=None, audio="AAC2.0")
        self.save_path = set_save_path(stream, self.config, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt" if pssh else None
        self.sub_path = None

        info(f"{str(stream)}")
        click.echo("")

        args, file_path = get_args(self, res="")

        if not file_path.exists():
            try:
                subprocess.run(args, check=True)
            except:
                raise ValueError("Download failed or was interrupted")
        else:
            info(f"{self.filename} already exist. Skipping download\n")
            self.sub_path.unlink() if self.sub_path else None
            pass