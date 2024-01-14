"""
Credit to rlaphoenix for the title storage

TubiTV
Author: stabbedbybrick

Info:
TubiTV WEB is 720p max


"""
from __future__ import annotations

import json
import re
import subprocess
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import click
import m3u8

from utils.args import get_args
from utils.cdm import LocalCDM
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    force_numbering,
    get_wvd,
    in_cache,
    pssh_from_init,
    set_filename,
    set_save_path,
    string_cleaning,
    update_cache,
)

MAX_VIDEO = "720"
MAX_AUDIO = "AAC2.0"


class TUBITV(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        with self.config["download_cache"].open("r") as file:
            self.cache = json.load(file)

        if self.quality is None:
            self.quality = MAX_VIDEO

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
        type = urlparse(url).path.split("/")[1]
        video_id = urlparse(url).path.split("/")[2]

        content_id = f"0{video_id}" if type == "series" else video_id

        content = self.config["content"].format(content_id=content_id)

        r = self.client.get(f"{content}")
        r.raise_for_status()

        return r.json()

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
                    id_=episode["id"],
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
                    id_=data["id"],
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

    def get_init(self, mpd: str) -> str:
        r = self.client.get(mpd)
        url = re.search('#EXT-X-MAP:URI="(.*?)"', r.text).group(1)

        headers = {"Range": "bytes=0-9999"}

        response = self.client.get(url, headers=headers)
        with open(self.tmp / "init.mp4", "wb") as f:
            f.write(response.content)

        return pssh_from_init(Path(self.tmp / "init.mp4"))

    def get_mediainfo(self, manifest: str, quality: str, res=""):
        r = self.client.get(manifest)
        r.raise_for_status()

        url = urlparse(manifest)
        base = f"{url.scheme}://{url.netloc}/{url.path.split('/')[1]}/"

        m3u8_obj = m3u8.loads(r.text)

        playlists = []
        if m3u8_obj.is_variant:
            for playlist in m3u8_obj.playlists:
                playlists.append((playlist.stream_info.resolution[1], playlist.uri))

            heights = sorted([x[0] for x in playlists], reverse=True)
            manifest = [base + x[1] for x in playlists if heights[0] == x[0]][0]

        for playlist in playlists:
            if int(quality) in heights:
                resolution = quality
                manifest = base + playlist[1]
            else:
                self.log.error(
                    "Video quality unavailable. Please select another resolution"
                )
                resolution = None
                self.skip_download = True

        return manifest, resolution

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

    def get_episode_from_url(self, url: str):
        with self.console.status("Getting episode from URL..."):
            episode_id = urlparse(url).path.split("/")[2]

            content = (
                f"https://tubitv.com/oz/videos/{episode_id}/content?"
                f"video_resources=hlsv6_widevine_nonclearlead&video_resources=hlsv6"
            )

            series_id = self.client.get(content).json()["series_id"]
            content = re.sub(rf"{episode_id}", f"{series_id}", content)

            data = self.client.get(content).json()

            episode = Series(
                [
                    Episode(
                        id_=episode["id"],
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
                    if episode["id"] == episode_id
                ]
            )

        title = string_cleaning(str(episode))

        return [episode[0]], title

    def get_options(self) -> None:
        downloads, title = get_downloads(self)

        for download in downloads:
            if in_cache(self.cache, self.quality, download):
                continue

            if self.slowdown:
                with self.console.status(
                    f"Slowing things down for {self.slowdown} seconds..."
                ):
                    time.sleep(self.slowdown)

            self.download(download, title)

    def download(self, stream: object, title: str) -> None:
        manifest, self.res = self.get_mediainfo(stream.data, self.quality)

        keys = None
        if stream.lic_url:
            pssh = self.get_init(manifest)
            keys = self.get_keys(pssh, stream.lic_url)
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio=MAX_AUDIO)
        self.save_path = set_save_path(stream, self, title)
        self.manifest = stream.data
        self.key_file = self.tmp / "keys.txt" if keys else None
        self.sub_path = None

        if stream.subtitle is not None:
            self.sub_path = self.tmp / f"{self.filename}.srt"
            r = self.client.get(url=f"{stream.subtitle}")
            with open(self.sub_path, "wb") as f:
                f.write(r.content)

        self.log.info(f"{str(stream)}")
        self.log.info(f"{keys[0]}") if keys else None
        click.echo("")

        try:
            subprocess.run(get_args(self), check=True)
        except Exception as e:
            self.sub_path.unlink() if self.sub_path else None
            raise ValueError(f"{e}")

        if not self.skip_download:
            update_cache(self.cache, self.config, self.res, stream.id)
