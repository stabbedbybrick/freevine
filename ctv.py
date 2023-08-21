"""
ctv downloader - 21/08/23
Author: stabbedbybrick

Info:
This program will grab up to 1080p (if available)
Default settings are set to local CDM and best available quality with all subtitles
Place blob and key file in pywidevine/L3/cdm/devices/android_generic to use local CDM

Requirements:
N_m3u8DL-RE
ffmpeg OR mkvmerge (default: mkvmerge)
mp4decrypt OR shaka-packager (default: mp4decrypt)

Necessary libraries:
pip install httpx lxml click rich sortedcontainers google protobuf==3.19.5 pycryptodomex pycryptodome

Usage:
python ctv.py --help

"""

import base64
import datetime
import re
import subprocess
import json
import asyncio
import shutil

from urllib.parse import urlparse
from pathlib import Path
from abc import ABC
from collections import Counter

import click
import httpx
import requests

from bs4 import BeautifulSoup
from sortedcontainers import SortedKeyList
from rich.console import Console

from pywidevine.L3.decrypt.wvdecryptcustom import WvDecrypt
from pywidevine.L3.cdm import deviceconfig

TMP = Path("tmp")
TMP.mkdir(parents=True, exist_ok=True)

API = "https://api.ctv.ca/space-graphql/graphql"


class Episode:
    def __init__(
        self,
        id_: str,
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

        self.id = id_
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
        id_: str,
        service: str,
        title: str,
        year: int,
        name: str,
        data: str,
    ) -> None:
        name = name.strip()

        self.id = id_
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


def local_cdm(pssh: str, cert_b64=None) -> str:
    lic_url = "https://license.9c9media.ca/widevine"

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
        return content
    else:
        raise ValueError("Unable to fetch decryption keys")


def remote_cdm(pssh: str) -> str:
    lic_url = "https://license.9c9media.ca/widevine"

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
    li_tags = soup.find("ol").find_all("li")
    return [x.text for x in li_tags]


def get_title_id(url: str) -> str:
    url = url.rstrip("/")
    parse = urlparse(url).path.split("/")
    type = parse[1]
    slug = parse[-1]

    payload = {
        "operationName": "resolvePath",
        "variables": {"path": f"/{type}/{slug}"},
        "query": """
        query resolvePath($path: String!) {
            resolvedPath(path: $path) {
                lastSegment {
                    content {
                        id
                    }
                }
            }
        }
        """,
    }
    r = client.post(API, json=payload).json()
    return r["data"]["resolvedPath"]["lastSegment"]["content"]["id"]


def get_series_data(url: str) -> json:
    title_id = get_title_id(url)

    payload = {
        "operationName": "axisMedia",
        "variables": {"axisMediaId": f"{title_id}"},
        "query": """
            query axisMedia($axisMediaId: ID!) {
                contentData: axisMedia(id: $axisMediaId) {
                    title
                    originalSpokenLanguage
                    mediaType
                    firstAirYear
                    seasons {
                        title
                        id
                        seasonNumber
                    }
                }
            }
            """,
    }

    return client.post(API, json=payload).json()["data"]


def get_movie_data(url: str) -> json:
    title_id = get_title_id(url)

    payload = {
        "operationName": "axisMedia",
        "variables": {"axisMediaId": f"{title_id}"},
        "query": """
            query axisMedia($axisMediaId: ID!) {
                contentData: axisMedia(id: $axisMediaId) {
                    title
                    firstAirYear
                    firstPlayableContent {
                        axisId
                    }
                }
            }
            """,
    }

    return client.post(API, json=payload).json()["data"]


async def fetch_titles(async_client: httpx.AsyncClient, id: str) -> json:
    payload = {
        "operationName": "season",
        "variables": {"seasonId": f"{id}"},
        "query": """
            query season($seasonId: ID!) {
                axisSeason(id: $seasonId) {
                    episodes {
                        axisId
                        title
                        contentType
                        seasonNumber
                        episodeNumber
                        axisPlaybackLanguages {
                            language
                            destinationCode
                        }
                    }
                }
            }
            """,
    }
    response = await async_client.post(API, json=payload)
    return response.json()["data"]["axisSeason"]["episodes"]


async def get_titles(data: dict) -> list:
    async with httpx.AsyncClient() as async_client:
        tasks = [fetch_titles(async_client, x["id"]) for x in data]
        titles = await asyncio.gather(*tasks)
        return [episode for episodes in titles for episode in episodes]


