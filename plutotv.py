"""
Credit to rlaphoenix for the title storage

PlutoTV downloader 0.0.1 - 28/08/23
Author: stabbedbybrick

Info:
This program will download ad-free streams with highest available quality and subtitles
Quality: 720p, AAC 2.0 max
Some titles are encrypted, some are not. Both versions are supported
Place blob and key file in pywidevine/L3/cdm/devices/android_generic

Notes:
While functional, it's still considered in beta
Labeling for resolution and year is currently missing
Pluto's library is very spotty, so it's highly recommended to use --titles before downloading

Requirements:
N_m3u8DL-RE
ffmpeg OR mkvmerge (default: mkvmerge)
mp4decrypt OR shaka-packager (default: mp4decrypt)

Necessary libraries:
pip install httpx lxml click rich sortedcontainers google protobuf==3.19.5 pycryptodomex pycryptodome

Usage:
python plutotv.py --help

"""

import base64
import datetime
import re
import subprocess
import shutil
import uuid

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


TMP = Path("tmp")
TMP.mkdir(parents=True, exist_ok=True)

BASE = "https://service-vod.clusters.pluto.tv/v4/vod"
LIC_URL = "https://service-concierge.clusters.pluto.tv/v1/wv/alt"


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


def local_cdm(pssh: str, cert_b64=None) -> str:
    wvdecrypt = WvDecrypt(
        init_data_b64=pssh,
        cert_data_b64=cert_b64,
        device=deviceconfig.device_android_generic,
    )

    response = client.post(url=LIC_URL, data=wvdecrypt.get_challenge())
    license_b64 = base64.b64encode(response.content)
    wvdecrypt.update_license(license_b64)
    status, content = wvdecrypt.start_process()

    if status:
        return content[0]
    else:
        raise ValueError("Unable to fetch decryption keys")


