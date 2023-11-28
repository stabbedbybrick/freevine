import shutil
import re

from utils.utilities import (
    info,
    set_range,
    is_url,
    is_title_match,
    general_error,
)


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

        episode = next(
            (i for i in series if self.episode.lower() in str(i).lower()), None
        )

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
            if any(i.lower() in str(episode).lower() for i in episode_range):
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
            if any(i.lower() in str(episode).lower() for i in episode_mix):
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


def get_downloads(stream: object) -> tuple:
    if stream.url and not any(
        [stream.episode, stream.season, stream.complete, stream.movie, stream.titles]
    ):
        general_error("URL is missing an argument. See --help for more information")

    if (
        hasattr(stream, "episode_re")
        and is_url(stream.episode)
        and is_title_match(stream.episode, stream.episode_re)
    ):
        downloads, title = stream.get_episode_from_url(stream.episode)
    elif is_url(stream.episode):
        downloads, title = stream.get_episode_from_url(stream.episode)
    else:
        options = Options(stream)
        content, title = stream.get_content(stream.url)

        if stream.episode:
            downloads = options.get_episode(content)
        if stream.season:
            downloads = options.get_season(content)
        if stream.complete:
            downloads = options.get_complete(content)
        if stream.movie:
            downloads = options.get_movie(content)
        if stream.titles:
            options.list_titles(content)

    if not downloads:
        general_error("Requested data returned empty. See --help for more information")

    return downloads, title
