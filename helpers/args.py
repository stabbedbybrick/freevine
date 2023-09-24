import shutil

from pathlib import Path

from helpers.utilities import info, set_range


class Options:
    def __init__(self, cls: object) -> None:
        self.episode = cls.episode
        self.season = cls.season
        self.titles = cls.titles
        self.url = cls.url
        self.tmp = cls.tmp

    def list_titles(self, series: object) -> str:
        for episode in series:
            info(episode.name)

        shutil.rmtree(self.tmp)
        exit(0)

    def get_episode(self, series: object) -> None:
        if "-" in self.episode:
            return self.get_episode_range(series, self.episode)
        if "," in self.episode:
            return self.get_episode_mix(series, self.episode)

        episode = next((i for i in series if self.episode in i.name), None)

        if episode is not None and self.titles:
            info(f"{episode.name}")
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
            if any(i in episode.name for i in episode_range):
                downloads.append(episode)

        if self.titles:
            for episode in downloads:
                info(f"{episode.name}")

            shutil.rmtree(self.tmp)
            exit(0)

        return downloads

    def get_episode_mix(self, series: object, episodes: str) -> None:
        episode_mix = [x for x in episodes.split(",")]

        downloads = []
        for episode in series:
            if any(i in episode.name for i in episode_mix):
                downloads.append(episode)

        if self.titles:
            for episode in downloads:
                info(f"{episode.name}")

            shutil.rmtree(self.tmp)
            exit(0)

        return downloads

    def get_season(self, series: object) -> None:
        if "," in self.season:
            return self.get_season_mix(series, self.season)

        downloads = []
        for episode in series:
            if self.season in episode.name:
                downloads.append(episode)

        if self.titles:
            for episode in downloads:
                info(f"{episode.name}")

            shutil.rmtree(self.tmp)
            exit(0)

        return downloads

    def get_season_mix(self, series: object, seasons: str):
        season_mix = [x for x in seasons.split(",")]

        downloads = []
        for episode in series:
            if any(i in episode.name for i in season_mix):
                downloads.append(episode)

        if self.titles:
            for episode in downloads:
                info(f"{episode.name}")

            shutil.rmtree(self.tmp)
            exit(0)

        return downloads

    def get_complete(self, series: object) -> None:
        downloads = []

        for episode in series:
            downloads.append(episode)

        if self.titles:
            for episode in downloads:
                info(f"{episode.name}")

            shutil.rmtree(self.tmp)
            exit(0)

        return downloads

    def get_movie(self, movies: object) -> None:
        downloads = []

        for movie in movies:
            movie.name = movie.get_filename()
            downloads.append(movie)

        if self.titles:
            for movie in downloads:
                info(f"{movie.name}")

            shutil.rmtree(self.tmp)
            exit(0)

        return downloads


def get_args(service: object, res: str):
    config = service.config
    manifest = service.manifest
    key_file = service.key_file
    filename = service.filename
    save_path = service.save_path
    quality = service.quality
    all_audio = service.all_audio
    sub_path = service.sub_path

    m3u8dl = shutil.which("N_m3u8DL-RE") or shutil.which("n-m3u8dl-re")

    video = f"res='{res}'" if quality else config["video"]
    audio = "all" if all_audio else config["audio"]

    temp = config["temp_dir"]
    threads = config["threads"]
    format = config["format"]
    muxer = config["muxer"]
    skip = config["skip_sub"]

    args = [
        m3u8dl,
        manifest,
        "-sv",
        video,
        "-sa",
        audio,
        "-ss",
        "all",
        "-mt",
        "-M",
        f"format={format}:muxer={muxer}:skip_sub={skip}",
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

    args.extend(
        [f"--mux-import", f"path={sub_path}:lang=eng:name='English'"]
    ) if sub_path and skip == "false" else None

    file_path = Path(save_path) / f"{filename}.{format}"

    return args, file_path