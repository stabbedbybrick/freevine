import subprocess
import re
import random
import logging
import sys

from utils.utilities import get_binary, contains_ip_address



class Hola:
    def __init__(self) -> None:
        self.executable = get_binary("hola-proxy", "hola-proxy.windows-amd64", "hola-proxy.linux-amd64")
        if not self.executable:
            raise ValueError("Required hola-proxy executable was not found on your system")
        
    def proxy(self, query):
        command = [
            self.executable,
            "-country", query,
            "-proxy-type", "lum", # residential
            "-list-proxies"
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
            host, ip_address, direct, peer, hola, trial, trial_peer, vendor = server.split(",")
            proxies.append(f"http://{username}:{password}@{ip_address}:{peer}")

        proxy = random.choice(proxies)
        return proxy

    # TODO
    # def countries():
    #     pass

def get_proxy(query: str) -> str:
    log = logging.getLogger()

    if len(query) > 2 and contains_ip_address(query):
        return query
    
    elif len(query) == 2:
        log.info(f"+ Adding {query} proxy")
        query = query.lower()
        query = "gb" if query == "uk" else query
        hola = Hola()
        return hola.proxy(query)
    
    else:
        log.error("Unsupported input for proxy")
        sys.exit(1)