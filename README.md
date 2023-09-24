### Freevine beta (20230924)

#### Changelog:

    #(20230924):

    Added --info option:
        Use --info to print video and audio profiles for single episode or movie (Pluto and Tubi not yet supported)
        A simple info box will display description, video and audio profiles

    Filename customization:
        You can now customize your filename output in config.yaml for both series and movies
        Use the keywords in curly brackets to remove/re-arrange however you want
        NOTE: Any empty spaces will be automatically replaced by dots

    Video and audio quality settings:
        You can now use Video and Audio in config.yaml to set base settings for N_m3u8DL-RE
        See "N_m3u8DL-RE --morehelp select-video" for guidance

    Added functionality:
        Ability to download a mix of full seasons with --season S01,S04,S07 (no spaces)
        You can now use --titles along with --episode and --season to print titles per episode or season

    #(20230920):

    ITV: Subtitles are now part of the manifest and properly converted to SRT
    CTV:  Fixed error where some movie titles had different hubs
    TUBI: Removed hardcoding for subtitles since many titles dont have any

#### Features:

- [x] Movies & TV-series
- [x] Episode selection and batch options
- [x] Quality selection
- [x] Automatic PSSH, manifest, and key retreival 
- [x] Local and remote CDM options
- [x] Config file with settings for download path, file format, subtitle options etc.

#### Supported services:

    (Premium content on any service is not supported)

    ROKU:  1080p, DD5.1
    CTV:   1080p, DD5.1
    ALL4:  1080p, AAC2.0
    UKTV:  1080p, AAC2.0
    STV:   1080p, AAC2.0
    CRKL:  1080p, AAC2.0
    ITV:   720p,  AAC2.0
    TUBI:  720p,  AAC2.0
    PLUTO: 720p,  AAC2.0

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
    python freevine.py --episode S01E01 URL
    python freevine.py --episode S01E01-S01E10 URL
    python freevine.py --episode S01E01,S03E12,S05E03 URL
    python freevine.py --quality 720p --season S01 URL
    python freevine.py --remote --season S01 URL
    python freevine.py --titles URL

#### Notes:

> It's still in early beta. Expect bugs here and there

> Free streaming services are known for having gaps in their library and odd labels

> It's highly recommended to view available episodes with --titles before downloading

    

