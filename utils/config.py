import logging
import re
from pathlib import Path
from typing import Any, Optional

import requests
from rich.console import Console

from utils.utilities import is_url
from utils.proxies import get_proxy


class Config:
    """Config class that gets inherited by the service"""

    def __init__(
        self,
        config: Any,
        wvd: Path = None,
        url: str = None,
        remote: Optional[bool] = None,
        titles: Optional[bool] = None,
        info: Optional[bool] = None,
        quality: Optional[str] = None,
        episode: Optional[str] = None,
        season: Optional[str] = None,
        movie: Optional[bool] = None,
        complete: Optional[bool] = None,
        sub_only: Optional[bool] = None,
        sub_no_mux: Optional[bool] = None,
        sub_no_fix: Optional[bool] = None,
        select_video: Optional[str] = None,
        select_audio: Optional[str] = None,
        drop_video: Optional[str] = None,
        drop_audio: Optional[str] = None,
        select_subtitle: Optional[str] = None,
        drop_subtitle: Optional[str] = None,
        threads: Optional[str] = None,
        format: Optional[str] = None,
        muxer: Optional[str] = None,
        use_shaka_packager: Optional[bool] = None,
        no_mux: Optional[bool] = None,
        save_dir: Optional[str] = None,
        save_name: Optional[str] = None,
        add_command: Optional[list] = None,
        slowdown: Optional[int] = None,
        force_numbering: Optional[list] = None,
        no_cache: Optional[bool] = None,
        proxy: Optional[str] = None,
        # skip_download: Optional[bool] = None,
    ) -> None:
        if episode and not is_url(episode):
            episode = episode.upper()
        if season:
            season = season.upper()

        if "res" in config["video"]["select"]:
            quality = re.search(r"res=(\d+)", config["video"]["select"]).group(1)
        if "res" in select_video:
            quality = re.search(r"res=(\d+)", select_video).group(1)

        self.config = config
        self.url = url
        self.wvd = wvd
        self.quality = quality
        self.remote = remote
        self.titles = titles
        # self.info = info
        self.episode = episode
        self.season = season
        self.movie = movie
        self.complete = complete
        self.sub_only = sub_only
        self.sub_no_mux = sub_no_mux
        self.sub_no_fix = sub_no_fix
        self.select_video = select_video
        self.select_audio = select_audio
        self.drop_video = drop_video
        self.drop_audio = drop_audio
        self.select_subtitle = select_subtitle
        self.drop_subtitle = drop_subtitle
        self.threads = threads
        self.format = format
        self.muxer = muxer
        self.use_shaka_packager = use_shaka_packager
        self.no_mux = no_mux
        self.save_dir = save_dir
        self.save_name = save_name
        self.add_command = add_command
        self.slowdown = slowdown
        self.skip_download = info
        self.force_numbering = force_numbering
        self.no_cache = no_cache

        self.console = Console()

        self.tmp = Path("tmp")
        self.tmp.mkdir(parents=True, exist_ok=True)

        self.log = logging.getLogger()

        self.client = requests.Session()
        self.client.timeout = 10.0
        self.client.headers.update(
            {
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/118.0.0.0 Safari/537.36"
                ),
            }
        )

        if proxy != "False":
            uri = get_proxy(proxy)
            self.client.proxies = {"http": uri, "https": uri}
