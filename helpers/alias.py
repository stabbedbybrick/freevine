from services.uktv import UKTV
from services.itv import ITV
from services.all4 import ALL4
from services.stv import STV
from services.ctv import CTV
from services.roku import ROKU
from services.tubi import TUBI
from services.plutotv import PLUTO


def get_alias(service: str):
    service = service.upper()
    aliases = {
        "UKTV": UKTV,
        "ITV": ITV,
        "ALL4": ALL4,
        "STV": STV,
        "CTV": CTV,
        "ROKU": ROKU,
        "TUBI": TUBI,
        "PLUTO": PLUTO,
    }

    if service in aliases:
        return aliases[service]
    else:
        raise ValueError(f"{service} is not a valid service")
