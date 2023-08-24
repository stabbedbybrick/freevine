"""
Credit to Diazole and rlaphoenix for paving the way

ALL4 downloader 0.2 - 24/08/23
Author: stabbedbybrick

Info:
This program will grab higher 1080p bitrate (if available)
Place blob and key file in pywidevine/L3/cdm/devices/android_generic

Requirements:
N_m3u8DL-RE
ffmpeg OR mkvmerge (default: mkvmerge)
mp4decrypt OR shaka-packager (default: mp4decrypt)

Necessary libraries:
pip install httpx lxml click rich sortedcontainers google protobuf==3.19.5 pycryptodomex pycryptodome

Usage:
python all4.py --help

"""

import base64
import datetime
import re
import subprocess
import json
import shutil
import sys

from pathlib import Path
from abc import ABC
from collections import Counter

import click
import httpx

from bs4 import BeautifulSoup
from sortedcontainers import SortedKeyList
from rich.console import Console
from Crypto.Cipher import AES

from pywidevine.L3.decrypt.wvdecryptcustom import WvDecrypt
from pywidevine.L3.cdm import deviceconfig

TMP = Path("tmp")
TMP.mkdir(parents=True, exist_ok=True)


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


def local_cdm(
    pssh: str, lic_url: str, manifest: str, token: str, asset: str, cert_b64=None
) -> str:
    wvdecrypt = WvDecrypt(
        init_data_b64=pssh,
        cert_data_b64=cert_b64,
        device=deviceconfig.device_android_generic,
    )
    lic = get_license(wvdecrypt.get_challenge(), lic_url, manifest, token, asset)

    wvdecrypt.update_license(lic)
    status, content = wvdecrypt.start_process()

    if status:
        return content
    else:
        raise ValueError("Unable to fetch decryption keys")


