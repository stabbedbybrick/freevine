import re
import datetime
import shutil

from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.style import Style
from rich.padding import Padding


def info(text: str) -> str:
    time = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    stamp = click.style(f"{time}")
    info = click.style(f"INFO", fg="green", underline=True)
    message = click.style(f" : {text}")
    return click.echo(f"{stamp} {info}{message}")


def error(text: str) -> str:
    time = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    stamp = click.style(f"{time}")
    info = click.style(f"ERROR", fg="red", underline=True)
    message = click.style(f" : {text}")
    return click.echo(f"{stamp} {info}{message}")


def string_cleaning(filename: str) -> str:
    filename = filename.replace("&", "and")
    filename = re.sub(r"[:;/ ]", ".", filename)
    filename = re.sub(r"[\\*!?¿,'\"()<>|$#`’]", "", filename)
    filename = re.sub(rf"[{'.'}]{{2,}}", ".", filename)
    filename = re.sub(rf"[{'_'}]{{2,}}", "_", filename)
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
            year=stream.year if stream.year else "",
            resolution=f"{res}p" if res else "",
            service=stream.service,
            audio=audio,
        )
        return string_cleaning(filename)
    else:
        parts = re.split(r"(S\d+E\d+)", stream.name)
        filename = service.config["filename"]["series"].format(
            title=parts[0].rstrip("."),
            number=parts[1],
            name=parts[2].lstrip(".") if parts[2] else "",
            resolution=f"{res}p" if res else "",
            service=stream.service,
            audio=audio,
        )
        return string_cleaning(filename)


def add_subtitles(soup: object, subtitle: str) -> object:
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
    downloads = Path(config["save_dir"])
    save_path = downloads.joinpath(title)
    save_path.mkdir(parents=True, exist_ok=True)

    if stream.__class__.__name__ == "Episode" and config["seasons"] == "true":
        _season = f"season.{stream.season:02d}"
        save_path = save_path.joinpath(_season)
        save_path.mkdir(parents=True, exist_ok=True)

    return save_path


def print_info(service: object, stream: object, keys: list):
    console = Console()

    elements = service.soup.find_all("Representation")
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

    audio = [
        (x.attrs["bandwidth"], x.attrs["id"], x.attrs.get("codecs"))
        for x in elements
        if x.attrs.get("mimeType") == "audio/mp4"
        or x.attrs.get("codecs") == "mp4a.40.2"
        or x.attrs.get("codecs") == "mp4a.40.5"
        or x.attrs.get("codecs") == "ac-3"
        or "audio" in x.attrs.get("id")
    ]

    text = f"{stream.description}\n\n" if service.episode else f"{stream.synopsis}\n\n"

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
    title = f"[white]{stream.name}[/white]"
    panel = Panel(padding, title=title, width=80, style=Style(color="bright_black"))
    console.print(panel)

    shutil.rmtree(service.tmp)
    exit(0)