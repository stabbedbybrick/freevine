"""
BBC iplayer
Author: stabbedbybrick

Info:
up to 1080p

"""

import subprocess
import re
import json

from collections import Counter
from urllib.parse import urlparse, urlunparse

import click
import requests

from bs4 import BeautifulSoup

from helpers.utilities import (
    info,
    error,
    string_cleaning,
    set_save_path,
    print_info,
    set_filename,
)
from helpers.titles import Episode, Series, Movie, Movies
from helpers.args import Options, get_args
from helpers.config import Config


class BBC(Config):

    def __init__(self, config, srvc, **kwargs):
        super().__init__(config, srvc, **kwargs)

        self.get_options()

    def get_data(self, pid: str, slice_id: str) -> dict:
        json_data = {
            "id": "9fd1636abe711717c2baf00cebb668de",
            "variables": {
                "id": pid,
                "perPage": 200,
                "page": 1,
                "sliceId": slice_id if slice_id else None,
            },
        }

        response = self.client.post(self.srvc["bbc"]["api"], json=json_data).json()

        return response["data"]["programme"]

    def create_episode(self, episode):
        subtitle = episode["episode"]["subtitle"]
        season_match = re.search(r"Series (\d+):", subtitle.get("default"))
        season = int(season_match.group(1)) if season_match else 0
        number_match = re.finditer(
            r"(\d+)\.|Episode (\d+)", subtitle.get("slice") or subtitle.get("default")
        )
        number = int(next((m.group(1) or m.group(2) for m in number_match), 0))
        name_match = re.search(
            r"\d+\. (.+)", subtitle.get("slice") or subtitle.get("default") or ""
        )
        name = name_match.group(1) if name_match else subtitle.get("slice") or ""

        return Episode(
            id_=episode["episode"]["id"],
            service="iP",
            title=episode["episode"]["title"]["default"],
            season=season,
            number=number,
            name=name,
            description=episode["episode"]["synopsis"].get("small"),
        )

    def get_series(self, pid: str) -> Series:
        data = self.get_data(pid, slice_id=None)
        seasons = [
            self.get_data(pid, x["id"]) for x in data["slices"] or [{"id": None}]
        ]

        episodes = [
            self.create_episode(episode)
            for season in seasons
            for episode in reversed(season["entities"]["results"])
        ]
        return Series(episodes)

    def get_movies(self, pid: str) -> Movies:
        data = self.get_data(pid, slice_id=None)

        return Movies(
            [
                Movie(
                    id_=data["id"],
                    service="iP",
                    title=data["title"]["default"],
                    year=None,  # TODO
                    name=data["title"]["default"],
                    synopsis=data["synopsis"].get("small"),
                )
            ]
        )

    def add_stream(self, soup: object, init: str) -> object:
        representation = soup.new_tag(
            "Representation",
            id="video=12000000",
            bandwidth="8490000",
            width="1920",
            height="1080",
            frameRate="50",
            codecs="avc3.640020",
            scanType="progressive",
        )

        template = soup.new_tag(
            "SegmentTemplate",
            timescale="5000",
            duration="19200",
            initialization=f"{init}-$RepresentationID$.dash",
            media=f"{init}-$RepresentationID$-$Number$.m4s",
        )

        representation.append(template)

        soup.find("AdaptationSet", {"contentType": "video"}).append(representation)

        return soup

    def get_playlist(self, pid: str) -> tuple:
        resp = self.client.get(self.srvc["bbc"]["playlist"].format(pid=pid)).json()

        vpid = resp["defaultAvailableVersion"]["smpConfig"]["items"][0]["vpid"]

        media = self.client.get(self.srvc["bbc"]["media"].format(vpid=vpid)).json()

        captions = None
        subtitle = None

        try:
            for item in media["media"]:
                if item["kind"] == "video" and int(item["bitrate"]) > 3500:
                    videos = item["connection"]
        except KeyError:
            error("Request failed. Make sure to use a valid UK IP-address")
            exit(1)

        for item in media["media"]:
            if item["kind"] == "captions":
                captions = item["connection"]

        for video in videos:
            if (
                video["supplier"] == "mf_bidi" and video["transferFormat"] == "dash"
            ):  # TODO
                manifest = video["href"]

        if captions:
            for caption in captions:
                if caption["supplier"] == "mf_bidi" or "mf_cloudfront":
                    subtitle = caption["href"]

        soup = BeautifulSoup(requests.get(manifest).content, "xml")

        parse = urlparse(manifest)
        _path = parse.path.split("/")
        _path[-1] = "dash/"
        init = _path[-2].replace(".ism", "")

        base_url = urlunparse(
            parse._replace(
                scheme="https",
                netloc=self.srvc["bbc"]["base"],
                path="/".join(_path),
                query="",
            )
        )
        soup.select_one("BaseURL").string = base_url

        tag = soup.find(id="video=5070000")
        if tag:
            soup = self.add_stream(soup, init)

        with open(self.tmp / "manifest.mpd", "w") as f:
            f.write(str(soup.prettify()))

        self.soup = soup
        return soup, subtitle

    def get_mediainfo(self, soup: object, quality: str) -> str:
        elements = soup.find_all("Representation")
        heights = sorted(
            [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
            reverse=True,
        )

        if quality is not None:
            if int(quality) in heights:
                return quality
            else:
                closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
                return closest_match

        return heights[0]

    def parse_url(self, url: str):
        regex = r"^(?:https?://(?:www\.)?bbc\.co\.uk/iplayer/episodes?/)?(?P<id>[a-z0-9]+)"

        try:
            pid = re.match(regex, url).group("id")
        except AttributeError:
            error("Improper URL format")
            exit(1)

        return pid

    def get_content(self, url: str) -> object:
        if self.movie:
            with self.console.status("Fetching titles..."):
                pid = self.parse_url(url)
                content = self.get_movies(pid)
                title = string_cleaning(str(content))

            info(f"{str(content)}\n")

        else:
            with self.console.status("Fetching titles..."):
                pid = self.parse_url(url)
                content = self.get_series(pid)

                seasons = Counter(x.season for x in content)
                num_seasons = len(seasons)
                num_episodes = sum(seasons.values())

                episode_count = {}
                extra_episode_number = 1

                for index, episode in enumerate(content):
                    if episode.number == 0 and episode.season == 0:
                        episode.number = extra_episode_number
                        extra_episode_number += 1

                    if episode.season == 0 and num_seasons == 1:
                        episode.season = 1

                    if episode.number == 0 and episode.season > 0:
                        if episode.season not in episode_count:
                            episode_count[episode.season] = 0

                        episode.number = episode_count[episode.season]
                        episode_count[episode.season] += 1

                title = string_cleaning(str(content))

            info(
                f"{str(content)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"
            )

        return content, title

    def get_episode_from_url(self, url: str):
        html = self.client.get(url).text
        redux = (
            re.search("window.__IPLAYER_REDUX_STATE__ = (.*?);</script>", html)
            .group(1)
        )
        data = json.loads(redux)

        subtitle = data["episode"]["subtitle"]
        season_match = re.search(r"Series (\d+):", subtitle)
        season = int(season_match.group(1)) if season_match else 0
        number_match = re.finditer(r"(\d+)\.|Episode (\d+)", subtitle)
        number = int(next((m.group(1) or m.group(2) for m in number_match), 0))
        name_match = re.search(r"\d+\. (.+)", subtitle)
        name = name_match.group(1) if name_match else subtitle if not re.search(
            r"Series (\d+): Episode (\d+)", subtitle
            ) else ""

        episode = Series(
            [
                Episode(
                    id_=data["episode"]["id"],
                    service="iP",
                    title=data["episode"]["title"],
                    season=season,
                    number=number,
                    name=name,
                    description=data["episode"]["synopses"].get("small"),
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

    def clean_subtitles(self, subtitle: str, filename: str):
        """
        Temporary solution, but seems to work for the most part
        """
        with self.console.status("Cleaning up subtitles..."):
            soup = BeautifulSoup(requests.get(subtitle).content, "xml")
            for tag in soup.find_all():
                if tag.name != "p" and tag.name != "br" and tag.name != "span":
                    tag.unwrap()

            for br in soup.find_all("br"):
                br.replace_with(" ")

            srt = ""
            for i, tag in enumerate(soup.find_all("p")):
                start = tag["begin"]
                end = tag["end"]
                text = tag.get_text().strip()
                srt += f"{i+1}\n{start.replace('.', ',')} --> {end.replace('.', ',')}\n{text}\n\n"

            with open(self.save_path / f"{filename}.srt", "w", encoding="UTF-8") as f:
                f.write(srt)

        self.sub_path = self.save_path / f"{filename}.srt"

    def download(self, stream: object, title: str) -> None:
        with self.console.status("Getting media info..."):
            soup, subtitle = self.get_playlist(stream.id)
            res = self.get_mediainfo(soup, self.quality)

        if self.info:
            print_info(self, stream, keys=None)

        self.filename = set_filename(self, stream, res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self.config, title)
        self.manifest = self.tmp / "manifest.mpd"
        self.key_file = None  # not encrypted
        self.sub_path = None

        if subtitle is not None:
            self.clean_subtitles(subtitle, self.filename)

        info(f"{str(stream)}")
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
