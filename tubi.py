"""
Credit to rlaphoenix for the title storage

TubiTV downloader
Version: 0.0.1 - 25/08/23
Author: stabbedbybrick

Info:
TubiTV WEB is 720p max
Some titles are encrypted, some are not. Both versions are supported
Default settings are set to local CDM and best available quality
Place blob and key file in pywidevine/L3/cdm/devices/android_generic to use local CDM

Requirements:
N_m3u8DL-RE
ffmpeg OR mkvmerge (default: mkvmerge)
mp4decrypt OR shaka-packager (default: mp4decrypt)

Necessary libraries:
pip install -r requirements.txt

Usage:
python tubi.py --help

"""

import base64
import datetime
import re
import subprocess
import json
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
        subtitle: str,
        lic_url: str,
    ) -> None:
        title = title.strip()

        if name is not None:
            name = name.strip()
            if re.match(r"Episode ?#?\d+", name, re.IGNORECASE):
                name = None

        self.service = service
        self.title = title
        self.season = season
        self.number = number
        self.name = name
        self.year = year
        self.data = data
        self.subtitle = subtitle
        self.lic_url = lic_url

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
        lic_url: str,
    ) -> None:
        name = name.strip()

        self.service = service
        self.title = title
        self.year = year
        self.name = name
        self.data = data
        self.lic_url = lic_url

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
        return content
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
    li_tags = soup.find("ol").find_all("li")
    return [x.text for x in li_tags]


def get_data(url: str) -> json:
    type = urlparse(url).path.split("/")[1]
    video_id = urlparse(url).path.split("/")[2]

    content_id = f"0{video_id}" if type == "series" else video_id

    content = (
        f"https://tubitv.com/oz/videos/{content_id}/content?"
        f"video_resources=hlsv6_widevine_nonclearlead&video_resources=hlsv6"
    )

    try:
        return client.get(f"{content}").json()
    except:
        raise KeyError("Request failed. Possible GEO block")


def get_series(url: str) -> Series:
    data = get_data(url)

    return Series(
        [
            Episode(
                service="TUBi",
                title=data["title"],
                season=int(season["id"]),
                number=int(episode["episode_number"]),
                name=episode["title"].split("-")[1],
                year=data["year"],
                data=episode["video_resources"][0]["manifest"]["url"],
                subtitle=episode["subtitles"][0].get("url"),
                lic_url=episode["video_resources"][0]["license_server"]["url"]
                if episode["video_resources"][0].get("license_server")
                else None,
            )
            for season in data["children"]
            for episode in season["children"]
        ]
    )


def get_movies(url: str) -> Movies:
    data = get_data(url)

    return Movies(
        [
            Movie(
                service="TUBi",
                title=data["title"],
                year=data["year"],
                name=data["title"],
                data=data["video_resources"][0]["manifest"]["url"],
                subtitle=data["subtitles"][0].get("url"),
                lic_url=data["video_resources"][0]["license_server"]["url"]
                if data["video_resources"][0].get("license_server")
                else None,
            )
        ]
    )


