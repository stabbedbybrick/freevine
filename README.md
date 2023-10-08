### Freevine
Download videos from free streaming services

#### Features:
- [x] Movies & TV-series
- [x] Episode selection and batch options
- [x] Quality selection
- [x] Automatic PSSH, manifest, and key retreival 
- [x] Local and remote CDM options
- [x] Config file with settings for download path, file format, subtitle options etc.

#### Supported services:
    (Premium content on any service is not supported)

    ROKU:     1080p, DD5.1
    CTV:      1080p, DD5.1
    ALL4:     1080p, AAC2.0
    MY5:      1080p, AAC2.0
    iPLAYER:  1080p, AAC2.0
    UKTVPLAY: 1080p, AAC2.0
    STV:      1080p, AAC2.0
    CRACKLE:  1080p, AAC2.0
    ITV:      720p,  AAC2.0
    TUBI:     720p,  AAC2.0
    PLUTO:    720p,  AAC2.0


#### Required tools:
* [Python 3.10+](https://www.python.org/)

* [Pywidevine](https://www.mediafire.com/file/y7o57xs6pazx0rc/pywidevine.zip/)

    * Valid L3 CDM (blob and key) not included

* [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE/releases/)

* [ffmpeg](https://ffmpeg.org/)

* [mkvmerge](https://mkvtoolnix.download/downloads.html)

* [mp4decrypt](https://www.bento4.com/downloads/)

#### Installation:
1. Install Python (check 'Add to PATH' if on Windows)
2. Place pywidevine folder inside Freevine folder
3. Place N_m3u8DL-RE, ffmpeg, mkvmerge, mp4decrypt inside Freevine folder OR add to PATH
4. Install necessary Python modules: `pip install -r requirements.txt`

#### Usage:
    python freevine.py --help (READ THIS!)

    Examples:
    python freevine.py --titles URL
    python freevine.py --info --episode S01E01 URL
    python freevine.py --episode S01E01 URL
    python freevine.py --episode S01E01-S01E10 URL
    python freevine.py --episode S01E01,S03E12,S05E03 URL
    python freevine.py --season S01,S03,S05 URL
    python freevine.py --quality 720p --season S01 URL
    python freevine.py --remote --season S01 URL

#### Notes:
> It's still in early beta. Expect bugs here and there

> Free streaming services are known for having gaps in their library and odd labels

> It's highly recommended to view available episodes with --titles before downloading

    

