"""
Credit to rlaphoenix for the title storage

STV downloader 0.1 - 24/08/23
Author: stabbedbybrick

Info:
Some titles are encrypted, some are not. This program works for both
Quality: 1080p, AAC 2.0 max
Place blob and key file in pywidevine/L3/cdm/devices/android_generic

Requirements:
N_m3u8DL-RE
ffmpeg OR mkvmerge (default: mkvmerge)
mp4decrypt OR shaka-packager (default: mp4decrypt)

Necessary libraries:
pip install httpx lxml click rich sortedcontainers google protobuf==3.19.5 pycryptodomex pycryptodome

How to use:
python stv.py --help

"""

import base64
import datetime
import re
import subprocess
import json
import shutil

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


API = f"https://player.api.stv.tv/v1/episodes?series.guid="
API2 = f"https://edge.api.brightcove.com/playback/v1/accounts"


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


def get_data(url: str) -> tuple:
    soup = BeautifulSoup(client.get(url), "html.parser")
    props = soup.select_one("#__NEXT_DATA__").text
    data = json.loads(props)
    data = data["props"]["pageProps"]["data"]

    id_list = [x["id"] for x in data["tabs"] if x["type"] == "episode"]
    drm = data["programmeData"]["drmEnabled"]

    headers = {"stv-drm": "true"} if drm else None

    seasons = [client.get(f"{API}{id}", headers=headers).json() for id in id_list]

    return seasons, drm


def account_config(drm: bool) -> tuple[dict[str, str]]:
    pkey = {
        "Accept": "application/json;pk="
        "BCpkADawqM1WJ12PwtUWqGXx3nbAo2XVSxyAQxPRZKBc75svhrUB9qIMPN_"
        "d9US0Vib5smumeNMbntSmZIpzeVV1iUrnzYgf5k7UMaVN46PGYe_oSZ-xbPVnsm4"
    }

    pkey_drm = {
        "Accept": "application/json;pk="
        "BCpkADawqM1fQNUrQOvg-vTo4VGDTJ_lGjxp2zBSPcXJntYd5csQkjm7hBKviIVgfFoEJLW4_"
        "JPPsHUwXNEjZspbr3d1HqGDw2gUqGCBZ_9Y_BF7HJsh2n6PQcpL9b2kdbi103oXvmTNZWiQ"
    }

    headers = pkey_drm if drm else pkey
    account = "6204867266001" if drm else "1486976045"

    return headers, account


def get_playlist(video_id: str, drm: bool):
    headers, account = account_config(drm)
    url = f"{API2}/{account}/videos/{video_id}"

    r = client.get(url, headers=headers).json()

    if drm:
        lic_url = r["sources"][2]["key_systems"]["com.widevine.alpha"]["license_url"]
        mpd = r["sources"][2]["src"]
        return mpd, lic_url

    mpd = [x["src"] for x in r["sources"] if x.get("type") == "application/dash+xml"][0]
    lic_url = None
    return mpd, lic_url


def get_series(data: list):
    return Series(
        [
            Episode(
                service="STV",
                title=episode["programme"]["name"],
                season=int(episode["playerSeries"]["name"].split(" ")[1]),
                number=episode["number"],
                name=re.split(r"[,.]", episode["title"])[1],
                year=None,
                data=episode["video"]["id"],
            )
            for series in data
            for episode in series["results"]
        ]
    )


def get_pssh(soup: str) -> str:
    kid = (
        soup.select_one("ContentProtection")
        .attrs.get("cenc:default_KID")
        .replace("-", "")
    )
    version = "3870737368"  # b'8pssh'
    system_id = "EDEF8BA979D64ACEA3C827DCD51D21ED"
    data = "48E3DC959B06"
    s = f"000000{version}00000000{system_id}000000181210{kid}{data}"
    return base64.b64encode(bytes.fromhex(s)).decode()


