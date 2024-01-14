import base64
import datetime
import logging
import re
import shutil
import http.cookiejar
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta  # noqa: F811
from pathlib import Path

import click
import m3u8
import requests
from bs4 import BeautifulSoup
from pywidevine.device import Device, DeviceTypes
from unidecode import unidecode
from rich.console import Console

console = Console()
log = logging.getLogger()


def create_wvd(dir: Path) -> Path:
    """
    Check for both untouched and renamed RSA keys and identification blobs
    Create a new WVD from key pair if available
    """
    private_key = None
    client_id = None

    files = dir.glob("*")
    for file in files:
        if file.suffix == ".pem" or file.stem == "device_private_key":
            private_key = file
        if file.suffix == ".bin" or file.stem == "device_client_id_blob":
            client_id = file

    if not private_key and not client_id:
        log.error("Required key and client ID not found")
        exit(1)

    device = Device(
        type_=DeviceTypes["ANDROID"],
        security_level=3,
        flags=None,
        private_key=private_key.read_bytes(),
        client_id=client_id.read_bytes(),
    )

    out_path = (
        dir / f"{device.type.name}_{device.system_id}_l{device.security_level}.wvd"
    )
    device.dump(out_path)
    log.info("New WVD file successfully created")

    return next(dir.glob("*.wvd"), None)


def get_wvd(cwd: Path) -> Path:
    """Get path to WVD file"""

    dir = cwd / "utils" / "wvd"
    wvd = next(dir.glob("*.wvd"), None)

    if not wvd:
        log.info("WVD file is missing. Attempting to create a new one...")
        wvd = create_wvd(dir)

    return wvd


def info(text: str) -> str:
    """Custom info 'logger' designed to match N_m3u8DL-RE output"""

    time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    stamp = click.style(f"{time}")
    info = click.style("INFO", fg="green", underline=True)
    message = click.style(f" : {text}")
    return click.echo(f"{stamp} {info}{message}")


def error(text: str) -> str:
    """Custom error 'logger' designed to match N_m3u8DL-RE output"""

    time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    stamp = click.style(f"{time}")
    info = click.style("ERROR", fg="red", underline=True)
    message = click.style(f" : {text}")
    return click.echo(f"{stamp} {info}{message}")


def notification(text: str) -> str:
    """Custom error 'logger' designed to match N_m3u8DL-RE output"""

    time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    stamp = click.style(f"{time}")
    info = click.style("[!!]", fg="bright_magenta")
    message = click.style(f" : {text}")
    return click.echo(f"{stamp} {info}{message}")


def is_url(value):
    if value is not None:
        return True if re.match("^https?://", value, re.IGNORECASE) else False
    else:
        return False


def is_title_match(string: str, title: re):
    return True if re.match(title, string, re.IGNORECASE) else False


def get_binary(*names: str) -> Path:
    for name in names:
        path = shutil.which(name)
        if path:
            return Path(path)
    return None


def contains_ip_address(input_string):
    pattern = r"\b((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
    return bool(re.search(pattern, input_string))


def get_heights(session: requests.Session, manifest: str) -> tuple:
    r = session.get(manifest)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "xml")
    elements = soup.find_all("Representation")
    heights = sorted(
        [int(x.attrs["height"]) for x in elements if x.attrs.get("height")],
        reverse=True,
    )
    return heights, soup


def force_numbering(content: list) -> list:
    season_episode_counter = {}
    for episode in content:
        if episode.season not in season_episode_counter:
            season_episode_counter[episode.season] = 1
        else:
            season_episode_counter[episode.season] += 1
        episode.number = season_episode_counter[episode.season]

    return content


def load_cookies(path: Path) -> http.cookiejar.MozillaCookieJar:
    cookie_jar = http.cookiejar.MozillaCookieJar(path)
    cookie_jar.load()
    return cookie_jar


def get_cookie(cookie_jar: http.cookiejar.MozillaCookieJar, name: str) -> dict:
    for cookie in cookie_jar:
        if cookie.name == name:
            return {"value": cookie.value, "expires": cookie.expires}
    return None


def in_cache(cache: json, quality: str, download: object) -> bool:
    video = str(download.id)
    if video in cache and quality in cache[video].get("quality", []):
        log.info(f"{str(download)} {quality}p was found in cache. Skipping download...")
        return True
    else:
        return False


def update_cache(cache: json, config: dict, quality: str, download: str) -> None:
    if download in cache and isinstance(cache[download].get("quality"), list):
        cache[download]["quality"].append(quality)
    else:
        cache[download] = {"quality": [quality]}

    with config["download_cache"].open("w") as f:
        json.dump(cache, f, indent=4)


def string_cleaning(filename: str) -> str:
    filename = unidecode(filename)
    filename = filename.replace("&", "and")
    filename = re.sub(r"[:;/]", "", filename)
    filename = re.sub(r"[\\*!?¿,'\"<>|$#`’]", "", filename)
    filename = re.sub(rf"[{'.'}]{{2,}}", ".", filename)
    filename = re.sub(rf"[{'_'}]{{2,}}", "_", filename)
    filename = re.sub(rf"[{' '}]{{2,}}", " ", filename)
    return filename


def set_range(episode: str) -> list:
    start, end = episode.split("-")
    start_season, start_episode = start.split("E")
    end_season, end_episode = end.split("E")

    start_season = int(start_season[1:])
    start_episode = int(start_episode)
    end_season = int(end_season[1:])
    end_episode = int(end_episode)

    return [
        f"S{season:02d}E{episode:02d}"
        for season in range(start_season, end_season + 1)
        for episode in range(start_episode, end_episode + 1)
    ]


