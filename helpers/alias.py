import sys
import re

from urllib.parse import urlparse

from helpers.utilities import stamp, stamperr

from services.uktv import UKTV
from services.itv import ITV
from services.all4 import ALL4
from services.stv import STV
from services.ctv import CTV
from services.roku import ROKU
from services.tubi import TUBI
from services.plutotv import PLUTO
from services.crackle import CRKL


def get_service(url: str):
    parse = urlparse(url)

    if "pluto" in parse.netloc:
        stamp("PlutoTV")
        if "episode" in parse.path:
            stamperr("Wrong URL format. Use series URL, not episode URL")
            sys.exit(1)
        return "PLUTO"

    if "channel4" in parse.netloc:
        stamp("All4")
        if re.search(r"\d+-\d+$", parse.path):
            stamperr("Wrong URL format. Use series URL, not episode URL")
            sys.exit(1)
        return "ALL4"

    if "ctv" in parse.netloc:
        stamp("CTV")
        if re.search(r"s\d+e\d+$", parse.path):
            stamperr("Wrong URL format. Use series URL, not episode URL")
            sys.exit(1)
        return "CTV"

    if "uktvplay" in parse.netloc:
        stamp("UKTV Play")
        if "episode" in parse.path:
            stamperr("Wrong URL format. Use series URL, not episode URL")
            sys.exit(1)
        return "UKTV"

    if "stv" in parse.netloc:
        stamp("STV Player")
        if "episode" in parse.path:
            stamperr("Wrong URL format. Use series URL, not episode URL")
            sys.exit(1)
        return "STV"

    if "tubitv" in parse.netloc:
        stamp("TubiTV")
        if "tv-shows" in parse.path:
            stamperr("Wrong URL format. Use series URL, not episode URL")
            sys.exit(1)
        return "TUBI"

    if "roku" in parse.netloc:
        stamp("The Roku Channel")
        if re.search(r"s\d+-e\d+", parse.path):
            stamperr("Wrong URL format. Use series URL, not episode URL")
            sys.exit(1)
        return "ROKU"

    if "crackle" in parse.netloc:
        stamp("CRACKLE")
        if "?" in parse.path:
            stamperr("Wrong URL format. Use series URL, not episode URL")
            sys.exit(1)
        return "CRKL"

    if "itv" in parse.netloc:
        stamp("ITVX")
        return "ITV"


def get_alias(url: str):
    service = get_service(url)
    aliases = {
        "UKTV": UKTV,
        "ITV": ITV,
        "ALL4": ALL4,
        "STV": STV,
        "CTV": CTV,
        "ROKU": ROKU,
        "TUBI": TUBI,
        "PLUTO": PLUTO,
        "CRKL": CRKL,
    }

    if service in aliases:
        return aliases[service]
    else:
        raise ValueError(f"{service} is not a valid service")
