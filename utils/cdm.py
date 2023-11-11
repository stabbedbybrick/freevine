import base64

from bs4 import BeautifulSoup

from utils.utilities import info, error

from pywidevine.pssh import PSSH
from pywidevine.device import Device
from pywidevine.cdm import Cdm


class LocalCDM:
    def __init__(self, wvd=None) -> None:
        
        self.device = Device.load(wvd)
        self.cdm = Cdm.from_device(self.device)
        self.session_id = self.cdm.open()

    def challenge(self, pssh: str) -> bytes:
        return self.cdm.get_license_challenge(self.session_id, PSSH(pssh))

    def parse(self, response) -> list:
        try:
            self.cdm.parse_license(self.session_id, response)
            keys = []
            for key in self.cdm.get_keys(self.session_id):
                if key.type == "CONTENT":
                    keys.append(f"{key.kid.hex}:{key.key.hex()}")
                    
            return keys
        
        except Exception as e:
            error(f"Unable to parse license response {e}")
            exit(1)

        finally:
            self.cdm.close(self.session_id)
