import shutil

from pathlib import Path

import click
import yaml

from utils import __version__
from utils.documentation import main_help
from utils.services import get_service
from utils.utilities import info, is_url, get_wvd
from utils.search.search import search_engine


@click.command(help=main_help)
@click.argument("url", type=str, required=False)
@click.option("--search", nargs=2, type=str, help="Search service(s) for titles")
@click.option("--threads", type=str, default=False, help="Concurrent download fragments")
@click.option("--format", type=str, default=False, help="Specify file format")
@click.option("--muxer", type=str, default=False, help="Select muxer")
@click.option("--no-mux", is_flag=True, default=False, help="Choose to not mux files")
@click.option("--save-name", type=str, default=False, help="Name of saved file")
@click.option("--save-dir", type=str, default=False, help="Save directory")
@click.option("--sub-only", is_flag=True, default=False, help="Download only subtitles")
@click.option("--sub-no-mux", is_flag=True, default=False, help="Choose to not mux subtitles")
@click.option("--sub-no-fix", is_flag=True, default=False, help="Leave subtitles untouched")
@click.option("--use-shaka-packager", is_flag=True, default=False, help="Use shaka-packager to decrypt")
@click.option("-e", "--episode", type=str, help="Download episode(s)")
@click.option("-s", "--season", type=str, help="Download complete season")
@click.option("-c", "--complete", is_flag=True, help="Download complete series")
@click.option("-m", "--movie", is_flag=True, help="Download movie")
@click.option("-t", "--titles", is_flag=True, default=False, help="List all titles")
@click.option("-i", "--info", is_flag=True, default=False, help="Print title info")
@click.option("-sv", "--select-video", type=str, default=False, help="Select video stream")
@click.option("-sa", "--select-audio", type=str, default=False, help="Select audio stream")
@click.option("-dv", "--drop-video", type=str, default=False, help="Drop video stream")
@click.option("-da", "--drop-audio", type=str, default=False, help="Drop audio stream")
@click.option("-ss", "--select-subtitle", type=str, default=False, help="Select subtitle")
@click.option("-ds", "--drop-subtitle", type=str, default=False, help="Drop subtitle")
def main(search=None, **kwargs) -> None:
    click.echo("")
    info(f"Freevine {__version__}\n")

    if search:
        alias, keywords = search
        search_engine(alias, keywords)
    else:
        wvd = get_wvd(Path.cwd())

        with open("config.yaml", "r") as f:
            main_config = yaml.safe_load(f)

        url = (
            kwargs.get("episode") 
            if is_url(kwargs.get("episode")) 
            else kwargs.get("url")
        )

        Service, srvc_api, srvc_config = get_service(url)
        Service(main_config, srvc_api, srvc_config, wvd, **kwargs)

    shutil.rmtree("tmp") if Path("tmp").exists() else None


if __name__ == "__main__":
    main()