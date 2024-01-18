import logging
import random
import re
import subprocess
import shutil
from pathlib import Path

from utils.utilities import get_binary

log = logging.getLogger()


class Windscribe:
    def __init__(self, config: dict) -> None:
        self.executable = get_binary(
            "windscribe-proxy",
            "windscribe-proxy.windows-amd64",
            "windscribe-proxy.linux-amd64",
        )
        if not self.executable:
            raise ValueError(
                "Required windscribe-proxy executable was not found on your system"
            )

        self.wndstate = Path("utils") / "settings" / "wndstate.json"

        self.username = config["windscribe"].get("username")
        self.password = config["windscribe"].get("password")
        if not self.wndstate.exists() and not self.username and not self.password:
            raise IndexError("Windscribe credentials must be provided")

    def proxy(self, query):
        command = [self.executable, "-list-proxies"]
        command.extend(
            ["-username", self.username]
        ) if not self.wndstate.exists() else None
        command.extend(
            ["-password", self.password]
        ) if not self.wndstate.exists() else None
        command.extend(
            ["-state-file", self.wndstate]
        ) if self.wndstate.exists() else None

        output = subprocess.run(command, capture_output=True, text=True)
        if output.returncode != 0:
            raise ConnectionError(f"{output.stderr}")
        
        if Path("wndstate.json").exists():
            shutil.move(Path("wndstate.json"), Path("utils") / "settings")

        username, password = re.search(
            r"Proxy login: (.*)\nProxy password: (.*)", output.stdout
        ).groups()

        hostnames = re.findall(r"[a-zA-Z0-9.-]+\.totallyacdn\.com", output.stdout)
        servers = [hostname for hostname in hostnames if hostname.startswith(query)]
        if not servers:
            raise ValueError(f"Proxy server for {query.upper()} was not found")

        proxies = []
        for server in servers:
            proxies.append(f"https://{username}:{password}@{server}:443")

        proxy = random.choice(proxies)
        return proxy


class Hola:
    def __init__(self) -> None:
        self.executable = get_binary(
            "hola-proxy", "hola-proxy.windows-amd64", "hola-proxy.linux-amd64"
        )
        if not self.executable:
            raise ValueError(
                "Required hola-proxy executable was not found on your system"
            )

    def proxy(self, query):
        command = [
            self.executable,
            "-country",
            query,
            "-proxy-type",
            "lum",  # residential
            "-list-proxies",
        ]
        output = subprocess.run(command, capture_output=True, text=True)
        if output.returncode != 0:
            raise ConnectionError(f"{output.stderr}")

        username, password = re.search(
            r"Login: (.*)\nPassword: (.*)", output.stdout
        ).groups()

        servers = re.findall(r"(zagent.*)", output.stdout)
        proxies = []
        for server in servers:
            (
                host,
                ip_address,
                direct,
                peer,
                hola,
                trial,
                trial_peer,
                vendor,
            ) = server.split(",")
            proxies.append(f"http://{username}:{password}@{ip_address}:{peer}")

        proxy = random.choice(proxies)
        return proxy

    # TODO
    # def countries():
    #     pass


def get_proxy(cli: object, location: str = None) -> str:
    client = cli.config.get("proxy")
    if not client:
        raise IndexError("A proxy client must be set in config file")
    client = client.lower()

    if client == "basic":
        url = location if location else cli.proxy

        log.info(f"+ Adding basic proxy location: {url}")

        return url

    elif client == "hola":
        iso = location if location else cli.proxy
        if not len(iso) == 2:
            raise ValueError("Country codes should only be two letters")

        log.info(f"+ Adding Hola proxy location: {iso.upper()}")

        query = iso.lower()
        query = "gb" if query == "uk" else query
        hola = Hola()
        return hola.proxy(query)

    elif client == "windscribe":
        iso = location if location else cli.proxy
        if not len(iso) == 2:
            raise ValueError("Country codes should only be two letters")

        log.info(f"+ Adding Windscribe proxy location: {iso.upper()}")

        query = iso.lower()
        windscribe = Windscribe(cli.config)
        return windscribe.proxy(query)
