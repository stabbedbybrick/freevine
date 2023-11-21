import re
import datetime
import shutil

from pathlib import Path

import click

from unidecode import unidecode
from rich.console import Console
from rich.panel import Panel
from rich.style import Style
from rich.padding import Padding

from pywidevine.device import Device, DeviceTypes


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
        error("Required key and client ID not found")
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
    info("New WVD file successfully created")

    return next(dir.glob("*.wvd"), None)


def get_wvd(cwd: Path) -> Path:
    """Get path to WVD file"""

    dir = cwd / "utils" / "wvd"
    wvd = next(dir.glob("*.wvd"), None)

    if not wvd:
        info("WVD file is missing. Attempting to create a new one...")
        wvd = create_wvd(dir)

    return wvd


def info(text: str) -> str:
    """Custom info 'logger' designed to match N_m3u8DL-RE output"""

    time = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    stamp = click.style(f"{time}")
    info = click.style(f"INFO", fg="green", underline=True)
    message = click.style(f" : {text}")
    return click.echo(f"{stamp} {info}{message}")


def error(text: str) -> str:
    """Custom error 'logger' designed to match N_m3u8DL-RE output"""

    time = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    stamp = click.style(f"{time}")
    info = click.style(f"ERROR", fg="red", underline=True)
    message = click.style(f" : {text}")
    return click.echo(f"{stamp} {info}{message}")


def is_url(value):
    if value is not None:
        return True if re.match("^https?://", value, re.IGNORECASE) else False
    else:
        return False


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


def set_save_path(stream: object, config, title: str) -> Path:
    downloads = (
        Path(config["save_dir"]["movies"])
        if stream.__class__.__name__ == "Movie"
        else Path(config["save_dir"]["series"])
    )

    save_path = downloads.joinpath(title)
    save_path.mkdir(parents=True, exist_ok=True)

    if (
        stream.__class__.__name__ == "Episode"
        and config["seasons"] == "true"
        and stream.season > 0
    ):
        _season = f"Season {stream.season:02d}"
        save_path = save_path.joinpath(_season)
        save_path.mkdir(parents=True, exist_ok=True)

    return save_path


def print_info(service: object, stream: object, keys: list):
    """Info panel that prints out description, stream ID and keys"""

    console = Console()

    elements = service.soup.find_all("Representation")
    adaptation_sets = service.soup.find_all("AdaptationSet")
    video = sorted(
        [
            (int(x.attrs["width"]), int(x.attrs["height"]), int(x.attrs["bandwidth"]))
            for x in elements
            if x.attrs.get("height")
            and x.attrs.get("width")
            and x.attrs.get("bandwidth")
        ],
        reverse=True,
    )
    video.extend(
        [
            (int(x.attrs["width"]), int(x.attrs["height"]), 2635743)
            for x in adaptation_sets
            if x.attrs.get("height") and x.attrs.get("width")
        ]
    )
    video.sort(reverse=True)

    audio = [
        (x.attrs["bandwidth"], x.attrs["id"], x.attrs.get("codecs"))
        for x in elements
        if x.attrs.get("mimeType") == "audio/mp4"
        or x.attrs.get("codecs") == "mp4a.40.2"
        or x.attrs.get("codecs") == "mp4a.40.5"
        or x.attrs.get("codecs") == "ac-3"
        or "audio" in x.attrs.get("id")
    ]

    text = (
        f"{stream.description}\n\n"
        if stream.__class__.__name__ == "Episode"
        else f"{stream.synopsis}\n\n"
    )

    text += "[white]Video:[/white]\n"
    for width, height, bandwidth in video:
        bitrate = bandwidth // 1000
        text += f"  {width}x{height} @ {bitrate} kb/s\n"

    text += "\n[white]Audio:[/white]\n"
    for bandwidth, id, codec in audio:
        bitrate = int(bandwidth) // 1000
        text += f"  {id} @ {bitrate} kb/s\n"

    if keys is not None:
        text += "\n[white]Keys:[/white]\n"
        for key in keys:
            text += f"  {key}\n"

    padding = Padding(text, (1, 2))
    title = f"[white]{str(stream)}[/white]"
    panel = Panel(padding, title=title, width=80, style=Style(color="bright_black"))
    console.print(panel)

    shutil.rmtree(service.tmp)
    exit(0)
