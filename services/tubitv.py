"""
Credit to rlaphoenix for the title storage

TubiTV
Author: stabbedbybrick

Info:
TubiTV WEB is 720p max
Some titles are encrypted, some are not. Both versions are supported


"""

import base64
import re
import subprocess
import json
import shutil
import sys

from urllib.parse import urlparse
from pathlib import Path
from collections import Counter

import click


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


class TUBITV(Config):
    def __init__(self, config, srvc, **kwargs):
        super().__init__(config, srvc, **kwargs)

        if self.info:
            info("Info feature is not yet supported on this service")
            exit(1)

        self.get_options()

    def get_data(self, url: str) -> json:
        type = urlparse(url).path.split("/")[1]
        video_id = urlparse(url).path.split("/")[2]

        content_id = f"0{video_id}" if type == "series" else video_id

        content = (
            f"https://tubitv.com/oz/videos/{content_id}/content?"
            f"video_resources=hlsv6_widevine_nonclearlead&video_resources=hlsv6"
        )

        r = self.client.get(f"{content}")
        if not r.is_success:
            print(f"\nError! {r.status_code}")
            shutil.rmtree(self.tmp)
            sys.exit(1)

        return r.json()

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
                    service="TUBi",
                    title=data["title"],
                    season=int(season["id"]),
                    number=int(episode["episode_number"]),
                    name=episode["title"].split("-")[1],
                    year=data["year"],
                    data=episode["video_resources"][0]["manifest"]["url"],
                    subtitle=episode.get("subtitles")[0].get("url")
                    if episode.get("subtitles")
                    else None,
                    lic_url=episode["video_resources"][0]["license_server"]["url"]
                    if episode["video_resources"][0].get("license_server")
                    else None,
                )
                for season in data["children"]
                for episode in season["children"]
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)

        return Movies(
            [
                Movie(
                    service="TUBi",
                    title=data["title"],
                    year=data["year"],
                    name=data["title"],
                    data=data["video_resources"][0]["manifest"]["url"],
                    subtitle=data.get("subtitles")[0].get("url")
                    if data.get("subtitles")
                    else None,
                    lic_url=data["video_resources"][0]["license_server"]["url"]
                    if data["video_resources"][0].get("license_server")
                    else None,
                )
            ]
        )

    def get_pssh(self, mpd: str) -> str:
        r = self.client.get(mpd)
        url = re.search('#EXT-X-MAP:URI="(.*?)"', r.text).group(1)

        headers = {"Range": "bytes=0-9999"}

        response = self.client.get(url, headers=headers)
        with open(self.tmp / "init.mp4", "wb") as f:
            f.write(response.read())

        raw = Path(self.tmp / "init.mp4").read_bytes()
        wv = raw.rfind(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
        if wv == -1:
            return None
        return base64.b64encode(raw[wv - 12 : wv - 12 + raw[wv - 9]]).decode("utf-8")

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        m3u8 = self.client.get(manifest).text
        url = urlparse(manifest)
        base = f"https://{url.netloc}/{url.path.split('/')[1]}"

        lines = m3u8.split("\n")
        playlist = [
            (re.search("RESOLUTION=([0-9x]+)", line).group(1), lines[i + 1])
            for i, line in enumerate(lines)
            if line.startswith("#EXT-X-STREAM-INF:")
            and re.search("RESOLUTION=([0-9x]+)", line)
        ]

        playlist.sort(key=lambda x: int(x[0].split("x")[1]), reverse=True)

        if quality is not None:
            for resolution, m3u8_link in playlist:
                if quality in resolution:
                    mpd = f"{base}/{m3u8_link}"
                    return mpd, quality

        mpd = f"{base}/{playlist[0][1]}"

        return mpd, playlist[0][0].split("x")[1]

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
            manifest, res = self.get_mediainfo(stream.data, self.quality)

        keys = None
        if stream.lic_url:
            with self.console.status("Getting decryption keys..."):
                pssh = self.get_pssh(manifest)
                keys = (
                    remote_cdm(pssh, stream.lic_url, self.client)
                    if self.remote
                    else local_cdm(pssh, stream.lic_url, self.client)
                )
                with open(self.tmp / "keys.txt", "w") as file:
                    file.write("\n".join(keys))

        self.filename = set_filename(self, stream, res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self.config, title)
        self.manifest = stream.data
        self.key_file = self.tmp / "keys.txt" if stream.lic_url else None
        self.sub_path = None

        if stream.subtitle is not None:
            self.sub_path = self.save_path / f"{self.filename}.srt"
            r = self.client.get(url=f"{stream.subtitle}")
            with open(self.sub_path, "wb") as f:
                f.write(r.content)

        info(f"{str(stream)}")
        info(f"{keys[0]}") if stream.lic_url else None
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