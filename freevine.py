import shutil

from pathlib import Path

import click
import yaml

from utils import __version__
from utils.documentation import main_help
from utils.services import get_service
from utils.utilities import info
from utils.search.search import search_engine


@click.command(help=main_help)
@click.option("--search", nargs=2, type=str, help="Search service(s) for titles")
@click.argument("url", type=str, required=False)
@click.option("-q", "--quality", type=str, help="Specify resolution")
@click.option("-a", "--all-audio", is_flag=True, help="Include all audio tracks")
@click.option("-e", "--episode", type=str, help="Download episode(s)")
@click.option("-s", "--season", type=str, help="Download complete season")
@click.option("-c", "--complete", is_flag=True, help="Download complete series")
@click.option("-m", "--movie", is_flag=True, help="Download movie")
@click.option("-t", "--titles", is_flag=True, default=False, help="List all titles")
@click.option("-i", "--info", is_flag=True, default=False, help="Print title info")
@click.option("-r", "--remote", is_flag=True, default=False, help="Use remote CDM")
@click.option("--subtitles", is_flag=True, default=False, help="Download only subtitles")
def main(search=None, **kwargs) -> None:
    click.echo("")
    info(f"Freevine {__version__}\n")

    if search:
        alias, keywords = search
        search_engine(alias, keywords)
    else:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)

        Service = get_service(kwargs.get("url"))
        Service(config, **kwargs)

    shutil.rmtree("tmp") if Path("tmp").exists() else None


if __name__ == "__main__":
    main()