"""
Thanks to A_n_g_e_l_a for the cookies!

ITV
Author: stabbedbybrick

Info:
ITV L3 is 720p, AAC 2.0 max

"""
from __future__ import annotations

import base64
import subprocess
import json
import shutil
import sys

from collections import Counter
from pathlib import Path

import click
import requests
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
    add_subtitles,
    get_wvd,
)
from utils.titles import Episode, Series, Movie, Movies
from utils.options import Options
from utils.args import get_args
from utils.config import Config
from utils.cdm import LocalCDM


class ITV(Config):
    def __init__(self, config, srvc_api, srvc_config, **kwargs):
        super().__init__(config, srvc_api, srvc_config, **kwargs)

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
        with self.console.status("Getting decryption keys..."):
            wvd = get_wvd(Path.cwd())
            widevine = LocalCDM(wvd)
            challenge = widevine.challenge(pssh)
            response = self.get_license(challenge, lic_url)
            return widevine.parse(response)

    def get_data(self, url: str) -> dict:
        soup = BeautifulSoup(self.client.get(url), "html.parser")
        props = soup.select_one("#__NEXT_DATA__").text
        data = json.loads(props)
        return data["props"]["pageProps"]

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)

        return Series(
            [
                Episode(
                    id_=None,
                    service="ITV",
                    title=data["programme"]["title"],
                    season=episode.get("series") or 0,
                    number=episode.get("episode") or 0,
                    name=episode["episodeTitle"],
                    year=None,
                    data=episode["playlistUrl"],
                    description=episode.get("description"),
                )
                for series in data["seriesList"]
                if "Latest episodes" not in series["seriesLabel"]
                for episode in series["titles"]
            ]
        )

    def get_movies(self, url: str) -> Movies:
        data = self.get_data(url)

        return Movies(
            [
                Movie(
                    id_=None,
                    service="ITV",
                    title=data["programme"]["title"],
                    year=movie.get("productionYear"),
                    name=data["programme"]["title"],
                    data=movie["playlistUrl"],
                    synopsis=movie.get("description"),
                )
                for movies in data["seriesList"]
                for movie in movies["titles"]
            ]
        )

    def get_playlist(self, playlist: str) -> tuple:
        featureset = {
            k: ("mpeg-dash", "widevine", "outband-webvtt", "hd", "single-track")
            for k in ("min", "max")
        }
        payload = {
            "client": {"id": "browser"},
            "variantAvailability": {"featureset": featureset, "platformTag": "dotcom"},
        }

        r = self.client.post(playlist, json=payload)
        if not r.is_success:
            click.echo(f"\n\nError! {r.status_code}\n{r.content}")
            shutil.rmtree(self.tmp)
            sys.exit(1)

        data = r.json()

        video = data["Playlist"]["Video"]
        media = video["MediaFiles"]
        mpd_url = f"{video.get('Base')}{media[0].get('Href')}"
        lic_url = f"{media[0].get('KeyServiceUrl')}"
        subtitle = video.get("Subtitles")
        subtitle = f"{subtitle[0].get('Href')}" if subtitle else None

        return mpd_url, lic_url, subtitle

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

    def get_mediainfo(self, manifest: str, quality: str, subtitle: str) -> str:
        r = requests.get(manifest)
        if not r.ok:
            click.echo(f"\n\nError! {r.status_code}\n{r.content}")
            sys.exit(1)

        self.soup = BeautifulSoup(r.content, "xml")
        pssh = self.get_pssh(self.soup)
        elements = self.soup.find_all("Representation")
        heights = sorted(
            [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
            reverse=True,
        )

        new_base, params = manifest.split(".mpd")
        new_base += "dash/"
        self.soup.select_one("BaseURL").string = new_base

        segments = self.soup.find_all("SegmentTemplate")
        for segment in segments:
            segment["media"] += params
            segment["initialization"] += params

        if subtitle is not None:
            self.soup = add_subtitles(self.soup, subtitle)

        with open(self.tmp / "manifest.mpd", "w") as f:
            f.write(str(self.soup.prettify()))

        if quality is not None:
            if int(quality) in heights:
                return quality, pssh
            else:
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
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
        data = self.get_data(url)

        episode = Series(
            [
                Episode(
                    id_=None,
                    service="ITV",
                    title=data["programme"]["title"],
                    season=data["episode"].get("series") or 0,
                    number=data["episode"].get("episode") or 0,
                    name=data["episode"]["episodeTitle"],
                    year=None,
                    data=data["episode"]["playlistUrl"],
                    description=data["episode"].get("description"),
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
            manifest, lic_url, subtitle = self.get_playlist(stream.data)
            self.res, pssh = self.get_mediainfo(manifest, self.quality, subtitle)

        keys = self.get_keys(pssh, lic_url)
        with open(self.tmp / "keys.txt", "w") as file:
            file.write("\n".join(keys))

        if self.info:
            print_info(self, stream, keys)

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self.config, title)
        self.manifest = self.tmp / "manifest.mpd"
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