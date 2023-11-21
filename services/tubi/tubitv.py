"""
Credit to rlaphoenix for the title storage

TubiTV
Author: stabbedbybrick

Info:
TubiTV WEB is 720p max
Some titles are encrypted, some are not. Both versions are supported


"""
from __future__ import annotations

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
import yaml
import m3u8

from utils.utilities import (
    info,
    error,
    is_url,
    string_cleaning,
    set_save_path,
    # print_info,
    set_filename,
    get_wvd,
)
from utils.titles import Episode, Series, Movie, Movies
from utils.options import Options
from utils.args import get_args
from utils.config import Config
from utils.cdm import LocalCDM


class TUBITV(Config):
    def __init__(self, config, srvc_api, srvc_config, **kwargs):
        super().__init__(config, srvc_api, srvc_config, **kwargs)

        if self.info:
            info("Info feature is not yet supported on this service")
            exit(1)

        with open(self.srvc_api, "r") as f:
            self.config.update(yaml.safe_load(f))

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
        type = urlparse(url).path.split("/")[1]
        video_id = urlparse(url).path.split("/")[2]

        content_id = f"0{video_id}" if type == "series" else video_id

        content = self.config["content"].format(content_id=content_id)

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
    

    def get_mediainfo(self, manifest: str, quality: str, res=""):
        r = self.client.get(manifest)
        if not r.is_success:
            error(f"Unable to fetch manifest: {r.response_code}")
            exit(1)

        url = urlparse(manifest)
        base = f"{url.scheme}://{url.netloc}/{url.path.split('/')[1]}/"

        m3u8_obj = m3u8.loads(r.text)

        playlists = []
        if m3u8_obj.is_variant:
            for playlist in m3u8_obj.playlists:
                playlists.append((playlist.stream_info.resolution[1], playlist.uri))

            heights = sorted([x[0] for x in playlists], reverse=True)
            manifest = [base + x[1] for x in playlists if heights[0] == x[0]][0]
            res = heights[0]
        
        if quality is not None:
            for playlist in playlists:
                if int(quality) in playlist:
                    res = playlist[0]
                    manifest = base + playlist[1]
                else:
                    res = min(heights, key=lambda x: abs(int(x) - int(quality)))
                    if res == playlist[0]:
                        manifest = base + playlist[1]

        return manifest, res
        

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
        with self.console.status("Fetching title..."):
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
            manifest, self.res = self.get_mediainfo(stream.data, self.quality)

        keys = None
        if stream.lic_url:
            pssh = self.get_pssh(manifest)
            keys = self.get_keys(pssh, stream.lic_url)
            with open(self.tmp / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
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