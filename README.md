<h2 align="center">Freevine</h2>
<h4 align="center">A download utility for free streaming services</h4>

## Features:

- [x] Movies & TV-series
- [x] Episode selection and batch options
- [x] Quality selection
- [x] Automatic PSSH, manifest, and key retreival 
- [x] Config file with customized settings
- [x] Search option

## Supported services:

```
ROKU:     1080p, DD5.1
CTV:      1080p, DD5.1
CBC GEM:  1080p, DD5.1
iView:    1080p, AAC2.0
ALL4:     1080p, AAC2.0
MY5:      1080p, AAC2.0
iPLAYER:  1080p, AAC2.0
UKTVPLAY: 1080p, AAC2.0
STV:      1080p, AAC2.0
CRACKLE:  1080p, AAC2.0
ITV:      720p,  AAC2.0
TUBI:     720p,  AAC2.0
PLUTO:    720p,  AAC2.0
```

## Requirements:

* [Python 3.10+](https://www.python.org/)

* [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE/releases/)

* [ffmpeg](https://ffmpeg.org/)

* [mkvmerge](https://mkvtoolnix.download/downloads.html)

* [mp4decrypt](https://www.bento4.com/downloads/)

* [shaka packager](https://github.com/shaka-project/shaka-packager)(optional)

* Widevine Device file

## Installation:

1. Install Python (check 'Add to PATH' if on Windows)
2. Clone or download Freevine repository
3. Place N_m3u8DL-RE, ffmpeg, mkvmerge, mp4decrypt inside Freevine folder OR add to PATH
4. Place RSA key pair or .wvd file in /utils/wvd/ folder
5. Install necessary packages: `pip install -r requirements.txt`

> **Note**
> If you encounter this error:
>
> "p = os.fspath(p)
>
> TypeError: expected str, bytes or os.PathLike object, not NoneType"
>
> It means that you haven't properly added N_m3u8DL-RE to PATH and is unable to be located

## Usage:

Available commands:

```
  --help                  Help documentation

  --search                Search service(s) for titles
  --threads               Concurrent download fragments
  --format                Specify file format
  --muxer                 Select muxer
  --no-mux                Choose to not mux files
  --save-name             Name of saved file
  --save-dir              Save directory
  --sub-only              Download only subtitles
  --sub-no-mux            Choose to not mux subtitles
  --sub-no-fix            Leave subtitles untouched
  --use-shaka-packager    Use shaka-packager to decrypt
  -e, --episode           Download episode(s)
  -s, --season            Download complete season
  -c, --complete          Download complete series
  -m, --movie             Download movie
  -t, --titles            List all titles
  -i, --info              Print title info
  -sv, --select-video     Select video stream
  -sa, --select-audio     Select audio stream
  -dv, --drop-video       Drop video stream
  -da, --drop-audio       Drop audio stream
  -ss, --select-subtitle  Select subtitle
  -ds, --drop-subtitle    Drop subtitle
```
Examples:

```
python freevine.py --titles URL
python freevine.py --movie URL
python freevine.py --info --episode S01E01 URL
python freevine.py --subtitles --episode S01E01 URL
python freevine.py --episode S01E01 URL
python freevine.py --episode "name of episode" URL
python freevine.py --episode EPISODE_URL
python freevine.py --episode S01E01-S01E10 URL
python freevine.py --episode S01E01,S03E12,S05E03 URL
python freevine.py --season S01,S03,S05 URL
python freevine.py --select-video res=720 --season S01 URL
python freevine.py --select-audio name=English --episode S01E01 URL

```
> **Note**
> Commands will override equivalent settings in config files
>
> See N_m3u8DL-RE --morehelp select-video/select-audio for possible selections

## Disclaimer

1. This project is purely for educational purposes and does not condone piracy
2. RSA key pair required for key derivation is not included in this project

