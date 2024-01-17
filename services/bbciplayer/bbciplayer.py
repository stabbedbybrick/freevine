"""
BBC iplayer
Author: stabbedbybrick

Info:
up to 1080p

"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections import Counter

import click
import m3u8
from bs4 import BeautifulSoup

from utils.args import get_args
from utils.config import Config
from utils.options import get_downloads
from utils.titles import Episode, Movie, Movies, Series
from utils.utilities import (
    is_title_match,
    set_filename,
    set_save_path,
    string_cleaning,
    force_numbering,
    append_id,
    in_cache,
    update_cache,
)



class BBC(Config):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

        self.series_re = r"^(?:https?://(?:www\.)?bbc\.co\.uk/(?:iplayer/episodes?|programmes?)/)(?P<id>[a-z0-9]+)"
        self.episode_re = (
            r"^(?:https?://(?:www\.)?bbc\.co\.uk/(iplayer/episode)/)(?P<id>[a-z0-9]+)"
        )

        with self.config["download_cache"].open("r") as file:
            self.cache = json.load(file)

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

        r = self.client.post(self.config["api"], json=json_data)
        r.raise_for_status()

        return r.json()["data"]["programme"]

    def create_episode(self, episode):
        title = episode["episode"]["title"]["default"]
        subtitle = episode["episode"]["subtitle"]
        fallback = subtitle.get("default").split(":")[0]
        labels = episode["episode"]["labels"]
        cetegory = labels.get("category") if labels else None

        series = re.finditer(
            r"Series (\d+):|Season (\d+):|(\d{4}/\d{2}): Episode \d+", subtitle.get("default")
        )
        season_num = int(
            next((m.group(1) or m.group(2) or m.group(3).replace("/", "") for m in series), 0)
        )

        number = re.finditer(r"(\d+)\.|Episode (\d+)", subtitle.get("slice") or "")
        ep_num = int(next((m.group(1) or m.group(2) for m in number), 0))

        season_special = True if season_num == 0 else False

        name = re.search(r"\d+\. (.+)", subtitle.get("slice") or "")
        ep_name = name.group(1) if name else subtitle.get("slice") or ""
        if season_special and cetegory == "Entertainment":
            ep_name += f" {fallback}"
        if not subtitle.get("slice"):
            ep_name = subtitle.get("default") or ""

        return Episode(
            id_=episode["episode"]["id"],
            service="iP",
            title=title,
            season=season_num,
            number=ep_num,
            name=ep_name,
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
            for episode in season["entities"]["results"]
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

    def get_streams(self, content: list) -> list:
        for video in [x for x in content if x["kind"] == "video"]:
            connections = sorted(video["connection"], key=lambda x: x["priority"])
            connection = next(
                x
                for x in connections
                if x["supplier"] == "mf_akamai" and x["transferFormat"] == "hls"
            )
            break

        manifest = "/".join(
            connection["href"].replace(".hlsv2.ism", "").split("?")[0].split("/")[0:-1]
            + ["hls", "master.m3u8"]
        )

        for caption in [x for x in content if x["kind"] == "captions"]:
            connections = sorted(caption["connection"], key=lambda x: x["priority"])
            subtitle = next(
                x["href"] for x in connections if x["supplier"] == "mf_cloudfront"
            )
            break

        return manifest, subtitle

    def get_version_content(self, vpid: str) -> list:
        r = self.client.get(self.config["media"].format(client="iptv-all", vpid=vpid))
        if not r.ok:
            raise ConnectionError(f"{r} {r.json()['result']}")

        return r.json()["media"]

    def get_playlist(self, pid: str) -> tuple:
        r = self.client.get(self.config["playlist"].format(pid=pid))
        r.raise_for_status()

        version = r.json().get("defaultAvailableVersion")
        vpid = version["smpConfig"]["items"][0]["vpid"]

        content = self.get_version_content(vpid)
        return self.get_streams(content)

    def get_mediainfo(self, manifest: str, quality: int, resolution=None):
        r = self.client.get(manifest)
        r.raise_for_status()

        base = manifest.split("master")[0]

        m3u8_obj = m3u8.loads(r.text)

        playlists = sorted(
            [
                {
                    "resolution": playlist.stream_info.resolution,
                    "bandwidth": playlist.stream_info.bandwidth,
                    "codec": playlist.stream_info.codecs.split(",")[1],
                    "audio": playlist.stream_info.audio,
                    "uri": base + playlist.uri,
                }
                for playlist in m3u8_obj.playlists
            ],
            key=lambda x: x["resolution"][1],
            reverse=True,
        )

        heights = sorted([x["resolution"][1] for x in playlists], reverse=True)

        if not quality:
            quality = 1080

        first_track = None
        next_track = None

        for stream in playlists:
            if int(quality) in stream["resolution"]:
                uri = self.client.get(stream["uri"])
                if uri.status_code == 200:
                    first_track = stream["uri"]
                    break
                else:
                    self.log.warning(
                        f"Stream for {quality}p responded with [{uri.status_code}], selecting next quality..."
                    )

        if first_track is None:
            next_track = next(
                (
                    (stream["uri"], stream["resolution"][1])
                    for stream in playlists
                    for height in heights
                    if height in stream["resolution"]
                    and self.client.get(stream["uri"]).status_code == 200
                ),
                None,
            )

        if first_track is not None:
            playlist = first_track
            resolution = quality

        elif next_track is not None:
            playlist, resolution = next_track

        if first_track is None and next_track is None:
            self.log.error("No streams available")
            sys.exit(1)

        self.playlist = True

        return playlist, resolution

    def parse_url(self, url: str):
        if is_title_match(url, self.series_re):
            return re.match(self.series_re, url).group("id")

    def get_content(self, url: str) -> object:
        if self.movie:
            with self.console.status("Fetching movie titles..."):
                pid = self.parse_url(url)
                content = self.get_movies(pid)
                title = string_cleaning(str(content))

            self.log.info(f"{str(content)}\n")

        else:
            with self.console.status("Fetching series titles..."):
                pid = self.parse_url(url)
                content = self.get_series(pid)

                seasons = Counter(x.season for x in content)
                num_seasons = len(seasons)
                num_episodes = sum(seasons.values())

                title = string_cleaning(str(content))

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
            r = self.client.get(url)
            r.raise_for_status()

            redux = re.search(
                "window.__IPLAYER_REDUX_STATE__ = (.*?);</script>", r.text
            ).group(1)
            data = json.loads(redux)
            subtitle = data["episode"].get("subtitle")

            if subtitle is not None:
                season_match = re.search(r"Series (\d+):", subtitle)
                season = int(season_match.group(1)) if season_match else 0
                number_match = re.finditer(r"(\d+)\.|Episode (\d+)", subtitle)
                number = int(next((m.group(1) or m.group(2) for m in number_match), 0))
                name_match = re.search(r"\d+\. (.+)", subtitle)
                name = (
                    name_match.group(1)
                    if name_match
                    else subtitle
                    if not re.search(r"Series (\d+): Episode (\d+)", subtitle)
                    else ""
                )

            episode = Series(
                [
                    Episode(
                        id_=data["episode"]["id"],
                        service="iP",
                        title=data["episode"]["title"],
                        season=season if subtitle else 0,
                        number=number if subtitle else 0,
                        name=name if subtitle else "",
                        description=data["episode"]["synopses"].get("small"),
                    )
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
                with self.console.status(f"Slowing things down for {self.slowdown} seconds..."):
                    time.sleep(self.slowdown)

            self.download(download, title)

    def clean_subtitles(self, subtitle: str, filename: str):
        """
        Temporary solution, but seems to work for the most part
        """
        if self.sub_no_fix:
            xml = self.client.get(subtitle)
            with open(self.save_path / f"{filename}.xml", "wb") as f:
                f.write(xml.content)

            self.sub_path = self.tmp / f"{filename}.xml"

        else:
            with self.console.status("Cleaning subtitles..."):
                r = self.client.get(subtitle)
                r.raise_for_status()
                soup = BeautifulSoup(r.content, "xml")
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

                with open(
                    self.tmp / f"{filename}.srt", "w", encoding="UTF-8"
                ) as f:
                    f.write(srt)

            self.sub_path = self.tmp / f"{filename}.srt"

    def download(self, stream: object, title: str) -> None:
        manifest, subtitle = self.get_playlist(stream.id)
        playlist, self.res = self.get_mediainfo(manifest, self.quality)

        self.filename = set_filename(self, stream, self.res, audio="AAC2.0")
        self.save_path = set_save_path(stream, self, title)
        self.manifest = manifest if self.skip_download else playlist
        self.key_file = None  # not encrypted
        self.sub_path = None

        if subtitle is not None and not self.skip_download:
            self.clean_subtitles(subtitle, self.filename)

        self.log.info(f"{str(stream)}")
        click.echo("")

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