def set_filename(service: object, stream: object, res: str, audio: str):
    if service.movie:
        filename = service.config["filename"]["movies"].format(
            title=stream.title,
            year=stream.year or "",
            resolution=f"{res}p" or "",
            service=stream.service,
            audio=audio,
        )
    else:
        filename = service.config["filename"]["series"].format(
            title=stream.title,
            year=stream.year or "",
            season=f"{stream.season:02}" if stream.season > 0 else "",
            episode=f"{stream.number:02}" if stream.number > 0 else "",
            name=stream.name or "",
            resolution=f"{res}p" or "",
            service=stream.service,
            audio=audio,
        )

        no_ep = r"(S\d+)E"
        no_sea = r"S(E\d+)"
        no_num = r"SE"
        if stream.number == 0:
            filename = re.sub(no_ep, r"\1", filename)
        if stream.season == 0:
            filename = re.sub(no_sea, r"\1", filename)
        if stream.season == 0 and stream.number == 0:
            filename = re.sub(no_num, "", filename)

    filename = string_cleaning(filename)
    return (
        filename.replace(" ", ".").replace(".-.", ".")
        if filename.count(".") >= 2
        else filename
    )


def add_subtitles(soup: object, subtitle: str) -> object:
    """Add subtitle stream to manifest"""

    adaptation_set = soup.new_tag(
        "AdaptationSet",
        id="3",
        group="3",
        contentType="text",
        mimeType="text/vtt",
        startWithSAP="1",
    )
    representation = soup.new_tag("Representation", id="English", bandwidth="0")
    base_url = soup.new_tag("BaseURL")
    base_url.string = f"{subtitle}"

    adaptation_set.append(representation)
    representation.append(base_url)

    period = soup.find("Period")
    period.append(adaptation_set)

    return soup


def from_mpd(mpd_data: str, url: str = None):
    root = ET.fromstring(mpd_data)
    items = []

    for adaptationSet in root.iter("{urn:mpeg:dash:schema:mpd:2011}AdaptationSet"):
        for representation in adaptationSet.iter(
            "{urn:mpeg:dash:schema:mpd:2011}Representation"
        ):
            if representation.get("mimeType") in ["video/mp4", "audio/mp4"]:
                item = {}
                if representation.get("id"):
                    item["id"] = representation.get("id")
                if representation.get("codecs"):
                    item["codecs"] = representation.get("codecs")
                if representation.get("height"):
                    item["height"] = representation.get("height")
                if representation.get("bandwidth"):
                    item["bandwidth"] = int(representation.get("bandwidth"))
                items.append(item)

    if url is not None:
        items.insert(0, {"url": url})

    return items


def from_m3u8(m3u8_data: str):
    heights = []
    codecs = []

    m3u8_obj = m3u8.loads(m3u8_data)

    for playlist in m3u8_obj.playlists:
        if playlist.stream_info.resolution:
            heights.append(playlist.stream_info.resolution[1])
        if playlist.stream_info.codecs:
            codecs.append(playlist.stream_info.codecs)

    return heights, codecs


def kid_to_pssh(soup: object) -> str:
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


def construct_pssh(soup: object) -> str:
    kid = (
        soup.select_one("ContentProtection")
        .attrs.get("cenc:default_KID")
        .replace("-", "")
    )
    version = "3870737368"
    system_id = "EDEF8BA979D64ACEA3C827DCD51D21ED"
    data = "48E3DC959B06"
    s = f"000000{version}00000000{system_id}000000181210{kid}{data}"
    return base64.b64encode(bytes.fromhex(s)).decode()


def pssh_from_init(path: Path) -> str:
    raw = Path(path).read_bytes()
    wv = raw.rfind(bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed"))
    if wv == -1:
        return None
    return base64.b64encode(raw[wv - 12 : wv - 12 + raw[wv - 9]]).decode("utf-8")


def set_save_path(stream: object, service: object, title: str) -> Path:
    if service.skip_download:
        save_path = service.tmp / service.filename
        save_path.mkdir(parents=True, exist_ok=True)

    elif service.save_dir != "False":
        save_path = Path(service.save_dir)
        save_path.mkdir(parents=True, exist_ok=True)

    else:
        downloads = (
            Path(service.config["save_dir"]["movies"])
            if stream.__class__.__name__ == "Movie"
            else Path(service.config["save_dir"]["series"])
        )

        save_path = downloads.joinpath(title)
        save_path.mkdir(parents=True, exist_ok=True)

        if (
            stream.__class__.__name__ == "Episode"
            and service.config["seasons"] == "true"
            and stream.season > 0
        ):
            _season = f"Season {stream.season:02d}"
            save_path = save_path.joinpath(_season)
            save_path.mkdir(parents=True, exist_ok=True)

    return save_path


def expiration(expiry: str = None, issued: str = None) -> str:
    """Simple timestamps only"""
    issued_at = datetime.fromtimestamp(int(issued) / 1000)
    return issued_at + timedelta(seconds=int(expiry))


def check_version(local_version: str):
    r = requests.get(
        "https://api.github.com/repos/stabbedbybrick/freevine/releases/latest"
    )
    if not r.ok:
        return

    version = r.json().get("tag_name")

    if version:
        local_version = int(re.sub(r"[v.]", "", local_version))
        latest_version = int(re.sub(r"[v.]", "", version))

    if latest_version and local_version < latest_version:
        notification(f"{version} available: https://github.com/stabbedbybrick/freevine/releases/latest\n")
