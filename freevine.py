import click
import yaml

from helpers import __version__
from helpers.documentation import main_help
from helpers.alias import get_alias
from helpers.utilities import stamp


@click.command(help=main_help)
@click.argument("service", type=str, required=True)
@click.argument("url", type=str, required=True)
@click.option("-q", "--quality", type=str, help="Specify resolution")
@click.option("-a", "--all-audio", is_flag=True, help="Include all audio tracks")
@click.option("-e", "--episode", type=str, help="Download episode(s)")
@click.option("-s", "--season", type=str, help="Download complete season")
@click.option("-c", "--complete", is_flag=True, help="Download complete series")
@click.option("-m", "--movie", is_flag=True, help="Download movie")
@click.option("-t", "--titles", is_flag=True, default=False, help="List all titles")
@click.option("-r", "--remote", is_flag=True, default=False, help="Use remote CDM")
def main(service: bool, **kwargs) -> None:
    stamp(f"Freevine v{__version__}\n")

    with open("config.yaml", "r") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)

    Service = get_alias(service)
    Service(config, **kwargs)


if __name__ == "__main__":
    main()
