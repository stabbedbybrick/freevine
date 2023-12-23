from rich.console import Console
from rich.table import Table

console = Console()


def get_dash_info(soup: object):
    representations = soup.find_all("Representation")
    adaptation_sets = soup.find_all("AdaptationSet")

    video = [
        (
            x.attrs["id"],
            f'{x.attrs["width"]}x{x.attrs["height"]}',
            int(x.attrs["bandwidth"]) // 1000,
        )
        for x in representations
        if x.attrs.get("id")
        and x.attrs.get("height")
        and x.attrs.get("width")
        and x.attrs.get("bandwidth")
    ]

    video.extend(
        [
            (
                x.attrs["id"],
                f'{x.attrs["width"]}x{x.attrs["height"]}',
                int(x.attrs.get("bandwidth", 0)) // 1000,
            )
            for x in adaptation_sets
            if x.attrs.get("id") and x.attrs.get("height") and x.attrs.get("width")
        ]
    )

    audio = [
        (x.attrs["id"], int(x.attrs["bandwidth"]) // 1000, x.attrs.get("codecs"))
        for x in representations
        if x.attrs.get("mimeType") == "audio/mp4"
        or x.attrs.get("codecs") == "mp4a.40.2"
        or x.attrs.get("codecs") == "mp4a.40.5"
        or x.attrs.get("codecs") == "ac-3"
        or "audio" in x.attrs.get("id")
    ]

    return video, audio


def get_hls_info(m3u8_obj: object):
    video = []
    audio = []
    if m3u8_obj.is_variant:
        for playlist in m3u8_obj.playlists:
            resolution = f"{playlist.stream_info.resolution[0]}x{playlist.stream_info.resolution[1]}"
            video.append(
                ("Vid", resolution, int(playlist.stream_info.bandwidth) // 1000)
            )
            audio.append(("Audio", 0, "None"))

    return video, audio


def print_sorted_table(video_data, audio_data, stream):
    table = Table(title=str(stream), border_style="grey35")
    table.add_column("Video ID", style="bright_blue")
    table.add_column("Resolution", style="green")
    table.add_column("Bitrate", style="yellow")
    table.add_column("Audio ID", style="bright_blue")
    table.add_column("Bitrate", style="yellow")
    table.add_column("Codec", style="green")

    sorted_video_data = sorted(video_data, key=lambda x: x[2])
    sorted_audio_data = sorted(audio_data, key=lambda x: x[1])

    max_len = max(len(sorted_video_data), len(sorted_audio_data))

    for i in range(max_len):
        video_row = (
            sorted_video_data[i] if i < len(sorted_video_data) else ("", "", "", "")
        )
        audio_row = sorted_audio_data[i] if i < len(sorted_audio_data) else ("", "", "")

        table.add_row(
            video_row[0],
            str(video_row[1]),
            str(video_row[2]),
            audio_row[0],
            str(audio_row[1]),
            str(audio_row[2]),
        )

    console.print("\n\n")
    console.print(table)


def print_info(service: object, stream: object, keys: list = None):
    """Info panel that prints out description, stream ID and keys"""

    if hasattr(service, "hls"):
        video, audio = get_hls_info(service.hls)
    else:
        video, audio = get_dash_info(service.soup)

    print_sorted_table(video, audio, stream)

    exit(0)
