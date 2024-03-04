<h3 align="center">Freevine<br/>
<sup>A Download Utility for Free Streaming Services</sup></h3>
<p align="center">
    <a href="https://python.org">
        <img src="https://img.shields.io/badge/python-3.9+-blue" alt="Python version">
    </a>
    <a href="https://docs.python.org/3/library/venv.html">
        <img src="https://img.shields.io/badge/python-venv-blue" alt="Python virtual environments">
</p>

## Features:

- [x] Movies & TV-series
- [x] Episode selection and batch options
- [x] Quality selection
- [x] Automatic PSSH, manifest, and key retreival 
- [x] Config file with customized settings
- [x] Search option
- [x] Proxy option
- [x] Option to add login credentials with user profile or cookies 
- [x] [Supported sites](https://github.com/stabbedbybrick/freevine/blob/main/supportedsites.md)

## Requirements:

* [Python](https://www.python.org/)

* [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE/releases/)

* [ffmpeg](https://ffmpeg.org/)

* [mkvmerge](https://mkvtoolnix.download/downloads.html)

* [mp4decrypt](https://www.bento4.com/downloads/)

* [shaka packager](https://github.com/shaka-project/shaka-packager)

* [hola-proxy](https://github.com/Snawoot/hola-proxy) (optional)

* [windscribe-proxy](https://github.com/Snawoot/windscribe-proxy) (optional)

* Valid Widevine CDM (this is not included, so don't ask)

> [!TIP]
> Windows users are recommended to use Powershell 7 in Windows Terminal for best experience

## Installation:

1. Install Python (check 'Add to PATH' if on Windows)
2. Clone main branch or download latest version from [Releases](https://github.com/stabbedbybrick/freevine/releases)
3. Place required tools inside Freevine folder OR add them to system PATH (recommended)
4. Create `/utils/wvd/` folder and place either .wvd file or private_key and client_id blob inside
5. Install necessary packages: `pip install -r requirements.txt`

> [!TIP]
> Clone the main branch to always stay up to date:
>
> ```git clone https://github.com/stabbedbybrick/freevine.git freevine```

## Common issues:

> ModuleNotFoundError: No module named ...

You haven't installed the necessary packages. Run `pip install -r requirements.txt`

> "Required key and client ID not found"

Content is encrypted and a decryption module is needed. This is up to the user and not provided by this project.

> ConnectionError: 400/403/404

You're most likely being geo blocked by the service. Use a VPN or try the proxy option.

## Credentials:

A user profile with credentials can be set for services that require it:
```python
freevine.py profile --username "USERNAME" --password "PASSWORD" --service "SERVICE"
```

> [!NOTE]
>Setting a user profile will create a profile.yaml in the service folder that'll store credentials along with cached auth and refresh tokens

If a service requires cookies, you can use a browser extension to download cookies as .txt file format:

Firefox: https://addons.mozilla.org/addon/export-cookies-txt

Chrome: https://chrome.google.com/webstore/detail/gdocmgbfkjnnpapoeobnolbbkoibbcif

Name it `cookies.txt` and place it in service folder

## Proxies:

When using the `--proxy` option, you can either provide one or request a proxy using country codes (US, UK, SE etc.).

In order to request proxies, [hola-proxy](https://github.com/Snawoot/hola-proxy) and/or [windscribe-proxy](https://github.com/Snawoot/windscribe-proxy) is required. Download the exectutable from the releases page and rename it to "hola-proxy" or "windscribe-proxy". Place it in the same location as the other required tools. System PATH is recommended. Make sure to specify which proxy you want to use in the config file.

    freevine.py --proxy US
    freevine.py --proxy "01.234.56.789:10"

> [!NOTE]
>The proxy only affects API and license requests, not downloads

## Usage:

Available commands:

```python
Commands:
  clear-cache   Delete download cache
  file          Read commands from a text file
  get           Download series or movies
  profile       Create a profile with user credentials
  search        Search one or multiple services for titles
  service-info  Print information about each streaming service
```

Available arguments for `get` command:

```python
  --proxy TEXT                 Request or specify a proxy server
  --threads TEXT               Concurrent download fragments
  --format TEXT                Specify file format
  --muxer TEXT                 Select muxer
  --no-mux                     Choose to not mux files
  --save-name TEXT             Name of saved file
  --save-dir TEXT              Save directory
  --sub-only                   Download only subtitles
  --sub-no-mux                 Choose to not mux subtitles
  --sub-no-fix                 Leave subtitles untouched
  --use-shaka-packager         Use shaka-packager to decrypt
  --add-command TEXT           Add extra command to N_m3u8DL-RE
  --slowdown INTEGER           Add sleep (in seconds) between downloads
  --no-cache                   Ignore download cache
  --append-id                  Append video id to filename
  -fn, --force-numbering       Force add numbering to episodes
  -e, --episode TEXT           Download episode(s)
  -s, --season TEXT            Download complete season
  -c, --complete               Download complete series
  -m, --movie                  Download movie
  -t, --titles                 List all titles
  -i, --info                   Print title info
  -sv, --select-video TEXT     Select video stream
  -sa, --select-audio TEXT     Select audio stream
  -dv, --drop-video TEXT       Drop video stream
  -da, --drop-audio TEXT       Drop audio stream
  -ss, --select-subtitle TEXT  Select subtitle
  -ds, --drop-subtitle TEXT    Drop subtitle
```
Examples:

```python
freevine.py get --help (READ THIS!)

freevine.py get --titles URL
freevine.py get --movie URL
freevine.py get --info --episode S01E01 URL
freevine.py get --sub-only --episode S01E01 URL
freevine.py get --episode S01E01 URL
freevine.py get --episode "name of episode" URL
freevine.py get --episode EPISODE_URL
freevine.py get --episode S01E01-S01E10 URL
freevine.py get --episode S01E01,S03E12,S05E03 URL
freevine.py get --season S01,S03,S05 URL
freevine.py get --select-video res=720 --season S01 URL
freevine.py get --select-audio name=English --episode S01E01 URL

freevine.py service-info
freevine.py service-info "iplayer"

freevine.py profile --help
freevine.py profile --username "username" --password "password" --service "service"

freevine.py search --help
freevine.py search iplayer "KEYWORDS"

freevine.py clear-cache

```
Advanced track selections:

```python
# Select multiple tracks from id, codec, channel etc.
freevine.py get --select-audio id="7|8":for=best2
freevine.py get --select-audio codecs="ec-3|mp4a":for=best2

# Select best 2, and language is ja or en
freevine.py get --select-audio lang="ja|en":for=best2

# Select best video with duration longer than 1 hour 20 minutes 30 seconds
freevine.py get --select-video plistDurMin="1h20m30s":for=best

# Select all subs containing "English"
freevine.py get --select-subtitle name="English":for=all

# Select best audio based on role (only available in 20231113 build of N_m3u8DL-RE)
freevine.py get --select-audio role="main":for=best
```

> [!TIP]
> See "N_m3u8DL-RE --morehelp select-video/audio/subtitle" for possible selection patterns

## Disclaimer

1. This project is purely for educational purposes and does not condone piracy
2. RSA key pair required for key derivation is not included in this project

