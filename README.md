### Freevine

#### Requirements:
    Python 3.7+

    Local pywidevine module

    N_m3u8DL-RE

    ffmpeg OR mkvmerge (default: mkvmerge)

    mp4decrypt OR shaka-packager (default: mp4decrypt)

#### Usage examples:
    python ctv.py --help

    python ctv.py --episode S01E01 URL
    python ctv.py --episode S01E01-S01E10 URL
    python ctv.py --quality 720 --season S01 URL
    python ctv.py --remote --season S01 URL
    python ctv.py --complete URL
    python ctv.py --movie URL
    python ctv.py --titles URL


