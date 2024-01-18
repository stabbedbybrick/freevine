import yaml
import httpx
from rich.console import Console

from utils.search.api import _dict, _parse
from utils.proxies import get_proxy

console = Console()


class Config:
    def __init__(self, alias: str, keywords: str, proxy: str) -> None:
        if alias:
            alias = alias.upper()
        if keywords:
            keywords = keywords.lower()

        with open("config.yaml", "r") as f:
            self.config = yaml.safe_load(f)

        if proxy != "False":
            uri = get_proxy(config=self.config, location=proxy)
            self.client = httpx.Client(proxies={"http://": uri, "https://": uri})
        else:
            self.client = httpx.Client(
                headers={"user-agent": "Chrome/119.0.0.0 Safari/537.36"}
            )

        self.alias = [alias]
        self.keywords = keywords

        if "," in self.alias[0]:
            self.alias = [x for x in self.alias[0].split(",")]

        self.services = _dict(self.keywords)


def search_get(search: object, service: dict):
    url = service["url"]
    params = service.get("params", {})
    search.client.headers.update(service.get("header", {}))

    cookies = service.get("collect", {})

    r = search.client.get(url, cookies=cookies, params=params)

    if not r.is_success:
        return None
    try:
        return r.json()
    except:
        return None


def search_post(search: object, service: dict):
    url = service["url"]
    search.client.headers.update(service.get("header", {}))
    payload = service.get("payload", {})

    if service.get("token"):
        try:
            token = search.client.get(service["token"]).json()["csrf"]
            search.client.headers.update({"csrf-token": token})
        except:
            return None

    r = search.client.post(url, cookies=search.client.cookies, json=payload)

    if not r.is_success:
        return None
    try:
        return r.json()
    except:
        return None


def search_engine(alias: str, keywords: str, proxy: str):
    # alias, keywords = search
    cfg = Config(alias, keywords, proxy)

    services = [
        service
        for service in cfg.services
        if any(
            i in service_alias for i in cfg.alias for service_alias in service["alias"]
        )
    ]

    queries = []

    with console.status("Searching..."):
        for service in services:
            if service["method"] == "GET":
                query = search_get(cfg, service)
            if service["method"] == "POST":
                query = search_post(cfg, service)

            results = _parse(query, service, cfg.client)
            queries.append(results)

    queries = [results for results in queries]

    num_matches = 5 if len(services) >= 2 else 10

    matches = [
        [result for result in query if service["name"] in result][:num_matches]
        for service in services
        for query in queries
    ]
    for match in matches:
        for result in match:
            console.print(result)
