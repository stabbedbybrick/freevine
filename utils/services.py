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
        "iview.abc.net.au": {
            "name": "ABC",
            "alias": "ABC iView",
            "path": services / "abciview" / "abciview.py",
            "api": services / "abciview" / "api.yaml",
            "config": services / "abciview" / "config.yaml",
        },
        "www.bbc.co.uk": {
            "name": "BBC",
            "alias": "BBC iPlayer",
            "path": services / "bbciplayer" / "bbciplayer.py",
            "api": services / "bbciplayer" / "api.yaml",
            "config": services / "bbciplayer" / "config.yaml",
        },
        "www.channel4.com": {
            "name": "CHANNEL4",
            "alias": "ALL4",
            "path": services / "channel4" / "channel4.py",
            "api": services / "channel4" / "api.yaml",
            "config": services / "channel4" / "config.yaml",
        },
        "www.channel5.com": {
            "name": "CHANNEL5",
            "alias": "My5 TV",
            "path": services / "channel5" / "channel5.py",
            "api": services / "channel5" / "api.yaml",
            "config": services / "channel5" / "config.yaml",
        },
        "www.crackle.com": {
            "name": "CRACKLE",
            "alias": "CRACKLE",
            "path": services / "crackle" / "crackle.py",
            "api": services / "crackle" / "api.yaml",
            "config": services / "crackle" / "config.yaml",
        },
        "www.ctv.ca": {
            "name": "CTV",
            "alias": "CTV",
            "path": services / "ctv" / "ctv.py",
            "api": services / "ctv" / "api.yaml",
            "config": services / "ctv" / "config.yaml",
        },
        "gem.cbc.ca": {
            "name": "CBC",
            "alias": "CBC Gem",
            "path": services / "cbc" / "cbc.py",
            "api": services / "cbc" / "api.yaml",
            "config": services / "cbc" / "config.yaml",
        },
        "www.itv.com": {
            "name": "ITV",
            "alias": "ITVX",
            "path": services / "itv" / "itv.py",
            "api": services / "itv" / "api.yaml",
            "config": services / "itv" / "config.yaml",
        },
        "pluto.tv": {
            "name": "PLUTO",
            "alias": "PlutoTV",
            "path": services / "pluto" / "pluto.py",
            "api": services / "pluto" / "api.yaml",
            "config": services / "pluto" / "config.yaml",
        },
        "therokuchannel.roku.com": {
            "name": "ROKU",
            "alias": "The Roku Channel",
            "path": services / "roku" / "roku.py",
            "api": services / "roku" / "api.yaml",
            "config": services / "roku" / "config.yaml",
        },
        "player.stv.tv": {
            "name": "STV",
            "alias": "STV Player",
            "path": services / "stv" / "stv.py",
            "api": services / "stv" / "api.yaml",
            "config": services / "stv" / "config.yaml",
        },
        "tubitv.com": {
            "name": "TUBITV",
            "alias": "TubiTV",
            "path": services / "tubi" / "tubitv.py",
            "api": services / "tubi" / "api.yaml",
            "config": services / "tubi" / "config.yaml",
        },
        "uktvplay.co.uk": {
            "name": "UKTVPLAY",
            "alias": "UKTV Play",
            "path": services / "uktvplay" / "uktvplay.py",
            "api": services / "uktvplay" / "api.yaml",
            "config": services / "uktvplay" / "config.yaml",
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
    api = find_service.get("api")
    config = find_service.get("config")
    info(find_service["alias"])
    return srvc, api, config
