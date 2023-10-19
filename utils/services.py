import sys
import re
import importlib.util
import sys

from pathlib import Path
from urllib.parse import urlparse

from utils.utilities import info, error


def _services():
    services = Path("services")

    supported_services = {
        "www.bbc.co.uk": {
            "name": "BBC",
            "alias": "BBC iPlayer",
            "path": services / "bbciplayer.py",
        },
        "www.channel4.com": {
            "name": "CHANNEL4",
            "alias": "ALL4",
            "path": services / "channel4.py",
        },
        "www.channel5.com": {
            "name": "CHANNEL5",
            "alias": "My5 TV",
            "path": services / "channel5.py",
        },
        "www.crackle.com": {
            "name": "CRACKLE",
            "alias": "CRACKLE",
            "path": services / "crackle.py",
        },
        "www.ctv.ca": {
            "name": "CTV",
            "alias": "CTV",
            "path": services / "ctv.py",
        },
        "www.itv.com": {
            "name": "ITV",
            "alias": "ITVX",
            "path": services / "itv.py",
        },
        "pluto.tv": {
            "name": "PLUTO",
            "alias": "PlutoTV",
            "path": services / "pluto.py",
        },
        "therokuchannel.roku.com": {
            "name": "ROKU",
            "alias": "The Roku Channel",
            "path": services / "roku.py",
        },
        "player.stv.tv": {
            "name": "STV",
            "alias": "STV Player",
            "path": services / "stv.py",
        },
        "tubitv.com": {
            "name": "TUBITV",
            "alias": "TubiTV",
            "path": services / "tubitv.py",
        },
        "uktvplay.co.uk": {
            "name": "UKTVPLAY",
            "alias": "UKTV Play",
            "path": services / "uktvplay.py",
        },
    }

    return supported_services


def get_service(url: str):
    supported = _services()

    find_service = next(
        (
            info
            for service, info in supported.items()
            if service == urlparse(url).netloc
        ),
        None,
    )

    if find_service is None:
        error("Service is not supported")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location(
        find_service["name"], str(find_service["path"])
    )
    service_module = importlib.util.module_from_spec(spec)
    sys.modules[find_service["name"]] = service_module
    spec.loader.exec_module(service_module)
    srvc = getattr(service_module, find_service["name"])
    info(find_service["alias"])
    return srvc
