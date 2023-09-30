import sys
import re
import importlib
import sys

from pathlib import Path
from urllib.parse import urlparse

from helpers.utilities import info, error


def _services(domain: str):
    supported_services = []

    services = list(Path("services").glob("*.py"))
    for service in services:
        srvc = Path(service).stem
        if len(srvc) == 0 or srvc.startswith("_"):
            continue

        supported_services.append(srvc)

    if domain not in supported_services:
        error("Service not supported")
        sys.exit(1)

    return supported_services


def get_service(url: str):
    parse = urlparse(url)
    netloc = parse.netloc.split(".")

    if len(netloc) == 4:
        domain = netloc[1]
    elif len(netloc) == 3 and netloc[2] == "uk":
        domain = netloc[0]
    elif len(netloc) == 3:
        domain = netloc[1]
    else:
        domain = netloc[0]

    services = _services(domain)

    if any(
        re.search(pattern, parse.path)
        for pattern in [r"\d+-\d+$", r"s\d+e\d+$"]
    ):
        error("Wrong URL format. Use series URL, not episode URL")
        sys.exit(1)

    for service in services:
        if service == domain:
            service_module = importlib.import_module("services." + service)
            srvc = getattr(service_module, service.upper())
            info(srvc.__name__)
            return srvc
