import shutil
import re

from pathlib import Path

from utils.utilities import info, error


def video_settings(service: object) -> tuple:
    select_video = service.config["video"].get("select")
    drop_video = service.config["video"].get("drop")
    
    if service.select_video != "False":
        select_video = service.select_video
    if service.drop_video != "False":
        drop_video = service.drop_video

    if service.quality and service.quality != str(service.res):
        select_video = re.sub(r"res=\d+", f"res={service.res}", select_video)

    if hasattr(service, "variant") and not service.variant:
        select_video = None
        drop_video = None

    return select_video, drop_video

def audio_settings(service: object) -> tuple:
    select_audio = service.config["audio"].get("select")
    drop_audio = service.config["audio"].get("drop")

    if service.select_audio != "False":
        select_audio = service.select_audio
    if service.drop_audio != "False":
        drop_audio = service.drop_audio

    if hasattr(service, "variant") and not service.variant:
        select_audio = None
        drop_audio = None

    return select_audio, drop_audio

def subtitle_settings(service: object) -> tuple:
    sub_no_mux = service.config["subtitles"]["no_mux"]
    sub_fix = service.config["subtitles"]["fix"]
    select_subtitle = service.config["subtitles"].get("select")
    drop_subtitle = service.config["subtitles"].get("drop")

    if service.sub_only:
        sub_no_mux = "true"
    if service.sub_no_mux:
        sub_no_mux = "true"
    if service.sub_no_fix:
        sub_fix = "false"

    if service.select_subtitle != "False":
        select_subtitle = service.select_subtitle
    if service.drop_subtitle != "False":
        drop_subtitle = service.drop_subtitle

    if hasattr(service, "variant") and not service.variant:
        select_subtitle = None
        drop_subtitle = None

    return sub_no_mux, sub_fix, select_subtitle, drop_subtitle

def format_settings(service: object) -> tuple:
    threads = service.config["threads"]
    format = service.config["format"]
    muxer = service.config["muxer"]
    packager = service.config["shakaPackager"]

    if service.threads != "False":
        threads = service.threads
    if service.format != "False":
        format = service.format
    if service.muxer != "False":
        muxer = service.muxer
    if service.use_shaka_packager:
        packager = "true"

    muxer = "ffmpeg" if format == "mp4" else muxer

    return threads, format, muxer, packager

def dir_settings(service: object) -> tuple:
    temp = service.config["temp_dir"]
    save_path = service.save_path
    filename = service.filename

    if service.save_name != "False":
        filename = service.save_name
    if service.save_dir != "False":
        save_path = service.save_dir

    return temp, save_path, filename

def get_args(service: object) -> tuple:
    """
    Set download arguments based on config settings

    The hierarchy is CLI > service config > main config 
    """

    manifest = service.manifest
    key_file = service.key_file
    sub_path = service.sub_path
    sub_only = service.sub_only
    no_mux = service.no_mux

    m3u8dl = shutil.which("N_m3u8DL-RE") or shutil.which("n-m3u8dl-re")
    if not m3u8dl:
        error("Unable to locate N_m3u8DL-RE on your system")
        shutil.rmtree(service.tmp)
        exit(1)

    threads, format, muxer, packager = format_settings(service)
    temp, save_path, filename = dir_settings(service)
    select_video, drop_video = video_settings(service)
    select_audio, drop_audio = audio_settings(service)
    sub_no_mux, sub_fix, select_sub, drop_sub = subtitle_settings(service)

    args = [
        m3u8dl,
        manifest,
        "-mt",
        "--auto-subtitle-fix",
        sub_fix,
        "--thread-count",
        threads,
        "--save-name",
        filename,
        "--tmp-dir",
        temp,
        "--save-dir",
        save_path,
        "--no-log",
        # "--log-level",
        # "OFF",
    ]

    args.extend(["--key-text-file", key_file]) if key_file else None
    args.extend(["-sv", select_video]) if select_video else None
    args.extend(["-sa", select_audio]) if select_audio else None
    args.extend(["-ss", select_sub]) if select_sub else None
    args.extend(["-dv", drop_video]) if drop_video else None
    args.extend(["-da", drop_audio]) if drop_audio else None
    args.extend(["-ds", drop_sub]) if drop_sub else None
    args.extend(["--sub-only", "true"]) if sub_only else None
    args.extend(["--use-shaka-packager"]) if packager == "true" else None

    if not sub_only and not no_mux:
        args.extend(["-M", f"format={format}:muxer={muxer}:skip_sub={sub_no_mux}"])
    if sub_path and sub_no_mux == "false":
        args.extend(["--mux-import", f"path={sub_path}:lang=eng:name='English'"])

    file_path = Path(save_path) / f"{filename}.{format}"

    return args, file_path


