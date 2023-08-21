"""
Rokuchannel downloader
Version: 0.0.1 - 18/08/23
Author: stabbedbybrick

Info:
This program will grab higher 1080p bitrate and Dolby Digital audio (if available)
Default settings are set to local CDM and best available quality with all subtitles
Place blob and key file in pywidevine/L3/cdm/devices/android_generic to use local CDM

Requirements:
N_m3u8DL-RE
ffmpeg OR mkvmerge (default: mkvmerge)
mp4decrypt OR shaka-packager (default: mp4decrypt)

Necessary libraries:
pip install -r requirements.txt

Usage:
python roku.py --help

"""

import base64
import datetime
import re
import subprocess
import urllib
import json
import asyncio
import shutil

from urllib.parse import urlparse
from pathlib import Path
from abc import ABC
from collections import Counter

import click
import httpx

from bs4 import BeautifulSoup
from sortedcontainers import SortedKeyList
from rich.console import Console

from pywidevine.L3.decrypt.wvdecryptcustom import WvDecrypt
from pywidevine.L3.cdm import deviceconfig


CONTENT = (
    f"https://therokuchannel.roku.com/api/v2/homescreen/content/"
    "https%3A%2F%2Fcontent.sr.roku.com%2Fcontent%2Fv1%2Froku-trc%2F"
)


class Episode:
    def __init__(
        self,
        service: str,
        title: str,
        season: str,
        number: str,
        name: str,
        year: str,
        data: str,
    ) -> None:
        title = title.strip()

        if name is not None:
            name = name.strip()

        self.service = service
        self.title = title
        self.season = season
        self.number = number
        self.name = name
        self.year = year
        self.data = data

    def __str__(self) -> str:
        return "{title} S{season:02}E{number:02} {name}".format(
            title=self.title,
            season=self.season,
            number=self.number,
            name=self.name or "",
        ).strip()

    def get_filename(self) -> str:
        name = "{title} S{season:02}E{number:02} {name}".format(
            title=self.title.replace("$", "S"),
            season=self.season,
            number=self.number,
            name=self.name or "",
        ).strip()

        return string_cleaning(name)


class Series(SortedKeyList, ABC):
    def __init__(self, iterable=None):
        super().__init__(iterable, key=lambda x: (x.season, x.number, x.year or 0))

    def __str__(self) -> str:
        if not self:
            return super().__str__()
        return self[0].title + (f" ({self[0].year})" if self[0].year else "")


class Movie:
    def __init__(
        self,
        service: str,
        title: str,
        year: int,
        name: str,
        data: str,
    ) -> None:
        name = name.strip()

        self.service = service
        self.title = title
        self.year = year
        self.name = name
        self.data = data

    def __str__(self) -> str:
        if self.year:
            return f"{self.name} ({self.year})"
        return self.name

    def get_filename(self) -> str:
        name = str(self).replace("$", "S")

        return string_cleaning(name)


class Movies(SortedKeyList, ABC):
    def __init__(self, iterable=None):
        super().__init__(iterable, key=lambda x: x.year or 0)

    def __str__(self) -> str:
        if not self:
            return super().__str__()
        return self[0].title + (f" ({self[0].year})" if self[0].year else "")


def stamp(text: str) -> str:
    time = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    stamp = click.style(f"{time}")
    info = click.style(f"INFO", fg="green", underline=True)
    message = click.style(f" : {text}")
    return f"{stamp} {info}{message}"


def local_cdm(pssh: str, lic_url: str, cert_b64=None) -> str:
    wvdecrypt = WvDecrypt(
        init_data_b64=pssh,
        cert_data_b64=cert_b64,
        device=deviceconfig.device_android_generic,
    )

    response = client.post(url=lic_url, data=wvdecrypt.get_challenge())
    license_b64 = base64.b64encode(response.content)
    wvdecrypt.update_license(license_b64)
    status, content = wvdecrypt.start_process()

    if status:
        return content[0]
    else:
        raise ValueError("Unable to fetch decryption keys")


