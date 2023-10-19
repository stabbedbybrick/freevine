"""
Credit to Diazole and rlaphoenix for paving the way

Author: stabbedbybrick

Info:
This program will grab higher 1080p bitrate (if available)

"""

import base64
import re
import subprocess
import json
import shutil
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
    string_cleaning,
    set_save_path,
    print_info,
    set_filename,
)
from utils.titles import Episode, Series, Movie, Movies
from utils.args import Options, get_args
from utils.config import Config

from pywidevine.L3.decrypt.wvdecryptcustom import WvDecrypt
from pywidevine.L3.cdm import deviceconfig


class CHANNEL4(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        with open(Path("services") / "config" / "channel4.yaml", "r") as f:
            self.cfg = yaml.safe_load(f)
         
        self.config.update(self.cfg)
        self.get_options()

    def local_cdm(
        self,
        pssh: str,
        lic_url: str,
        manifest: str,
        token: str,
        asset: str,
        cert_b64=None,
    ) -> str:
        wvdecrypt = WvDecrypt(
            init_data_b64=pssh,
            cert_data_b64=cert_b64,
            device=deviceconfig.device_android_generic,
        )
        lic = self.get_license(
            wvdecrypt.get_challenge(), lic_url, manifest, token, asset
        )

        wvdecrypt.update_license(lic)
        status, content = wvdecrypt.start_process()

        if status:
            return content
        else:
            raise ValueError("Unable to fetch decryption keys")

    def get_license(
        self,
        challenge: bytes,
        lic_url: str,
        manifest: str,
        token: str,
        asset: str,
    ) -> str:
        r = self.client.post(
            lic_url,
            data=json.dumps(
                {
                    "message": base64.b64encode(challenge).decode("utf8"),
                    "token": token,
                    "request_id": asset,
                    "video": {"type": "ondemand", "url": manifest},
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        if r.status_code != 200:
            click.echo(f"Failed to get license! Error: {r.json()['status']['type']}")
            sys.exit(1)
        return r.json()["license"]

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
                    id_=None,
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

    def get_playlist(self, asset_id: str, episode_id: str) -> tuple:
        if self.config["client"] == "android":
            url = self.config["android"]["vod"].format(asset_id=asset_id)

            r = self.client.get(url)
            if not r.is_success:
                shutil.rmtree(self.tmp)
                raise ValueError("Invalid assetID")

            soup = BeautifulSoup(r.text, "xml")
            token = soup.select_one("token").text
            manifest = soup.select_one("uri").text

        else:
            url = self.config["web"]["vod"].format(programmeId=episode_id)

            r = self.client.get(url)
            if not r.is_success:
                shutil.rmtree(self.tmp)
                raise ValueError("Invalid programmeId")
            
            data = json.loads(r.content)

            for item in data["videoProfiles"]:
                if item["name"] == "dashwv-dyn-stream-1":
                    token = item["streams"][0]["token"]
                    manifest = item["streams"][0]["uri"]
        
        return manifest, token

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

    def get_mediainfo(self, manifest: str, quality: str) -> str:
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
                info(f"Resolution not available. Getting closest match:")
                return closest_match, pssh

        return heights[0], pssh

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
                    description=brand["selectedEpisode"].get("summary")
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
            downloads, title = self.get_episode_from_url(self.url)

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

        for download in downloads:
            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        with self.console.status("Getting media info..."):
            manifest, token = self.get_playlist(stream.data, stream.id)
            res, pssh = self.get_mediainfo(manifest, self.quality)
            token, license_url = self.decrypt_token(token)

        with self.console.status("Getting decryption keys..."):
            keys = self.local_cdm(pssh, license_url, manifest, token, stream.data)
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        if self.info:
            print_info(self, stream, keys)

        self.filename = set_filename(self, stream, res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self.config, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        info(f"{str(stream)}")
        info(f"{keys[0]}")
        click.echo("")

        args, file_path = get_args(self, res)

        if not file_path.exists():
            try:
                subprocess.run(args, check=True)
            except:
                raise ValueError("Download failed or was interrupted")
        else:
            info(f"{self.filename} already exist. Skipping download\n")
            self.sub_path.unlink() if self.sub_path else None
            pass