def get_mediainfo(manifest: str, quality: str, drm: bool) -> str:
    soup = BeautifulSoup(client.get(manifest), "xml")
    pssh = get_pssh(soup) if drm else None
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
        data, drm = get_data(url)
        series = get_series(data)

    seasons = Counter(x.season for x in series)
    num_seasons = len(seasons)
    num_episodes = sum(seasons.values())

    click.echo(
        stamp((f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"))
    )
    for episode in series:
        print(episode.get_filename())

    exit(0)


def get_episode(quality: str, url: str, remote: bool, requested: str) -> None:
    with console.status("Fetching titles..."):
        data, drm = get_data(url)
        series = get_series(data)

    seasons = Counter(x.season for x in series)
    num_seasons = len(seasons)
    num_episodes = sum(seasons.values())

    click.echo(
        stamp((f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"))
    )
    if "-" in requested:
        get_range(series, requested, quality, drm, remote)

    for episode in series:
        episode.name = episode.get_filename()
        if requested in episode.name:
            download(episode, quality, remote, drm, str(series))


def get_range(
    series: object, episode: str, quality: str, drm: bool, remote: bool
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
            download(episode, quality, remote, drm, str(series))


def get_season(quality: str, url: str, remote: bool, requested: str) -> None:
    with console.status("Fetching titles..."):
        data, drm = get_data(url)
        series = get_series(data)

    seasons = Counter(x.season for x in series)
    num_seasons = len(seasons)
    num_episodes = sum(seasons.values())

    click.echo(
        stamp((f"{str(series)}: {num_seasons} Season(s), {num_episodes} Episode(s)\n"))
    )

    for episode in series:
        episode.name = episode.get_filename()
        if requested in episode.name:
            download(episode, quality, remote, drm, str(series))


def get_stream(**kwargs):
    url = kwargs.get("url")
    quality = kwargs.get("quality")
    remote = kwargs.get("remote")
    titles = kwargs.get("titles")
    episode = kwargs.get("episode")
    season = kwargs.get("season")

    list_titles(url) if titles else None
    get_episode(quality, url, remote, episode.upper()) if episode else None
    get_season(quality, url, remote, season.upper()) if season else None


def download(stream: object, quality: str, remote: bool, drm: bool, title: str) -> None:
    title = string_cleaning(title)

    downloads = Path("downloads")
    save_path = downloads.joinpath(title)
    save_path.mkdir(parents=True, exist_ok=True)

    with console.status("Getting media info..."):
        manifest, lic_url = get_playlist(stream.data, drm)
        resolution, pssh = get_mediainfo(manifest, quality, drm)
        filename = f"{stream.name}.{resolution}p.{stream.service}.WEB-DL.AAC2.0.H.264"

    if drm:
        with console.status("Getting decryption keys..."):
            keys = remote_cdm(pssh, lic_url) if remote else local_cdm(pssh, lic_url)
            with open(TMP / "keys.txt", "w") as file:
                file.write("\n".join(keys))

    click.echo(stamp(f"{filename}"))
    click.echo("")

    m3u8dl = shutil.which("N_m3u8DL-RE") or shutil.which("n-m3u8dl-re")

    args = [
        m3u8dl,
        f"{manifest}",
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

    args.extend(["--key-text-file", TMP / "keys.txt"]) if drm else None

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

    \b
    File names follow the current P2P standard: "Title.S01E01.Name.1080p.STV.WEB-DL.AAC2.0.H.264"
    Downloads are located in /downloads folder

    URL format: https://player.stv.tv/summary/a-spy-among-friends/

    \b
    python stv.py --episode S01E01 URL
    python stv.py --episode S01E01-S01E10 URL
    python stv.py --quality 720 --season S01 URL
    python stv.py --remote --season S01 URL
    python stv.py --titles URL
    """
    get_stream(**kwargs)

    shutil.rmtree(TMP)


if __name__ == "__main__":
    console = Console()
    client = httpx.Client(headers={"user-agent": "Chrome/113.0.0.0 Safari/537.36"})
    main()
