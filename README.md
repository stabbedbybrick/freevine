<h2 align="center">Freevine:tv:</h2>
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
The Roku Channel: 1080p, DD5.1
CBC Gem:          1080p, DD5.1
CTV:              1080p, DD5.1
ABC iView:        1080p, AAC2.0
Channel4 All4:    1080p, AAC2.0
Channel5 My5:     1080p, AAC2.0
BBC iPlayer:      1080p, AAC2.0
UKTVPlay:         1080p, AAC2.0
STV Player:       1080p, AAC2.0
Crackle:          1080p, AAC2.0
Itv(x):           720p,  AAC2.0
Tubi:             720p,  AAC2.0
Pluto:            720p,  AAC2.0
```

## Requirements:

* [Python 3.10+](https://www.python.org/)

* [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE/releases/)

* [ffmpeg](https://ffmpeg.org/)

* [mkvmerge](https://mkvtoolnix.download/downloads.html)

* [mp4decrypt](https://www.bento4.com/downloads/)

* [shaka packager](https://github.com/shaka-project/shaka-packager)

* Widevine Device file (.wvd)

## Installation:

1. Install Python (check 'Add to PATH' if on Windows)
2. Clone or download Freevine repository
3. Place required tools inside Freevine folder OR add them to system PATH (recommended)
4. Create /utils/wvd/ folder and place either .wvd file or private_key and client blob inside
5. Install necessary packages: `pip install -r requirements.txt`

> **Note**
> As of v1.0.0, the requirements have changed
>
> Make sure to re-run the installation if you're coming from the beta version

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
python freevine.py --help (READ THIS!)

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
> **Warning**
> If you encounter this error:
>
> "p = os.fspath(p)
>
> TypeError: expected str, bytes or os.PathLike object, not NoneType"
>
> It means that you haven't properly added N_m3u8DL-RE to PATH and is unable to be located

> **Note**
> Commands will override equivalent settings in config files
>
> See N_m3u8DL-RE --morehelp select-video/select-audio for possible selections

## Disclaimer

1. This project is purely for educational purposes and does not condone piracy
2. RSA key pair required for key derivation is not included in this project

