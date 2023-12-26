import json
import logging
import sys
import subprocess
import shlex
from pathlib import Path

import click
import yaml
from rich.console import Console

from utils import __version__
from utils.console import custom_handler
from utils.docs.documentation import main_help
from utils.manager import service_manager
from utils.search.search import search_engine
from utils.utilities import is_url, check_version, get_binary

console = Console()


@click.group()
@click.option("--debug/--no-debug")
def cli(debug: bool):
    logging.basicConfig(
    level=logging.DEBUG if debug else logging.INFO,
    handlers=[custom_handler],
    )

    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    click.echo(f"\n❯_ 𝕗𝕣𝕖𝕖𝕧𝕚𝕟𝕖 {__version__}\n")
    check_version(__version__)


@cli.command()
@click.argument("alias", type=str)
@click.argument("keywords", type=str)
def search(alias: str, keywords: str) -> None:
    """
    Specify one or more services to search using keywords:

    Usage: freevine.py search bbc,all4 "KEYWORDS"
    """
    if keywords is not None:
        search_engine(alias, keywords)


@cli.command(short_help="Download series or movies", help=main_help)
@click.argument("url", type=str, required=False)
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
@click.option("--add-command", multiple=True, default=list, help="Add extra command to N_m3u8DL-RE")
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
def get(**kwargs) -> None:
    url = kwargs.get("episode") if is_url(kwargs.get("episode")) else kwargs.get("url")

    Service, config = service_manager.get_service(url)
    Service(config, **kwargs)


@cli.command()
@click.option("-u", "--username", type=str, required=True, help="Add profile username for a service")
@click.option("-p", "--password", type=str, required=True, help="Add profile password for a service")
@click.option("-s", "--service", type=str, required=True, help="Set service to be used with credentials")
def profile(username: str, password: str, service: str):
    """
    Create a profile with user credentials for a service

    This will create a profile.yaml in service folder, which stores credentials and cache data.
    """

    log = logging.getLogger()

    settings = Path("utils") / "settings"
    with open(settings / "services.json") as f:
        services = json.load(f)

    service = service.casefold()
    match = next(
        (
            item
            for item, key in services.items()
            if service in {alias.casefold() for alias in key["alias"]}
        ),
        None,
    )

    if not match:
        log.error(f"Profile could not be set for {service}")
        sys.exit(1)

    key = services[match]
    profile = Path(key["profile"]).resolve()

    if not profile.is_file():
        log.info(f"Creating new profile for {username}...")
        profile.touch()
        data = {"credentials": {"username": username, "password": password}}
        with open(profile, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)
    else:
        log.info("Updating profile...")
        with open(profile, "r") as f:
            data = yaml.safe_load(f)

        data["credentials"]["username"] = username
        data["credentials"]["password"] = password

        with open(profile, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)

    log.info(f"Profile has been set for {key['alias'][0]}!")


@cli.command()
@click.argument("file", type=click.Path(exists=True), required=True)
def file(file: Path):
    python = get_binary("python", "python3", "py")
    work_dir = Path(__file__).resolve().parent.parent
    freevine = work_dir / "freevine.py"
    with open(file, "r") as f:
        for line in f:
            args = shlex.split(line.rstrip())
            subprocess.run([python, freevine] + args)


cli.add_command(search)
cli.add_command(get)
cli.add_command(profile)
cli.add_command(file)
