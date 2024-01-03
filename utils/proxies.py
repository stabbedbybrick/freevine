import subprocess
import re
import random

from utils.utilities import get_binary, contains_ip_address



class Hola:
    def __init__(self) -> None:
        self.executable = get_binary("hola-proxy")
        if not self.executable:
            raise ValueError("Required hola-proxy executable was not found on your system")
        
    def proxy(self, query):
        command = [
            self.executable,
            "-country",
            query,
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
    query = query.lower()

    if len(query) > 2 and contains_ip_address(query):
        return query
    
    if len(query) == 2:
        hola = Hola()
        return hola.proxy(query)