def get_episodes(url: str) -> Series:
    data = get_series_data(url)
    titles = asyncio.run(get_titles(data["contentData"]["seasons"]))

    return Series(
        [
            Episode(
                id_=episode["axisId"],
                service="CTV",
                title=data["contentData"]["title"],
                season=int(episode["seasonNumber"]),
                number=int(episode["episodeNumber"]),
                name=episode["title"],
                year=data["contentData"]["firstAirYear"],
                data=episode["axisPlaybackLanguages"][0]["destinationCode"],
            )
            for episode in titles
        ]
    )


def get_movies(url: str) -> Movies:
    data = get_movie_data(url)

    return Movies(
        [
            Movie(
                id_=data["contentData"]["firstPlayableContent"]["axisId"],
                service="CTV",
                title=data["contentData"]["title"],
                year=data["contentData"]["firstAirYear"],
                name=data["contentData"]["title"],
                data="ctvmovies_hub",  # TODO: Don't hardcode
            )
        ]
    )


def get_playlist(hub: str, id: str) -> tuple:
    base = f"https://capi.9c9media.com/destinations/{hub}/platforms/desktop/contents"

    pkg_id = client.get(f"{base}/{id}/contentPackages").json()["Items"][0]["Id"]

    manifest = f"{base}/{id}/contentPackages/{pkg_id}/manifest.mpd?filter=0x14"
    subtitle = f"{base}/{id}/contentPackages/{pkg_id}/manifest.vtt"
    return manifest, subtitle


def get_pssh(soup):
    base = soup.select_one("BaseURL").text
    rep_id = soup.select_one("Representation").attrs.get("id")
    template = (
        soup.select_one("SegmentTemplate")
        .attrs.get("initialization")
        .replace("$RepresentationID$", f"{rep_id}")
    )

    r = client.get(f"{base}{template}")

    with open(TMP / "init.mp4", "wb") as f:
        f.write(r.content)

    path = Path(TMP / "init.mp4")
    raw = Path(path).read_bytes()
    wv = raw.rfind(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
    if wv == -1:
        return None
    return base64.b64encode(raw[wv - 12 : wv - 12 + raw[wv - 9]]).decode("utf-8")


def get_mediainfo(manifest: str, quality: str) -> str:
    soup = BeautifulSoup(client.get(manifest), "xml")
    pssh = get_pssh(soup)
    elements = soup.find_all("Representation")
    heights = sorted(
        [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
        reverse=True,
    )

    if quality is not None:
        if int(quality) in heights:
            return quality, pssh
        else:
            closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
            click.echo(stamp(f"Resolution not available. Getting closest match:"))
            return closest_match, pssh

    return heights[0], pssh


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
    title = string_cleaning(title)

    with console.status("Getting media info..."):
        manifest, subtitle = get_playlist(stream.data, stream.id)
        resolution, pssh = get_mediainfo(manifest, quality)
        r = requests.get(url=f"{subtitle}")
        if not r.ok:
            sub = None
        else:
            sub = True
            with open("sub.vtt", "wb") as f:
                f.write(r.content)

    downloads = Path("downloads")
    save_path = downloads.joinpath(title)
    save_path.mkdir(parents=True, exist_ok=True)

    filename = f"{stream.name}.{resolution}p.{stream.service}.WEB-DL.AAC2.0.H.264"

    with console.status("Getting decryption keys..."):
        keys = remote_cdm(pssh) if remote else local_cdm(pssh)
        with open(TMP / "keys.txt", "w") as file:
            file.write("\n".join(keys))

    click.echo(stamp(f"{filename}"))
    for key in keys:
        click.echo(stamp(f"{key}"))
    click.echo("")

    m3u8dl = shutil.which("N_m3u8DL-RE") or shutil.which("n-m3u8dl-re")

    args = [
        m3u8dl,
        "--key-text-file",
        TMP / "keys.txt",
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
        "16",
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

    args.extend(
        [f"--mux-import", "path=sub.vtt:lang=eng:name='English'"]
    ) if sub else None

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
    python ctv.py --episode S01E01 https://www.ctv.ca/shows/justified
    python ctv.py --episode S01E01-S01E10 https://www.ctv.ca/shows/justified
    python ctv.py --remote --episode S01E01 https://www.ctv.ca/shows/justified
    python ctv.py --quality 720 --season S01 https://www.ctv.ca/shows/justified
    python ctv.py --movie https://www.ctv.ca/movies/celeste-and-jesse-forever
    python ctv.py --titles https://www.ctv.ca/shows/justified
    """
    list_titles(url) if titles else None
    download_episode(quality, url, remote, episode.upper()) if episode else None
    download_season(quality, url, remote, season.upper()) if season else None
    download_movie(quality, url, remote) if movie else None

    shutil.rmtree(TMP)


if __name__ == "__main__":
    console = Console()
    client = httpx.Client(headers={"user-agent": "Chrome/113.0.0.0 Safari/537.36"})
    main()
