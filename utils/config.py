from pathlib import Path
from typing import Any, Optional

import httpx

from rich.console import Console


class Config:
    def __init__(
        self, 
        config: Any, 
        url: str,
        quality: Optional[str] = None,
        remote: Optional[bool] = None,
        titles: Optional[bool] = None,
        info: Optional[bool] = None,
        episode: Optional[str] = None,
        season: Optional[str] = None,
        movie: Optional[bool] = None,
        complete: Optional[bool] = None,
        all_audio: Optional[bool] = None,
        subtitles: Optional[bool] = None,
    ) -> None:
        
        if episode:
            episode = episode.upper()
        if season:
            season = season.upper()
        if quality:
            quality = quality.rstrip("p")
        
        self.config = config
        self.url = url
        self.quality = quality
        self.remote = remote
        self.titles = titles
        self.info = info
        self.episode = episode
        self.season = season
        self.movie = movie
        self.complete = complete
        self.all_audio = all_audio
        self.sub_only = subtitles

        self.console = Console()

        self.tmp = Path("tmp")
        self.tmp.mkdir(parents=True, exist_ok=True)

        self.client = httpx.Client(
            headers={
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/118.0.0.0 Safari/537.36"
                ),
            },
            timeout=10.0
        )