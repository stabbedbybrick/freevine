from utils import __version__

main_help = f"""
    \b
    Freevine {__version__}
    Author: stabbedbybrick

    \b
    Requirements:
        Python 3.10+
        Valid Widevine Device file
        N_m3u8DL-RE
        ffmpeg
        mkvmerge
        mp4decrypt
        shaka-packager
    \b
    Installation:
        1. Install Python (check 'Add to PATH' if on Windows)
        2. Clone or download Freevine repository
        3. Place N_m3u8DL-RE, ffmpeg, mkvmerge, mp4decrypt, packager inside Freevine folder OR add to system PATH
        4. Create /utils/wvd/ folder and place either .wvd file or private_key and client blob inside
        5. Install necessary packages: `pip install -r requirements.txt`
    \b
    Settings:
        Open config.yaml in your favorite text editor to configure global settings
    \b
        Copy config.yaml file to a service folder in order to configure that specific service
        This config, if it exists, will override the main config
    \b
        Using config settings in command will override everything else (see options below for examples)
    \b
        Default values for all services:
            Video: Best available
            Audio: Best available
            Subtitles: Cleaned SRT muxed with final output 
    \b
    Instructions:
        This program has got two methods of downloading:
    \b
        Method 1: (singles and batch)
            Provide the series main URL and request what to download from it:
    \b
                python freevine.py --episode  S01E01 URL
                python freevine.py --episode  "Name of episode" URL
                python freevine.py --season   S01 URL
                python freevine.py --episode  S01E01-S01E10 URL
                python freevine.py --episode  S01E01,S03E07,S10E12 URL
                python freevine.py --season   S01,S03,S10 URL
                python freevine.py --complete URL
    \b
            NOTES:
            Always use main URL of series for this method, not episode URLs
            Use the S01E01 format, or "episode name", to request episodes
            Use --episode S01E01-S01E10 to request a range of episodes (from the same season)
            Use --episode S01E01,S03E07,S10E12 (no spaces!) to request a mix of episodes
            Use --season S01,S03,S10 (no spaces!) to request a mix of seasons
    \b
        Method 2: (singles)
            Provide URL to episode or movie to download it directly:
    \b
                python freevine.py --episode EPISODE_URL
                python freevine.py --movie MOVIE_URL
    \b
            NOTES:
            Grabbing the URLs straight from the frontpage often comes with extra
            garbage attached. It's recommended to get the URL from title page
    \b
    Options:
            List all available episodes from a series:
                python freevine.py --titles URL
            Print available quality streams and info about a single title:
                python freevine.py --info --episode URL
                python freevine.py --info --movie URL
            Request video quality to be downloaded: (default: best)
                python freevine.py --select-video res=720 --episode/--season URL
                python freevine.py --select-video res=1080 --movie URL
            Request audio tracks to be downloaded: (default: best)
                python freevine.py --select-audio name=English --episode/--season URL
                python freevine.py --select-audio id=Descriptive --movie URL
            Request only subtitles from title(s):
                python freevine.py --sub-only --episode/--movie URL
    \b
            NOTES:
            See "N_m3u8DL-RE --morehelp select-video/audio/subtitle" for possible selection patterns
            The order of the options isn't super strict, but it's recommended to follow the examples above
            Combinations of options are possible as far as common sense allows
            If you request a quality that's not available, the closest match is downloaded instead
    \b
    Searching (beta):
        You can use the search option to search for titles in the command line:
    \b
            python freevine.py --search all4 "QUERY"
            python freevine.py --search all4,ctv,itv "QUERY"
    \b
            NOTES:
            You can search one or multiple services at the same time
            The results should produce usable URL to series or movie
            Some services have geo block even for searching
    \b    
    Service information:
        (Premium content on any service is not supported)
    \b
            ROKU:     1080p, DD5.1
            CTV:      1080p, DD5.1
            CBC GEM:  1080p, DD5.1
            iView:    1080p, AAC2.0
            ALL4:     1080p, AAC2.0 *
            MY5:      1080p, AAC2.0
            iPLAYER:  1080p, AAC2.0
            UKTVPLAY: 1080p, AAC2.0
            STV:      1080p, AAC2.0
            CRACKLE:  1080p, AAC2.0
            ITV:      720p,  AAC2.0
            TUBI:     720p,  AAC2.0
            PLUTO:    720p,  AAC2.0 
    \b
            *ALL4 offer different quality streams on different API endpoints
            You can switch between them in /services/channel4/api.yaml by using "android" or "web" as client
    \b
    Final notes:
    \b
        This program is just a hobby project inbetween real-life responsibilities
        Expect bugs and odd behavior, and consider it to be in forever beta
    \b
        Known bugs:
        Programmes without clear season/episode labels might display odd names and numbers
        TubiTV and PlutoTV does not work with --info at the moment

    \b
        Free streaming services are free for a reason and usually comes with gaps and odd labels
        It's STRONGLY recommended to use --titles to view episodes before downloading!
    """
