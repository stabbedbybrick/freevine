"""
ctv downloader 0.2 - 24/08/23
Author: stabbedbybrick

Info:
This program will get 1080p and Dolby 5.1 audio (if available)
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


def get_series(url: str) -> Series:
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
    base = f"https://capi.9c9media.com/destinations/{hub}/platforms/desktop"

    pkg_id = client.get(f"{base}/contents/{id}/contentPackages").json()["Items"][0][
        "Id"
    ]
    base += "/playback/contents"

    manifest = (
        f"{base}/{id}/contentPackages/{pkg_id}/manifest.mpd?filter=fe&mca=true&mta=true"
    )
    subtitle = f"{base}/{id}/contentPackages/{pkg_id}/manifest.vtt"
    return manifest, subtitle


def get_pssh(soup):
    try:
        base = soup.select_one("BaseURL").text
    except AttributeError:
        raise AttributeError("Failed to fetch manifest. Possible GEO block")

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

    soup.find("AdaptationSet", {"contentType": "video"}).append(
        soup.new_tag(
            "Representation",
            id="h264-ffa6v1-30p-primary-7200000",
            codecs="avc1.64001f",
            mimeType="video/mp4",
            width="1920",
            height="1080",
            bandwidth="7200000",
        )
    )

    elements = soup.find_all("Representation")
    codecs = [x.attrs["codecs"] for x in elements if x.attrs.get("codecs")]
    heights = sorted(
        [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
        reverse=True,
    )

    audio = "DD5.1" if "ac-3" in codecs else "AAC2.0"

    with open(TMP / "manifest.mpd", "w") as f:
        f.write(str(soup.prettify()))

    if quality is not None:
        if int(quality) in heights:
            return quality, pssh, audio
        else:
            closest_match = min(heights, key=lambda x: abs(int(x) - int(quality)))
            click.echo(stamp(f"Resolution not available. Getting closest match:"))
            return closest_match, pssh, audio

    return heights[0], pssh, audio


def string_cleaning(filename: str) -> str:
    filename = re.sub(r"[:; ]", ".", filename)
    filename = re.sub(r"[\\*!?¿,'\"()<>|$#`]", "", filename)
    filename = re.sub(rf"[{'.'}]{{2,}}", ".", filename)
    return filename


def list_titles(url: str) -> None:
    with console.status("Fetching titles..."):
        series = get_series(url)

    seasons = Counter(x.season for x in series)
    num_seasons = len(seasons)
    num_episodes = sum(seasons.values())

    click.echo(
        stamp((f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"))
    )
    for episode in series:
        print(episode.get_filename())


def get_episode(quality: str, aa: bool, url: str, remote: bool, requested: str) -> None:
    with console.status("Fetching titles..."):
        series = get_series(url)

    seasons = Counter(x.season for x in series)
    num_seasons = len(seasons)
    num_episodes = sum(seasons.values())

    click.echo(
        stamp((f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"))
    )
    if "-" in requested:
        get_range(series, requested, quality, aa, remote)

    for episode in series:
        episode.name = episode.get_filename()
        if requested in episode.name:
            download(episode, quality, aa, remote, str(series))


def get_range(
    series: object, episode: str, quality: str, aa: bool, remote: str
) -> None:
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
            download(episode, quality, aa, remote, str(series))


def get_season(quality: str, aa: bool, url: str, remote: bool, requested: str) -> None:
    with console.status("Fetching titles..."):
        series = get_series(url)

    seasons = Counter(x.season for x in series)
    num_seasons = len(seasons)
    num_episodes = sum(seasons.values())

    click.echo(
        stamp((f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"))
    )

    for episode in series:
        episode.name = episode.get_filename()
        if requested in episode.name:
            download(episode, quality, aa, remote, str(series))


def get_movie(quality: str, aa: bool, url: str, remote: bool) -> None:
    with console.status("Fetching titles..."):
        movies = get_movies(url)

    click.echo(stamp(f"{str(movies)}\n"))

    for movie in movies:
        movie.name = movie.get_filename()
        download(movie, quality, aa, remote, str(movies))


def get_stream(**kwargs):
    url = kwargs.get("url")
    quality = kwargs.get("quality")
    aa = kwargs.get("aa")
    remote = kwargs.get("remote")
    titles = kwargs.get("titles")
    episode = kwargs.get("episode")
    season = kwargs.get("season")
    movie = kwargs.get("movie")

    list_titles(url) if titles else None
    get_episode(quality, aa, url, remote, episode.upper()) if episode else None
    get_season(quality, aa, url, remote, season.upper()) if season else None
    get_movie(quality, aa, url, remote) if movie else None


def download(stream: object, quality: str, aa: bool, remote: bool, title: str) -> None:
    title = string_cleaning(title)

    downloads = Path("downloads")
    save_path = downloads.joinpath(title)
    save_path.mkdir(parents=True, exist_ok=True)

    with console.status("Getting media info..."):
        manifest, subtitle = get_playlist(stream.data, stream.id)
        resolution, pssh, audio = get_mediainfo(manifest, quality)
        filename = f"{stream.name}.{resolution}p.{stream.service}.WEB-DL.{audio}.H.264"
        sub_path = save_path / f"{filename}.vtt"

        r = requests.get(url=f"{subtitle}")
        if not r.ok:
            sub = None
        else:
            sub = True
            with open(sub_path, "wb") as f:
                f.write(r.content)

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
        TMP / "manifest.mpd",
        "-sv",
        f"res='{resolution}'",
        "-sa",
        "all" if aa else "for=best",
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
        [f"--mux-import", f"path={sub_path}:lang=eng:name='English'"]
    ) if sub else None

    try:
        subprocess.run(args, check=True)
    except:
        raise ValueError(
            "Download failed. Install necessary binaries before downloading"
        )


@click.command()
@click.option("-q", "--quality", type=str, help="Specify resolution")
@click.option("-a", "--aa", is_flag=True, help="Include all audio tracks")
@click.option("-e", "--episode", type=str, help="Download episode(s)")
@click.option("-s", "--season", type=str, help="Download season")
@click.option("-m", "--movie", is_flag=True, help="Download a movie")
@click.option("-t", "--titles", is_flag=True, default=False, help="List all titles")
@click.option("-r", "--remote", is_flag=True, default=False, help="Use remote CDM")
@click.argument("url", type=str, required=True)
def main(**kwargs) -> None:
    """
    Information:\n

    \b
    Use base URL of series and then specify which episode(s) you want
    Use the "S01E01" format (Season 1, Episode 1) to request episode
    Movies only require --movie URL

    \b
    --remote argument to get decryption keys remotely
    --titles argument to list all available episodes from a series
    --quality argument to specify video quality
    --aa argument to include all audio tracks (mostly for DV)

    \b
    File names follow the current P2P standard: "Title.S01E01.Name.1080p.CTV.WEB-DL.AAC2.0.H.264"
    Downloads are located in /downloads folder

    URL format: https://www.ctv.ca/shows/justified

    \b
    python ctv.py --episode S01E01 URL
    python ctv.py --episode S01E01-S01E10 URL
    python ctv.py --quality 720 --season S01 URL
    python ctv.py --remote --season S01 URL
    python ctv.py --movie URL
    python ctv.py --titles URL
    """
    get_stream(**kwargs)

    shutil.rmtree(TMP)


if __name__ == "__main__":
    console = Console()
    client = httpx.Client(headers={"user-agent": "Chrome/113.0.0.0 Safari/537.36"})
    main()
