import shutil
import atexit

from pathlib import Path


from utils.commands import cli


@atexit.register
def remove_temp_directory() -> None:
    if Path("tmp").exists():
        shutil.rmtree("tmp")


if __name__ == "__main__":
    cli()
