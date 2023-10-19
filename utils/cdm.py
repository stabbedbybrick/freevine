import base64

from bs4 import BeautifulSoup

from pywidevine.L3.decrypt.wvdecryptcustom import WvDecrypt
from pywidevine.L3.cdm import deviceconfig

def local_cdm(pssh: str, lic_url: str, client, cert_b64=None) -> str:
    wvdecrypt = WvDecrypt(
        init_data_b64=pssh,
        cert_data_b64=cert_b64,
        device=deviceconfig.device_android_generic,
    )

    response = client.post(url=lic_url, data=wvdecrypt.get_challenge())
    license_b64 = base64.b64encode(response.content)
    wvdecrypt.update_license(license_b64)
    status, content = wvdecrypt.start_process()

    if status:
        return content
    else:
        raise ValueError("Unable to fetch decryption keys")


def remote_cdm(pssh: str, lic_url: str, client) -> str:
    headers = {
        "accept": "application/json, text/plain, */*",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
            (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
    }
    payload = {
        "password": "password",
        "license": lic_url,
        "headers": "connection: keep-alive",
        "pssh": pssh,
        "buildInfo": "",
        "proxy": "",
        "cache": False,
    }
    response = client.post("https://wvclone.fly.dev/wv", headers=headers, json=payload)
    soup = BeautifulSoup(response.text, "html.parser")
    li_tags = soup.find("ol").find_all("li")
    return [x.text for x in li_tags]
