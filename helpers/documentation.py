from helpers import __version__

main_help = f"""
    \b
    Freevine {__version__}
    Author: stabbedbybrick

    \b
    Requirements:
        Python 3.9+
        Valid L3 CDM(blob and key)
        N_m3u8DL-RE
        ffmpeg
        mkvmerge
        mp4decrypt

    \b
    Python packages installation:
        pip install -r requirements.txt

    \b
    Settings:
        Open config.yaml in your favorite text editor to change settings like
        download path, folder structure, filenames, subtitle options etc.
    \b
    Instructions:
        Place blob and key file in pywidevine/L3/cdm/devices/android_generic to use local CDM
        Use --remote option if you don't have a CDM (ALL4 not supported)
    \b
        Use freevine.py followed by options and URL to content
        Service is found automatically and is not needed in the command
        See examples at the bottom for usage
    \b
        Always use main URL of series for batch downloads, not episode URLs
        Use the "S01E01" format (Season 1, Episode 1) to request episodes
        Use --episode S01E01-S01E10 to request a range of episodes (from the same season)
        Use --episode S01E01,S03E07,S10E12 (no spaces!) to request a mix of episodes
        Use --season S01,S03,S10 (no spaces!) to request a mix of seasons
    \b
        --titles to list all available episodes from a series
        --remote to get decryption keys remotely (default: local CDM)
        --info to print description and all available quality profiles from a title
        --quality to specify video quality (default: Best)
        --all-audio to include all audio tracks (default: Best)
    \b
    Information:
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
    \b
        Default file names follow the current P2P standard: 
        "Title.S01E01.Name.1080p.SERVICE.WEB-DL.AUDIO.CODEC"
        NOTE: Soaps and certain programmes without clear labels might display
        odd names and numbers. It's a known bug. 
    \b
        If you request a quality that's not available,
        the closest match is downloaded instead
    \b
        It's strongly recommended to use --titles to view episodes before downloading!
    \b
    Examples:
        python freevine.py --titles URL 
        python freevine.py --episode S01E01 URL
        python freevine.py --info --episode S01E01 URL
        python freevine.py --episode S01E01-S01E10 URL
        python freevine.py --quality 720p --season S01 URL
        python freevine.py --remote --season S01 URL
    \b
    Download single episodes directly by URL:
        python freevine.py EPISODE_URL
        python freevine.py --quality EPISODE_URL
        python freevine.py --info EPISODE_URL
    """
