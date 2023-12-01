import shutil

from pathlib import Path

import click
import yaml

from utils import __version__
from utils.documentation import main_help
from utils.services import get_service
from utils.utilities import info, check_version
from utils.search.search import search_engine
from utils.commands import commands


@click.command(help=main_help)
@commands
def main(search=None, **kwargs) -> None:
    click.echo("")
    info(f"Freevine {__version__}\n")
    check_version(__version__)

    if search:
        search_engine(search)
    else:
        with open("config.yaml", "r") as f:
            main_config = yaml.safe_load(f)

        Service, service_api, service_config = get_service(kwargs.get("url"))
        Service(main_config, service_api, service_config, **kwargs)

    shutil.rmtree("tmp") if Path("tmp").exists() else None


if __name__ == "__main__":
    main()