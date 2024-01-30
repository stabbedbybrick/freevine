"""
ABC iVIEW
Author: stabbedbybrick

Quality: up to 1080p

"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import click
import requests
from bs4 import BeautifulSoup

from utils.args import get_args
from utils.cdm import LocalCDM
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    append_id,
    convert_subtitles,
    force_numbering,
    get_heights,
    get_wvd,
    in_cache,
    info,
    kid_to_pssh,
    set_filename,
    set_save_path,
    string_cleaning,
    update_cache,
)


class ABC(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        if self.sub_only:
            info("Subtitle downloads are not supported on this service")
            return

        with self.config["download_cache"].open("r") as file:
            self.cache = json.load(file)

        self.lic_url = self.config["license"]
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

    def get_token(self):
        return self.client.post(
            self.config["jwt"],
            data={"clientId": self.config["client"]},
        ).json()["token"]

    def get_license_url(self, video_id: str):
        jwt = self.get_token()

        resp = self.client.get(
            self.config["drm"].format(video_id=video_id),
            headers={"bearer": jwt},
        ).json()

        if not resp["status"] == "ok":
            raise ValueError("Failed to fetch license token")

        return resp["license"]

    def get_data(self, url: str):
        show_id = urlparse(url).path.split("/")[2]
        url = self.config["series"].format(show=show_id)

        return self.client.get(url).json()

    def create_episode(self, episode):
        title = episode["showTitle"]
        season = re.search(r"Series (\d+)", episode.get("title"))
        number = re.search(r"Episode (\d+)", episode.get("title"))
        names_a = re.search(r"Series \d+ Episode \d+ (.+)", episode.get("title"))
        names_b = re.search(r"Series \d+ (.+)", episode.get("title"))

        name = (
            names_a.group(1)
            if names_a
            else names_b.group(1)
            if names_b
            else episode.get("displaySubtitle")
        )

        return Episode(
            id_=episode["id"],
            service="iV",
            title=title,
            season=int(season.group(1)) if season else 0,
            number=int(number.group(1)) if number else 0,
            name=name,
            description=episode.get("description"),
        )

    def get_series(self, url: str) -> Series:
        data = self.get_data(url)

        if isinstance(data, dict):
            data = [data]

        episodes = [
            self.create_episode(episode)
            for season in data
            for episode in reversed(season["_embedded"]["videoEpisodes"]["items"])
            if season.get("episodeCount")
        ]
        return Series(episodes)

    def get_movies(self, url: str) -> Movies:
        slug = urlparse(url).path.split("/")[2]
        url = self.config["film"].format(slug=slug)

        data = self.client.get(url).json()

        return Movies(
            [
                Movie(
                    id_=data["_embedded"]["highlightVideo"]["id"],
                    service="iV",
                    title=data["title"],
                    name=data["title"],
                    year=data.get("productionYear"),
                    synopsis=data.get("description"),
                )
            ]
        )

    def get_mediainfo(self, manifest: str, quality: str) -> str:
        r = self.client.get(manifest)
        r.raise_for_status()

        if "cenc" not in r.text:
            self.log.error("Unable to parse manifest. Possible VPN/proxy detection")
            sys.exit(0)

        self.soup = BeautifulSoup(r.content, "xml")
        heights, self.soup = get_heights(self.client, manifest)
        resolution = heights[0]

        _base = "/".join(manifest.split("/")[:-1])

        base_urls = self.soup.find_all("BaseURL")
        for base in base_urls:
            base.string = f"{_base}/{base.string}"

        if quality is not None:
            if int(quality) in heights:
                resolution = quality
            else:
                resolution = min(heights, key=lambda x: abs(int(x) - int(quality)))

        return resolution

    def get_playlist(self, video_id: str) -> tuple:
        r = self.client.get(self.config["vod"].format(video_id=video_id)).json()
        if not r.get("playable"):
            raise ConnectionError(r.get("unavailableMessage"))

        playlist = r["_embedded"]["playlist"]
        streams = [
            x["streams"]["mpegdash"] for x in playlist if x["type"] == "program"
        ][0]

        if streams.get("720"):
            manifest = streams["720"].replace("720.mpd", "1080.mpd")
        else:
            manifest = streams["sd"]

        program = [x for x in playlist if x["type"] == "program"][0]
        subtitle = program.get("captions", {}).get("src-vtt")

        return manifest, subtitle

    def get_content(self, url: str) -> object:
        if self.movie:
            with self.console.status("Fetching titles..."):
                content = self.get_movies(self.url)
                title = string_cleaning(str(content))

            self.log.info(f"{str(content)}\n")

        else:
            with self.console.status("Fetching titles..."):
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
            video_id = urlparse(url).path.split("/")[2]

            data = self.client.get(self.config["vod"].format(video_id=video_id)).json()

            episode = self.create_episode(data)

            episode = Series([episode])

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
        manifest, subtitle = self.get_playlist(stream.id)
        self.res = self.get_mediainfo(manifest, self.quality)
        pssh = kid_to_pssh(self.soup)
        customdata = self.get_license_url(stream.id)
        self.client.headers.update({"customdata": customdata})

        keys = self.get_keys(pssh, self.lic_url)
        with open(self.tmp / "keys.txt", "w") as file:
            file.write("\n".join(keys))

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest if not subtitle else self.tmp / "manifest.mpd"
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        self.log.info(f"{str(stream)}")
        click.echo("")

        if subtitle is not None and not self.skip_download:
            self.log.info(f"Subtitles: {subtitle}")
            try:
                sub = self.client.get(subtitle)
                sub.raise_for_status()
            except requests.exceptions.HTTPError:
                self.log.warning(f"Subtitle response {sub.status_code}, skipping")
            else:
                sub_path = self.tmp / f"{self.filename}.vtt"
                with open(sub_path, "wb") as f:
                    f.write(sub.content)

                if not self.sub_no_fix:
                    sub_path = convert_subtitles(
                        self.tmp, self.filename, sub_type="vtt"
                    )

                self.sub_path = sub_path

        if self.skip_download:
            self.log.info(f"Filename: {self.filename}")
            self.log.info("Subtitles: Yes\n") if subtitle else self.log.info(
                "Subtitles: None\n"
            )

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
