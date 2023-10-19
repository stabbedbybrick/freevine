import shutil

from pathlib import Path

from utils.utilities import info, set_range


class Options:
    def __init__(self, cls: object) -> None:
        self.episode = cls.episode
        self.season = cls.season
        self.titles = cls.titles
        self.url = cls.url
        self.tmp = cls.tmp

    def list_titles(self, series: object) -> str:
        for episode in series:
            info(str(episode))

        shutil.rmtree(self.tmp)
        exit(0)

    def get_episode(self, series: object) -> None:
        if "-" in self.episode:
            return self.get_episode_range(series, self.episode)
        if "," in self.episode:
            return self.get_episode_mix(series, self.episode)

        episode = next((i for i in series if self.episode in str(i)), None)

        if episode is not None and self.titles:
            info(f"{str(episode)}")
            shutil.rmtree(self.tmp)
            exit(0)

        if episode is not None:
            return [episode]
        else:
            info(f"{self.episode} was not found")
            shutil.rmtree(self.tmp)
            exit(0)

    def get_episode_range(self, series: object, episodes: str) -> None:
        episode_range = set_range(episodes)

        downloads = []
        for episode in series:
            if any(i in str(episode) for i in episode_range):
                downloads.append(episode)

        if self.titles:
            for episode in downloads:
                info(f"{str(episode)}")

            shutil.rmtree(self.tmp)
            exit(0)

        return downloads

    def get_episode_mix(self, series: object, episodes: str) -> None:
        episode_mix = [x for x in episodes.split(",")]

        downloads = []
        for episode in series:
            if any(i in str(episode) for i in episode_mix):
                downloads.append(episode)

        if self.titles:
            for episode in downloads:
                info(f"{str(episode)}")

            shutil.rmtree(self.tmp)
            exit(0)

        return downloads

    def get_season(self, series: object) -> None:
        if "," in self.season:
            return self.get_season_mix(series, self.season)

        downloads = []
        for episode in series:
            if self.season in str(episode):
                downloads.append(episode)

        if self.titles:
            for episode in downloads:
                info(f"{str(episode)}")

            shutil.rmtree(self.tmp)
            exit(0)

        return downloads

    def get_season_mix(self, series: object, seasons: str):
        season_mix = [x for x in seasons.split(",")]

        downloads = []
        for episode in series:
            if any(i in str(episode) for i in season_mix):
                downloads.append(episode)

        if self.titles:
            for episode in downloads:
                info(f"{str(episode)}")

            shutil.rmtree(self.tmp)
            exit(0)

        return downloads

    def get_complete(self, series: object) -> None:
        downloads = []

        for episode in series:
            downloads.append(episode)

        if self.titles:
            for episode in downloads:
                info(f"{str(episode)}")

            shutil.rmtree(self.tmp)
            exit(0)

        return downloads

    def get_movie(self, movies: object) -> None:
        downloads = []

        for movie in movies:
            downloads.append(movie)

        if self.titles:
            for movie in downloads:
                info(f"{str(movie)}")

            shutil.rmtree(self.tmp)
            exit(0)

        return downloads


def video_settings(quality: bool, res: str, config):
    track_config = config["video"].get("track")
    drop_config = config["video"].get("drop")

    select_video = f"res={res}" if quality else track_config
    drop_video = drop_config if drop_config else None

    return select_video, drop_video


def audio_settings(all_audio: bool, config):
    track_config = config["audio"].get("track")
    drop_config = config["audio"].get("drop")

    select_audio = "all" if all_audio else track_config
    drop_audio = drop_config if drop_config else None

    return select_audio, drop_audio


def subtitle_settings(config, sub_only):
    _mux = "true" if sub_only else config["subtitles"]["no_mux"]
    clean_sub = config["subtitles"]["clean"]

    return _mux, clean_sub


def get_args(service: object, res: str):
    config = service.config
    manifest = service.manifest
    key_file = service.key_file
    filename = service.filename
    save_path = service.save_path
    quality = service.quality
    all_audio = service.all_audio
    sub_path = service.sub_path
    sub_only = service.sub_only

    m3u8dl = shutil.which("N_m3u8DL-RE") or shutil.which("n-m3u8dl-re")

    select_video, drop_video = video_settings(quality, res, config)
    select_audio, drop_audio = audio_settings(all_audio, config)
    _mux, clean_sub = subtitle_settings(config, sub_only)

    temp = config["temp_dir"]
    threads = config["threads"]
    format = config["format"]
    muxer = config["muxer"]

    args = [
        m3u8dl,
        manifest,
        "-sv",
        select_video,
        "-sa",
        select_audio,
        "-ss",
        "all",
        "-mt",
        "--auto-subtitle-fix",
        clean_sub,
        "--thread-count",
        threads,
        "--save-name",
        filename,
        "--tmp-dir",
        temp,
        "--save-dir",
        save_path,
        "--no-log",
        # "--log-level",
        # "OFF",
    ]

    args.extend(["--key-text-file", key_file]) if key_file else None
    args.extend(["-dv", drop_video]) if drop_video else None
    args.extend(["-da", drop_audio]) if drop_audio else None
    args.extend(["--sub-only", "true"]) if sub_only else None

    args.extend(
        ["-M", f"format={format}:muxer={muxer}:skip_sub={_mux}"]
    ) if not sub_only else None
    args.extend(
        [f"--mux-import", f"path={sub_path}:lang=eng:name='English'"]
    ) if sub_path and _mux == "false" else None

    file_path = Path(save_path) / f"{filename}.{format}"

    return args, file_path