def get_license(
    challenge: bytes, lic_url, manifest: str, token: str, asset: str
) -> str:
    r = client.post(
        lic_url,
        data=json.dumps(
            {
                "message": base64.b64encode(challenge).decode("utf8"),
                "token": token,
                "request_id": asset,
                "video": {"type": "ondemand", "url": manifest},
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    if r.status_code != 200:
        click.echo(f"Failed to get license! Error: {r.json()['status']['type']}")
        sys.exit(1)
    return r.json()["license"]


def decrypt_token(token: str) -> tuple[str, str]:
    key = "QVlESUQ4U0RGQlA0TThESA=="
    iv = "MURDRDAzODNES0RGU0w4Mg=="

    if isinstance(token, str):
        token = base64.b64decode(token)
        cipher = AES.new(
            key=base64.b64decode(key), iv=base64.b64decode(iv), mode=AES.MODE_CBC
        )
        data = cipher.decrypt(token)[:-2]
        license_api, dec_token = data.decode().split("|")
        return dec_token.strip(), license_api.strip()


def get_data(url: str) -> dict:
    r = client.get(url)
    init_data = re.search(
        "<script>window\.__PARAMS__ = (.*)</script>",
        "".join(
            r.content.decode()
            .replace("\u200c", "")
            .replace("\r\n", "")
            .replace("undefined", "null")
        ),
    )
    data = json.loads(init_data.group(1))
    return data["initialData"]


def get_series(url: str) -> Series:
    data = get_data(url)

    return Series(
        [
            Episode(
                service="ALL4",
                title=data["brand"]["title"],
                season=episode["seriesNumber"],
                number=episode["episodeNumber"],
                name=episode["originalTitle"],
                year=None,
                data=episode.get("assetId"),
            )
            for episode in data["brand"]["episodes"]
        ]
    )


def get_movies(url: str) -> Movies:
    data = get_data(url)

    return Movies(
        [
            Movie(
                service="ALL4",
                title=data["brand"]["title"],
                year=data["brand"]["summary"].split(" ")[0].strip().strip("()"),
                name=data["brand"]["title"],
                data=movie.get("assetId"),
            )
            for movie in data["brand"]["episodes"]
        ]
    )


def get_playlist(asset_id: str) -> tuple[str, str]:
    url = f"https://ais.channel4.com/asset/{asset_id}?client=android-mod"
    r = client.get(url)
    if not r.is_success:
        click.echo("Invalid assetID")
        sys.exit(1)
    soup = BeautifulSoup(r.text, "xml")
    token = soup.select_one("token").text
    manifest = soup.select_one("uri").text
    return manifest, token


def get_pssh(soup: str) -> str:
    kid = (
        soup.select_one("ContentProtection")
        .attrs.get("cenc:default_KID")
        .replace("-", "")
    )
    array_of_bytes = bytearray(b"\x00\x00\x002pssh\x00\x00\x00\x00")
    array_of_bytes.extend(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
    array_of_bytes.extend(b"\x00\x00\x00\x12\x12\x10")
    array_of_bytes.extend(bytes.fromhex(kid.replace("-", "")))
    return base64.b64encode(bytes.fromhex(array_of_bytes.hex())).decode("utf-8")


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
        series = get_series(url)

    seasons = Counter(x.season for x in series)
    num_seasons = len(seasons)
    num_episodes = sum(seasons.values())

    click.echo(
        stamp((f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"))
    )
    for episode in series:
        print(episode.get_filename())


def get_episode(quality: str, url: str, requested: str) -> None:
    with console.status("Fetching titles..."):
        series = get_series(url)

    seasons = Counter(x.season for x in series)
    num_seasons = len(seasons)
    num_episodes = sum(seasons.values())

    click.echo(
        stamp((f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"))
    )
    if "-" in requested:
        get_range(series, requested, quality)

    for episode in series:
        episode.name = episode.get_filename()
        if requested in episode.name:
            download(episode, quality, str(series))


def get_range(series: object, episode: str, quality: str) -> None:
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
            download(episode, quality, str(series))


def get_season(quality: str, url: str, requested: str) -> None:
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
            download(episode, quality, str(series))


def get_movie(quality: str, url: str) -> None:
    with console.status("Fetching titles..."):
        movies = get_movies(url)

    click.echo(stamp(f"{str(movies)}\n"))

    for movie in movies:
        movie.name = movie.get_filename()
        download(movie, quality, str(movies))


def get_stream(**kwargs):
    url = kwargs.get("url")
    quality = kwargs.get("quality")
    titles = kwargs.get("titles")
    episode = kwargs.get("episode")
    season = kwargs.get("season")
    movie = kwargs.get("movie")

    list_titles(url) if titles else None
    get_episode(quality, url, episode.upper()) if episode else None
    get_season(quality, url, season.upper()) if season else None
    get_movie(quality, url) if movie else None


def download(stream: object, quality: str, title: str) -> None:
    title = string_cleaning(title)

    downloads = Path("downloads")
    save_path = downloads.joinpath(title)
    save_path.mkdir(parents=True, exist_ok=True)

    with console.status("Getting media info..."):
        manifest, token = get_playlist(stream.data)
        resolution, pssh = get_mediainfo(manifest, quality)
        token, license_url = decrypt_token(token)
        filename = f"{stream.name}.{resolution}p.{stream.service}.WEB-DL.AAC2.0.H.264"

    with console.status("Getting decryption keys..."):
        keys = local_cdm(pssh, license_url, manifest, token, stream.data)
        with open(TMP / "keys.txt", "w") as file:
            file.write("\n".join(keys))

    click.echo(stamp(f"{filename}"))
    for key in keys:
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

    \b
    File names follow the current P2P standard: "Title.S01E01.Name.1080p.ALL4.WEB-DL.AAC2.0.H.264"
    Downloads are located in /downloads folder

    URL format: https://www.channel4.com/programmes/alone

    \b
    python all4.py --episode S01E01 URL
    python all4.py --episode S01E01-S01E10 URL
    python all4.py --quality 720 --season S01 URL
    python all4.py --movie URL
    python all4.py --titles URL
    """
    get_stream(**kwargs)

    shutil.rmtree(TMP)


if __name__ == "__main__":
    console = Console()
    client = httpx.Client(headers={"user-agent": "Chrome/113.0.0.0 Safari/537.36"})
    main()
