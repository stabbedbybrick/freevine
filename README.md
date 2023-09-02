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

#### Requirements:
* Python 3.7+

* Working L3 CDM (key and blob)

* N_m3u8DL-RE

* ffmpeg

* mkvmerge

* mp4decrypt

#### Usage:
    pip install -r requirements.txt

    python freevine.py --help (READ THIS!)

    Examples:
    python freevine.py SERVICE --episode S01E01 URL
    python freevine.py SERVICE --episode S01E01-S01E10 URL
    python freevine.py SERVICE --episode S01E01,S03E12,S05E03 URL
    python freevine.py SERVICE --quality 720p --season S01 URL
    python freevine.py SERVICE --remote --season S01 URL
    python freevine.py SERVICE --titles URL