def remote_cdm(pssh: str, lic_url: str) -> str:
    headers = {
        "accept": "application/json, text/plain, */*",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
            (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
    }
    payload = {
        "password": "password",
        "license": lic_url,
        "headers": "connection: keep-alive",
        "pssh": pssh,
        "buildInfo": "",
        "proxy": "",
        "cache": False,
    }
    response = client.post("https://wvclone.fly.dev/wv", headers=headers, json=payload)
    soup = BeautifulSoup(response.text, "html.parser")
    return soup.select_one("ol li").text


def get_data(url: str) -> json:
    video_id = urlparse(url).path.split("/")[2]

    try:
        return client.get(f"{CONTENT}{video_id}").json()
    except:
        raise KeyError(
            "Request failed. IP-address is either blocked or content is premium"
        )


async def fetch_titles(async_client: httpx.AsyncClient, id: str) -> json:
    response = await async_client.get(f"{CONTENT}{id}")
    return response.json()


async def get_titles(data: dict) -> list:
    async with httpx.AsyncClient() as async_client:
        tasks = [fetch_titles(async_client, x["meta"]["id"]) for x in data["episodes"]]

        return await asyncio.gather(*tasks)


def get_episodes(url: str) -> Series:
    data = get_data(url)
    episodes = asyncio.run(get_titles(data))

    return Series(
        [
            Episode(
                service="ROKU",
                title=data["title"],
                season=int(episode["seasonNumber"]),
                number=int(episode["episodeNumber"]),
                name=episode["title"],
                year=data["releaseYear"],
                data=episode["meta"]["id"],
            )
            for episode in episodes
        ]
    )


def get_movies(url: str) -> Movies:
    data = get_data(url)

    return Movies(
        [
            Movie(
                service="ROKU",
                title=data["title"],
                year=data["releaseYear"],
                name=data["title"],
                data=data["meta"]["id"],
            )
        ]
    )


def get_playlist(id: str) -> tuple:
    response = client.get("https://therokuchannel.roku.com/api/v1/csrf").json()

    token = response["csrf"]

    headers = {
        "csrf-token": token,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
        (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
    }
    payload = {
        "rokuId": id,
        "mediaFormat": "mpeg-dash",
        "drmType": "widevine",
        "quality": "fhd",
        "providerId": "rokuavod",
    }

    url = f"https://therokuchannel.roku.com/api/v3/playback"

    response = client.post(
        url, headers=headers, cookies=client.cookies, json=payload
    ).json()

    try:
        videos = response["playbackMedia"]["videos"]
    except:
        raise KeyError(
            "Request failed. IP-address is either blocked or content is premium"
        )

    lic_url = [
        x["drmParams"]["licenseServerURL"]
        for x in videos
        if x["drmParams"]["keySystem"] == "Widevine"
    ][0]

    mpd = [x["url"] for x in videos if x["streamFormat"] == "dash"][0]
    manifest = urllib.parse.unquote(mpd).split("=")[1].split("?")[0]

    return lic_url, manifest


def get_mediainfo(manifest: str, quality: str) -> str:
    soup = BeautifulSoup(client.get(manifest), "xml")
    elements = soup.find_all("Representation")
    codecs = [x.attrs["codecs"] for x in elements if x.attrs.get("codecs")]
    heights = sorted(
        [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
        reverse=True,
    )

    audio = "DD5.1" if "ac-3" in codecs else "AAC2.0"

    if quality is not None:
        if quality in heights:
            return quality, audio
        else:
            closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
            click.echo(stamp(f"Resolution not available. Getting closest match:"))
            return closest_match, audio

    return heights[0], audio


def string_cleaning(filename: str) -> str:
    filename = re.sub(r"[:; ]", ".", filename)
    filename = re.sub(r"[\\*!?¿,'\"()<>|$#`]", "", filename)
    filename = re.sub(rf"[{'.'}]{{2,}}", ".", filename)
    return filename


def list_titles(url: str) -> None:
    with console.status("Fetching titles..."):
        series = get_episodes(url)

    seasons = Counter(x.season for x in series)
    num_seasons = len(seasons)
    num_episodes = sum(seasons.values())

    click.echo(
        stamp((f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"))
    )
    for episode in series:
        print(episode.get_filename())


def download_episode(quality: str, url: str, remote: bool, requested: str) -> None:
    with console.status("Fetching titles..."):
        series = get_episodes(url)

    seasons = Counter(x.season for x in series)
    num_seasons = len(seasons)
    num_episodes = sum(seasons.values())

    click.echo(
        stamp((f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"))
    )
    if "-" in requested:
        download_range(series, requested, quality, remote)

    for episode in series:
        episode.name = episode.get_filename()
        if requested in episode.name:
            download_stream(episode, quality, remote, str(series))


def download_range(series: object, episode: str, quality: str, remote: str) -> None:
    start, end = episode.split("-")
    start_season, start_episode = start.split("E")
    end_season, end_episode = end.split("E")

    start_season = int(start_season[1:])
    start_episode = int(start_episode)
    end_season = int(end_season[1:])
    end_episode = int(end_episode)

    episode_range = [
        f"S{season:02d}E{episode:02d}"
        for season in range(start_season, end_season + 1)
        for episode in range(start_episode, end_episode + 1)
    ]

    for episode in series:
        episode.name = episode.get_filename()
        if any(i in episode.name for i in episode_range):
            download_stream(episode, quality, remote, str(series))


def download_season(quality: str, url: str, remote: bool, requested: str) -> None:
    with console.status("Fetching titles..."):
        series = get_episodes(url)

    seasons = Counter(x.season for x in series)
    num_seasons = len(seasons)
    num_episodes = sum(seasons.values())

    click.echo(
        stamp((f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"))
    )

    for episode in series:
        episode.name = episode.get_filename()
        if requested in episode.name:
            download_stream(episode, quality, remote, str(series))


def download_movie(quality: str, url: str, remote: bool) -> None:
    with console.status("Fetching titles..."):
        movies = get_movies(url)

    click.echo(stamp(f"{str(movies)}\n"))

    for movie in movies:
        movie.name = movie.get_filename()
        download_stream(movie, quality, remote, str(movies))


def download_stream(stream: object, quality: str, remote: bool, title: str) -> None:
    pssh = "AAAAKXBzc2gAAAAA7e+LqXnWSs6jyCfc1R0h7QAAAAkiASpI49yVmwY="
    title = string_cleaning(title)
    lic_url, manifest = get_playlist(stream.data)
    resolution, audio = get_mediainfo(manifest, quality)

    downloads = Path("downloads")
    save_path = downloads.joinpath(title)
    save_path.mkdir(parents=True, exist_ok=True)

    filename = f"{stream.name}.{resolution}p.{stream.service}.WEB-DL.{audio}.H.264"

    with console.status("Getting decryption keys..."):
        key = remote_cdm(pssh, lic_url) if remote else local_cdm(pssh, lic_url)

    click.echo(stamp(f"{filename}"))
    click.echo(stamp(f"{key}"))
    click.echo("")

    m3u8dl = shutil.which("N_m3u8DL-RE") or shutil.which("n-m3u8dl-re")

    args = [
        m3u8dl,
        "--key",
        key,
        manifest,
        "-sv",
        f"res='{resolution}'",
        "-sa",
        "for=best",
        "-ss",
        "all",
        "-mt",
        "-M",
        "format=mkv:muxer=mkvmerge",
        "--thread-count",
        "6",
        "--save-name",
        f"{filename}",
        "--tmp-dir",
        "tmp",
        "--save-dir",
        f"{save_path}",
        "--no-log",
        # "--log-level",
        # "OFF",
    ]

    try:
        subprocess.run(args, check=True)
    except:
        raise ValueError(
            "Download failed. Install necessary binaries before downloading"
        )


@click.command()
@click.option("-q", "--quality", type=str, help="Specify resolution")
@click.option("-e", "--episode", type=str, help="Download episode(s)")
@click.option("-s", "--season", type=str, help="Download season")
@click.option("-m", "--movie", is_flag=True, help="Download a movie")
@click.option("-t", "--titles", is_flag=True, default=False, help="List all titles")
@click.option("-r", "--remote", is_flag=True, default=False, help="Use remote CDM")
@click.argument("url", type=str, required=True)
def main(
    quality: str,
    episode: str,
    season: str,
    movie: bool,
    titles: bool,
    url: str,
    remote: bool,
) -> None:
    """
    Examples:\n

    *Use S01E01-S01E10 to download a range of episodes (within the same season)

    \b
    python roku.py --episode S01E01 URL
    python roku.py --episode S01E01-S01E10 URL
    python roku.py --remote --episode S01E01 URL
    python roku.py --quality 720 --season S01 URL
    python roku.py --movie URL
    python roku.py --titles URL
    """
    list_titles(url) if titles else None
    download_episode(quality, url, remote, episode.upper()) if episode else None
    download_season(quality, url, remote, season.upper()) if season else None
    download_movie(quality, url, remote) if movie else None


if __name__ == "__main__":
    console = Console()
    client = httpx.Client(headers={"user-agent": "Chrome/113.0.0.0 Safari/537.36"})
    main()