def get_pssh(mpd: str) -> str:
    r = client.get(mpd)
    url = re.search('#EXT-X-MAP:URI="(.*?)"', r.text).group(1)

    headers = {"Range": "bytes=0-9999"}

    response = client.get(url, headers=headers)
    with open(TMP / "init.mp4", "wb") as f:
        f.write(response.read())

    raw = Path(TMP / "init.mp4").read_bytes()
    wv = raw.rfind(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
    if wv == -1:
        return None
    return base64.b64encode(raw[wv - 12 : wv - 12 + raw[wv - 9]]).decode("utf-8")


def get_mediainfo(manifest: str, quality: str) -> str:
    m3u8 = client.get(manifest).text
    url = urlparse(manifest)
    base = f"https://{url.netloc}/{url.path.split('/')[1]}"

    lines = m3u8.split("\n")
    playlist = [
        (re.search("RESOLUTION=([0-9x]+)", line).group(1), lines[i + 1])
        for i, line in enumerate(lines)
        if line.startswith("#EXT-X-STREAM-INF:")
        and re.search("RESOLUTION=([0-9x]+)", line)
    ]

    playlist.sort(key=lambda x: int(x[0].split("x")[1]), reverse=True)

    if quality is not None:
        for resolution, m3u8_link in playlist:
            if quality in resolution:
                mpd = f"{base}/{m3u8_link}"
                return mpd, quality

    mpd = f"{base}/{playlist[0][1]}"

    return mpd, playlist[0][0].split("x")[1]


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


def get_episode(quality: str, url: str, remote: bool, requested: str) -> None:
    with console.status("Fetching titles..."):
        series = get_series(url)

    seasons = Counter(x.season for x in series)
    num_seasons = len(seasons)
    num_episodes = sum(seasons.values())

    click.echo(
        stamp((f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"))
    )
    if "-" in requested:
        get_range(series, requested, quality, remote)

    for episode in series:
        episode.name = episode.get_filename()
        if requested in episode.name:
            download(episode, quality, remote, str(series))


def get_range(series: object, episode: str, quality: str, remote: str) -> None:
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
            download(episode, quality, remote, str(series))


def get_season(quality: str, url: str, remote: bool, requested: str) -> None:
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
            download(episode, quality, remote, str(series))


def get_complete(quality: str, url: str, remote: bool) -> None:
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
        download(episode, quality, remote, str(series))


def get_movie(quality: str, url: str, remote: bool) -> None:
    with console.status("Fetching titles..."):
        movies = get_movies(url)

    click.echo(stamp(f"{str(movies)}\n"))

    for movie in movies:
        movie.name = movie.get_filename()
        download(movie, quality, remote, str(movies))


def get_stream(**kwargs):
    url = kwargs.get("url")
    quality = kwargs.get("quality")
    remote = kwargs.get("remote")
    titles = kwargs.get("titles")
    episode = kwargs.get("episode")
    season = kwargs.get("season")
    complete = kwargs.get("complete")
    movie = kwargs.get("movie")

    list_titles(url) if titles else None
    get_episode(quality, url, remote, episode.upper()) if episode else None
    get_season(quality, url, remote, season.upper()) if season else None
    get_complete(quality, url, remote) if complete else None
    get_movie(quality, url, remote) if movie else None


def download(stream: object, quality: str, remote: bool, title: str) -> None:
    title = string_cleaning(title)

    downloads = Path("downloads")
    save_path = downloads.joinpath(title)
    save_path.mkdir(parents=True, exist_ok=True)

    with console.status("Getting media info..."):
        manifest, resolution = get_mediainfo(stream.data, quality)
        filename = f"{stream.name}.{resolution}p.{stream.service}.WEB-DL.AAC2.0.H.264"
        sub_path = save_path / f"{filename}.srt"
        if stream.subtitle is not None:
            r = client.get(url=f"{stream.subtitle}")
            with open(sub_path, "wb") as f:
                f.write(r.content)

    if stream.lic_url:
        with console.status("Getting decryption keys..."):
            pssh = get_pssh(manifest)
            keys = (
                remote_cdm(pssh, stream.lic_url)
                if remote
                else local_cdm(pssh, stream.lic_url)
            )
            with open(TMP / "keys.txt", "w") as file:
                file.write("\n".join(keys))

    click.echo(stamp(f"{filename}"))
    click.echo(stamp(f"{keys[0]}")) if stream.lic_url else None
    click.echo("")

    m3u8dl = shutil.which("N_m3u8DL-RE") or shutil.which("n-m3u8dl-re")

    args = [
        m3u8dl,
        f"{stream.data}",
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
        "temp",
        "--save-dir",
        f"{save_path}",
        "--no-log",
        # "--log-level",
        # "OFF",
    ]

    args.extend(["--key-text-file", TMP / "keys.txt"]) if stream.lic_url else None
    args.extend(
        [f"--mux-import", f"path={sub_path}:lang=eng:name='English'"]
    ) if stream.subtitle else None

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
    --quality argument to specify video quality
    --complete argument to download complete series

    \b
    File names follow the current P2P standard: "Title.S01E01.Name.720p.TUBi.WEB-DL.AAC2.0.H.264"
    Downloads are located in /downloads folder

    URL format: https://tubitv.com/series/300007799/blue-mountain-state

    \b
    python tubi.py --episode S01E01 URL
    python tubi.py --episode S01E01-S01E10 URL
    python tubi.py --quality 720 --season S01 URL
    python tubi.py --complete URL
    python tubi.py --remote --season S01 URL
    python tubi.py --movie URL
    python tubi.py --titles URL
    """
    get_stream(**kwargs)

    shutil.rmtree(TMP)


if __name__ == "__main__":
    console = Console()
    client = httpx.Client(headers={"user-agent": "Chrome/113.0.0.0 Safari/537.36"})
    main()