def remote_cdm(pssh: str) -> str:
    headers = {
        "accept": "application/json, text/plain, */*",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
            (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
    }
    payload = {
        "password": "password",
        "license": LIC_URL,
        "headers": "connection: keep-alive",
        "pssh": pssh,
        "buildInfo": "",
        "proxy": "",
        "cache": False,
    }
    response = client.post("https://wvclone.fly.dev/wv", headers=headers, json=payload)
    soup = BeautifulSoup(response.text, "html.parser")
    li_tags = soup.find("ol").find_all("li")
    return [x.text for x in li_tags][0]


def get_data(url: str) -> dict:
    type = urlparse(url).path.split("/")[3]
    video_id = urlparse(url).path.split("/")[4]

    params = {
        "appName": "web",
        "appVersion": "na",
        "clientID": str(uuid.uuid1()),
        "deviceDNT": 0,
        "deviceId": "unknown",
        "clientModelNumber": "na",
        "serverSideAds": "false",
        "deviceMake": "unknown",
        "deviceModel": "web",
        "deviceType": "web",
        "deviceVersion": "unknown",
        "sid": str(uuid.uuid1()),
        "drmCapabilities": "widevine:L3",
    }

    response = client.get("https://boot.pluto.tv/v4/start", params=params).json()

    token = response["sessionToken"]

    info = (
        f"{BASE}/series/{video_id}/seasons"
        if type == "series"
        else f"{BASE}/items?ids={video_id}"
    )
    client.headers.update({"Authorization": f"Bearer {token}"})
    client.params = params

    return client.get(info).json()


def get_series(url: str) -> Series:
    data = get_data(url)

    return Series(
        [
            Episode(
                service="PLUTO",
                title=data["name"],
                season=int(episode.get("season")),
                number=int(episode.get("number")),
                name=None,
                year=None,
                data=[x["path"] for x in episode["stitched"]["paths"]],
            )
            for series in data["seasons"]
            for episode in series["episodes"]
        ]
    )


def get_movies(url: str) -> Movies:
    data = get_data(url)

    return Movies(
        [
            Movie(
                service="PLUTO",
                title=movie["name"],
                year=None,  # TODO: Find this somewhere
                name=movie["name"],
                data=[x["path"] for x in movie["stitched"]["paths"]],
            )
            for movie in data
        ]
    )


def get_dash(stitch: str):
    base = "https://cfd-v4-service-stitcher-dash-use1-1.prd.pluto.tv/v2"

    url = f"{base}{stitch}"
    soup = BeautifulSoup(client.get(url), "xml")
    base_url = soup.select_one("BaseURL").text
    parse = urlparse(base_url)
    _path = parse.path.split("/")
    _path = "/".join(_path[:-3])
    new_path = f"{_path}/dash/0-end/main.mpd"

    return parse._replace(
        scheme="http",
        netloc="silo-hybrik.pluto.tv.s3.amazonaws.com",
        path=f"{new_path}",
    ).geturl()


def get_hls(stitch: str):
    base = "https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv"

    url = f"{base}{stitch}"
    response = client.get(url).text
    pattern = r"#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=(\d+),.*\n(.+\.m3u8)"
    matches = re.findall(pattern, response)

    playlists = [(int(bandwidth), url) for bandwidth, url in matches]
    max_bandwidth = sorted(playlists, key=lambda x: x[0], reverse=True)

    url = url.replace("master.m3u8", "")
    base_url = f"{url}{max_bandwidth[0][1]}"

    response = client.get(base_url).text
    segment = re.search(
        r"^(https?://.*/)0\-(end|[0-9]+)/[^/]+\.ts$", response, re.MULTILINE
    ).group(1)

    parse = urlparse(f"{segment}0-end/master.m3u8")

    return parse._replace(
        scheme="http",
        netloc="silo-hybrik.pluto.tv.s3.amazonaws.com",
    ).geturl()


def get_playlist(playlists: str) -> tuple:
    stitched = next((x for x in playlists if x.endswith(".mpd")), None)
    if not stitched:
        stitched = next((x for x in playlists if x.endswith(".m3u8")), None)

    if stitched.endswith(".mpd"):
        return get_dash(stitched)

    if stitched.endswith(".m3u8"):
        return get_hls(stitched)


def get_pssh(kid: str):
    array_of_bytes = bytearray(b"\x00\x00\x002pssh\x00\x00\x00\x00")
    array_of_bytes.extend(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
    array_of_bytes.extend(b"\x00\x00\x00\x12\x12\x10")
    array_of_bytes.extend(bytes.fromhex(kid.replace("-", "")))
    return base64.b64encode(bytes.fromhex(array_of_bytes.hex())).decode("utf-8")


def get_kids(manifest: str) -> str:
    soup = BeautifulSoup(client.get(manifest), "xml")
    tags = soup.find_all("ContentProtection")
    kids = set(
        [
            x.attrs.get("cenc:default_KID").replace("-", "")
            for x in tags
            if x.attrs.get("cenc:default_KID")
        ]
    )

    return [get_pssh(kid) for kid in kids]


def get_mediainfo(manifest: str) -> str:
    client.headers.pop("Authorization")
    return get_kids(manifest) if manifest.endswith(".mpd") else None


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


def get_episode(url: str, remote: bool, requested: str) -> None:
    with console.status("Fetching titles..."):
        series = get_series(url)

    seasons = Counter(x.season for x in series)
    num_seasons = len(seasons)
    num_episodes = sum(seasons.values())

    click.echo(
        stamp((f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"))
    )
    if "-" in requested:
        get_range(series, requested, remote)

    for episode in series:
        episode.name = episode.get_filename()
        if requested in episode.name:
            download(episode, remote, str(series))


def get_range(series: object, episode: str, remote: bool) -> None:
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
            download(episode, remote, str(series))


def get_season(url: str, remote: bool, requested: str) -> None:
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
            download(episode, remote, str(series))


def get_complete(url: str, remote: bool) -> None:
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
        download(episode, remote, str(series))


def get_movie(url: str, remote: bool) -> None:
    with console.status("Fetching titles..."):
        movies = get_movies(url)

    click.echo(stamp(f"{str(movies)}\n"))

    for movie in movies:
        movie.name = movie.get_filename()
        download(movie, remote, str(movies))


def get_stream(**kwargs):
    url = kwargs.get("url")
    remote = kwargs.get("remote")
    titles = kwargs.get("titles")
    episode = kwargs.get("episode")
    season = kwargs.get("season")
    complete = kwargs.get("complete")
    movie = kwargs.get("movie")

    list_titles(url) if titles else None
    get_episode(url, remote, episode.upper()) if episode else None
    get_season(url, remote, season.upper()) if season else None
    get_complete(url, remote) if complete else None
    get_movie(url, remote) if movie else None


def download(stream: object, remote: bool, title: str) -> None:
    title = string_cleaning(title)

    downloads = Path("downloads")
    save_path = downloads.joinpath(title)
    save_path.mkdir(parents=True, exist_ok=True)

    with console.status("Getting media info..."):
        manifest = get_playlist(stream.data)
        pssh = get_mediainfo(manifest)
        filename = f"{stream.name}.{stream.service}.WEB-DL.AAC2.0.H.264"

    click.echo(stamp(f"{filename}"))
    click.echo("")

    if pssh is not None:
        with console.status("Getting decryption keys..."):
            keys = [remote_cdm(key) if remote else local_cdm(key) for key in pssh]
            with open(TMP / "keys.txt", "w") as file:
                file.write("\n".join(keys))

        for key in keys:
            click.echo(stamp(f"{key}"))
        click.echo("")

    m3u8dl = shutil.which("N_m3u8DL-RE") or shutil.which("n-m3u8dl-re")

    args = [
        m3u8dl,
        f"{manifest}",
        "--append-url-params",
        "-sv",
        "for=best",
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
        "temp",
        "--save-dir",
        f"{save_path}",
        "--no-log",
        # "--log-level",
        # "OFF",
    ]
    args.extend(["--key-text-file", TMP / "keys.txt"]) if pssh is not None else None

    try:
        subprocess.run(args, check=True)
    except:
        raise ValueError(
            "Download failed. Install necessary binaries before downloading"
        )


@click.command()
@click.option("-e", "--episode", type=str, help="Download episode(s)")
@click.option("-s", "--season", type=str, help="Download season")
@click.option("-c", "--complete", is_flag=True, help="Download complete series")
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

    \b
    File names follow the current P2P standard: "Title.S01E01.Name.720p.PLUTO.WEB-DL.AAC2.0.H.264"
    Downloads are located in /downloads folder

    URL format: https://pluto.tv/en/on-demand/series/62bf26a809f31a0013741d0d/details/

    \b
    python plutotv.py --episode S01E01 URL
    python plutotv.py --episode S01E01-S01E10 URL
    python plutotv.py --remote --season S01 URL
    python plutotv.py --complete URL
    python plutotv.py --titles URL
    """
    get_stream(**kwargs)

    shutil.rmtree(TMP)


if __name__ == "__main__":
    console = Console()
    client = httpx.Client(headers={"user-agent": "Chrome/113.0.0.0 Safari/537.36"})
    main()
