"""
ABC iVIEW
Author: stabbedbybrick

Quality: up to 1080p

"""
from __future__ import annotations

import subprocess
import re
import base64

from urllib.parse import urlparse
from collections import Counter
from pathlib import Path

import click
import yaml

from bs4 import BeautifulSoup

from utils.utilities import (
    info,
    error,
    is_url,
    string_cleaning,
    set_save_path,
    set_filename,
    add_subtitles,
    get_wvd,
)
from utils.titles import Episode, Series, Movie, Movies
from utils.options import Options
from utils.args import get_args
from utils.info import print_info
from utils.config import Config
from utils.cdm import LocalCDM


class ABC(Config):
    def __init__(self, config, srvc_api, srvc_config, **kwargs):
        super().__init__(config, srvc_api, srvc_config, **kwargs)

        if self.sub_only:
            info("Subtitle downloads are not supported on this service")
            exit(1)

        with open(self.srvc_api, "r") as f:
            self.config.update(yaml.safe_load(f))

        self.lic_url = self.config["license"]
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

    def get_pssh(self, soup: str) -> str:
        try:
            kid = (
                soup.select_one("ContentProtection")
                .attrs.get("cenc:default_KID")
                .replace("-", "")
            )
        except:
            raise AttributeError("Video unavailable outside of Australia")

        array_of_bytes = bytearray(b"\x00\x00\x002pssh\x00\x00\x00\x00")
        array_of_bytes.extend(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
        array_of_bytes.extend(b"\x00\x00\x00\x12\x12\x10")
        array_of_bytes.extend(bytes.fromhex(kid.replace("-", "")))
        return base64.b64encode(bytes.fromhex(array_of_bytes.hex())).decode("utf-8")

    def get_mediainfo(self, manifest: str, quality: str, subtitle: str) -> str:
        self.soup = BeautifulSoup(self.client.get(manifest), "xml")
        pssh = self.get_pssh(self.soup)
        elements = self.soup.find_all("Representation")
        heights = sorted(
            [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
            reverse=True,
        )

        _base = "/".join(manifest.split("/")[:-1])

        base_urls = self.soup.find_all("BaseURL")
        for base in base_urls:
            base.string = f"{_base}/{base.string}"

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

    def get_playlist(self, video_id: str) -> tuple:
        resp = self.client.get(self.config["vod"].format(video_id=video_id)).json()

        try:
            playlist = resp["_embedded"]["playlist"]
        except:
            raise KeyError(resp["unavailableMessage"])

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
        video_id = urlparse(url).path.split("/")[2]

        data = self.client.get(self.config["vod"].format(video_id=video_id)).json()

        episode = self.create_episode(data)

        episode = Series([episode])

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
            manifest, subtitle = self.get_playlist(stream.id)
            self.res, pssh = self.get_mediainfo(manifest, self.quality, subtitle)
            customdata = self.get_license_url(stream.id)
            self.client.headers.update({"customdata": customdata})

        keys = self.get_keys(pssh, self.lic_url)
        with open(self.tmp / "keys.txt", "w") as file:
            file.write("\n".join(keys))

        if self.info:
            print_info(self, stream, keys)

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest if not subtitle else self.tmp / "manifest.mpd"
        self.key_file = self.tmp / "keys.txt"
        self.sub_path = None

        info(f"{str(stream)}")
        info(f"{keys[0]}")
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
