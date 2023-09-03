### Freevine (beta)

#### Supported services:
    ROKU:  1080p, DD5.1
    CTV:   1080p, DD5.1
    ALL4:  1080p, AAC2.0
    UKTV:  1080p, AAC2.0
    STV:   1080p, AAC2.0
    ITV:   720p,  AAC2.0
    TUBI:  720p,  AAC2.0
    PLUTO: 720p,  AAC2.0

#### Required tools:
1. [Python 3.7+](https://www.python.org/)

2. [Pywidevine](https://www.mediafire.com/file/y7o57xs6pazx0rc/pywidevine.zip/)

    * Valid L3 CDM (blob and key) required for some services

3. [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE/releases/)

4. [ffmpeg](https://ffmpeg.org/)

5. [mkvmerge](https://mkvtoolnix.download/downloads.html)

6. [mp4decrypt](https://www.bento4.com/downloads/)

#### Installation:
##### Necessary python modules:
    pip install -r requirements.txt

#### Usage:
    python dl.py --help (READ THIS!)

    Examples:
    python dl.py SERVICE --episode S01E01 URL
    python dl.py SERVICE --episode S01E01-S01E10 URL
    python dl.py SERVICE --episode S01E01,S03E12,S05E03 URL
    python dl.py SERVICE --quality 720p --season S01 URL
    python dl.py SERVICE --remote --season S01 URL
    python dl.py SERVICE --titles URL


