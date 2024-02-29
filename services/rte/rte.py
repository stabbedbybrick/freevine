"""
RTE Player
Author: stabbedbybrick

Info:
1080p, AAC 2.0

"""
from __future__ import annotations

import json
import subprocess
import time
import re
import base64
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import click

from utils.args import get_args
from utils.cdm import LocalCDM
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    append_id,
    kid_to_pssh,
    force_numbering,
    get_heights,
    get_wvd,
    in_cache,
    set_filename,
    set_save_path,
    string_cleaning,
    update_cache,
    load_xml,
)


class RTE(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        with self.config["download_cache"].open("r") as file:
            self.cache = json.load(file)

        self.base = self.config["base"]

        self.get_options()

    def get_license(self, challenge: bytes, token: str, account: str, pid: str) -> json:
        params = {
            "token": token,
            "account": account,
            "form": "json",
            "schema": "1.0",
        }
        payload = {
            "getWidevineLicense": {
                "releasePid": pid,
                "widevineChallenge": challenge,
            }
        }
        r = self.client.post(url=self.config["license"], params=params, json=payload)
        r.raise_for_status()
        return r.json()

    def get_keys(self, pssh: str, token: str, account: str, pid: str):
        wvd = get_wvd(Path.cwd())
        widevine = LocalCDM(wvd)
        challenge = base64.b64encode(widevine.challenge(pssh)).decode("utf-8")
        response = self.get_license(challenge, token, account, pid)
        message = response["getWidevineLicenseResponse"]["license"]
        return widevine.parse(message)

    def parse_url(self, url: str, ep_guid: str = None) -> tuple:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        series_guid = parsed.path.split("/")[-1]
        ep_guid = params.get("epguid", [None])[0]

        return series_guid, ep_guid

    def get_data(self, series_guid: str = None, movie_guid: str = None) -> dict:
        if movie_guid:
            r = self.client.get(
                f"{self.base}/rte-prd-prd-all-programs?count=true&entries=true&byId={movie_guid}"
            )
            if not r.ok:
                raise ConnectionError(r.text)
        
        else:
            r = self.client.get(
                f"{self.base}/rte-prd-prd-all-movies-series?byGuid={series_guid}"
            )
            if not r.ok:
                raise ConnectionError(r.text)

            id = r.json()["entries"][0]["id"]
            series_id = urlparse(id).path.split("/")[-1]

            r = self.client.get(
                f"{self.base}/rte-prd-prd-all-programs?bySeriesId={series_id}"
            )
            if not r.ok:
                raise ConnectionError(r.text)

        return r.json()["entries"]

    def get_series(self, url: str) -> Series:
        series_guid, _ = self.parse_url(url)
        data: list = self.get_data(series_guid)

        return Series(
            [
                Episode(
                    id_=episode["guid"],
                    service="RTE",
                    title=episode["plprogram$longTitle"],
                    season=episode.get("plprogram$tvSeasonNumber") or 0,
                    number=episode.get("plprogram$tvSeasonEpisodeNumber") or 0,
                    name=episode.get("description"),
                    year=episode.get("plprogram$year"),
                    data=episode["plprogramavailability$media"][0]["plmedia$publicUrl"],
                    description=episode.get("plprogram$longDescription"),
                )
                for episode in data
                if episode["plprogram$programType"] == "episode"
            ]
        )

    def get_movies(self, url: str) -> Movies:
        movie_guid, _ = self.parse_url(url)
        data = self.get_data(movie_guid=movie_guid)

        return Movies(
            [
                Movie(
                    id_=movie["guid"],
                    service="RTE",
                    title=movie.get("plprogram$longTitle"),
                    name=movie.get("plprogram$longTitle"),
                    year=movie.get("plprogram$year"),
                    data=movie["plprogramavailability$media"][0]["plmedia$publicUrl"],
                )
                for movie in data
            ]
        )

    def get_config(self):
        token = self.client.get(self.config["login"]).json()["mpx_token"]
        account = self.client.get(self.config["config"]).json()["mpx_config"][
            "account_id"
        ]

        return token, account

    def get_playlist(self, playlist: str, token: str) -> tuple:
        fmt = (
            "&format=SMIL&embedded=true&tracking=true&policy=121498957&iu="
            "/3014/RTE_Player_VOD/Desktop_Web/NotRegistered&assetTypes=default:isl&formats=mpeg-dash"
        )

        r = self.client.get(f"{playlist}?auth={token}{fmt}")
        if not r.ok:
            raise ConnectionError(r.text)

        root = load_xml(r.text)
        video = root.xpath("//switch/video")
        manifest = video[0].get("src")

        elem = root.xpath("//switch/ref")
        value = elem[0].find(".//param[@name='trackingData']").get("value")
        pid = re.search(r"pid=([^|]+)", value).group(1)

        return manifest, pid

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        heights, soup = get_heights(self.client, manifest)
        resolution = heights[0]

        if quality is not None:
            if int(quality) in heights:
                resolution = quality
            else:
                resolution = min(heights, key=lambda x: abs(int(x) - int(quality)))

        return resolution, soup

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

    def get_episode_from_url(self, url: str):
        with self.console.status("Getting episode from URL..."):
            if "/movie/" in url:
                raise ValueError("It looks like this is a movie, use -m/--movie")
            
            series_guid, ep_guid = self.parse_url(url)
            data: list = self.get_data(series_guid=series_guid)

            episode = Series(
                [
                    Episode(
                        id_=episode["guid"],
                        service="RTE",
                        title=episode["plprogram$longTitle"],
                        season=episode.get("plprogram$tvSeasonNumber") or 0,
                        number=episode.get("plprogram$tvSeasonEpisodeNumber") or 0,
                        name=episode.get("description"),
                        year=episode.get("plprogram$year"),
                        data=episode["plprogramavailability$media"][0][
                            "plmedia$publicUrl"
                        ],
                        description=episode.get("plprogram$longDescription"),
                    )
                    for episode in data
                    if episode["guid"] == ep_guid
                ]
            )

        title = string_cleaning(str(episode))

        return [episode[0]], title

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
        token, account = self.get_config()
        manifest, pid = self.get_playlist(stream.data, token)
        self.res, soup = self.get_mediainfo(manifest, self.quality)
        pssh = kid_to_pssh(soup)

        keys = self.get_keys(pssh, token, account, pid)
        with open(self.tmp / "keys.txt", "w") as file:
            file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        self.log.info(f"{str(stream)}")
        click.echo("")

        if self.skip_download:
            self.log.info(f"Filename: {self.filename}")

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
