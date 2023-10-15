import re
import uuid
import httpx

from rich.console import Console
from helpers.dict import _search

console = Console()


class Search:
    def __init__(self, alias: str, keywords: str) -> None:
        if alias:
            alias = alias.upper()
        if keywords:
            keywords = keywords.lower()

        self.client = httpx.Client(
            headers={
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/118.0.0.0 Safari/537.36"
                ),
            }
        )
        self.alias = [alias]
        self.keywords = keywords

        if "," in self.alias[0]:
            self.alias = [x for x in self.alias[0].split(",")]

        self.services = _search(self.keywords)


def sanitize(title: str) -> str:
    title = title.lower()
    title = title.replace("&", "and")
    title = re.sub(r"[:;/()]", "", title)
    title = re.sub(r"[ ]", "-", title)
    title = re.sub(r"[\\*!?¿,'\"<>|$#`’]", "", title)
    title = re.sub(rf"[{'.'}]{{2,}}", ".", title)
    title = re.sub(rf"[{'_'}]{{2,}}", "_", title)
    title = re.sub(rf"[{'-'}]{{2,}}", "-", title)
    title = re.sub(rf"[{' '}]{{2,}}", " ", title)
    return title


def search_get(search: object, service: dict):
    url = service["url"]
    params = service.get("params", {})
    search.client.headers.update(service.get("header", {}))

    cookies = service.get("collect", {})

    return search.client.get(url, cookies=cookies, params=params).json()


def search_post(search: object, service: dict):
    url = service["url"]
    search.client.headers.update(service.get("header", {}))
    payload = service.get("payload", {})

    if service.get("token"):
        token = search.client.get(service["token"]).json()["csrf"]
        search.client.headers.update({"csrf-token": token})

    return search.client.post(url, cookies=search.client.cookies, json=payload).json()


def parse_results(query: dict, service: dict, client=None):
    template = """
    [bold]{service}[/bold]
    Title: {title}
    Type: {type}
    Synopsis: {synopsis}
    Link: {url}
    """

    results = []

    if service["name"] == "BBC iPlayer":
        for field in query["results"]:
            results.append(
                template.format(
                    service=service["name"],
                    title=field["title"],
                    synopsis=field["synopsis"],
                    type="programme" if field["type"] == "brand" else field["type"],
                    url=field["url"],
                )
            )

    if service["name"] == "ALL4":
        for field in query["results"]:
            results.append(
                template.format(
                    service=service["name"],
                    title=field["brand"]["title"],
                    synopsis=field["brand"]["description"],
                    type="",
                    url=field["brand"]["href"],
                )
            )

    if service["name"] == "My5":
        link = "https://www.channel5.com/show/"

        for field in query["shows"]:
            results.append(
                template.format(
                    service=service["name"],
                    title=field["title"],
                    synopsis=field.get("s_desc"),
                    type=field.get("genre"),
                    url=f"{link}{field['f_name']}",
                )
            )

    if service["name"] == "ITV":
        link = "https://www.itv.com/watch"

        for field in query["results"]:
            special = field["data"].get("specialTitle")
            standard = field["data"].get("programmeTitle")
            film = field["data"].get("filmTitle")
            title = special if special else standard if standard else film

            slug = sanitize(title)

            _id = field["data"]["legacyId"]["apiEncoded"]
            _id = "_".join(_id.split("_")[:2]).replace("_", "a")
            _id = re.sub(r"a000\d+", "", _id)

            results.append(
                template.format(
                    service=service["name"],
                    title=title,
                    synopsis=field["data"]["synopsis"],
                    type=field["entityType"],
                    url=f"{link}/{slug}/{_id}",
                )
            )

    if service["name"] == "STV Player":
        for field in query["records"]["page"]:
            results.append(
                template.format(
                    service=service["name"],
                    title=field["title"],
                    synopsis=field.get("resultDescriptionTx"),
                    type="programme",
                    url=field["url"],
                )
            )

    if service["name"] == "CRACKLE":
        link = "https://www.crackle.com/details"

        for field in query["data"]["items"]:
            results.append(
                template.format(
                    service=service["name"],
                    title=field["metadata"][0]["title"],
                    synopsis=field["metadata"][0].get("longDescription"),
                    type=field.get("type"),
                    url=f"{link}/{field['id']}/{field['metadata'][0]['slug']}",
                )
            )

    if service["name"] == "CTV":
        link = "https://www.ctv.ca"

        for field in query["data"]["searchMedia"]["page"]["items"]:
            results.append(
                template.format(
                    service=service["name"],
                    title=field["title"],
                    synopsis=None,
                    type=field["path"].split("/")[1],
                    url=f"{link}{field['path']}",
                )
            )

    if service["name"] == "UKTV Play":
        link = "https://uktvplay.co.uk/shows/{slug}/watch-online"

        for field in query:
            results.append(
                template.format(
                    service=service["name"],
                    title=field["name"],
                    synopsis=field.get("synopsis"),
                    type=field.get("type"),
                    url=link.format(slug=field["slug"]),
                )
            )

    if service["name"] == "PlutoTV":
        params = {
            "appName": "web",
            "appVersion": "na",
            "clientID": str(uuid.uuid1()),
            "clientModelNumber": "na",
        }
        token = client.get("https://boot.pluto.tv/v4/start", params=params).json()[
            "sessionToken"
        ]

        client.headers.update({"Authorization": f"Bearer {token}"})

        query = client.get(service["url"], params=service["params"]).json()

        link = "https://pluto.tv/en/on-demand/{type}/{id}/details"

        for field in query["data"]:
            if "timeline" not in field["type"]:
                results.append(
                    template.format(
                        service=service["name"],
                        title=field["name"],
                        synopsis=field.get("synopsis"),
                        type=field["type"],
                        url=link.format(
                            type="movies" if field["type"] == "movie" else "series",
                            id=field["id"],
                        ),
                    )
                )
    if service["name"] == "The Roku Channel":
        link = "https://therokuchannel.roku.com/details/{id}/{title}"

        for field in query["view"]:
            _desc = field["content"].get("descriptions")
            results.append(
                template.format(
                    service=service["name"],
                    title=field["content"]["title"],
                    synopsis=_desc["250"]["text"] if _desc.get("250") else None,
                    type=field["content"].get("type"),
                    url=link.format(
                        id=field["content"]["meta"]["id"],
                        title=sanitize(field["content"]["title"]),
                    ),
                )
            )

    if service["name"] == "TubiTV":
        link = "https://tubitv.com/{type}/{id}/{title}"

        for field in query:
            type = (
                "series"
                if field["type"] == "s"
                else "movies"
                if field["type"] == "v"
                else field["type"]
            )
            results.append(
                template.format(
                    service=service["name"],
                    title=field["title"],
                    synopsis=field.get("description"),
                    type=type,
                    url=link.format(
                        type=type,
                        id=field["id"],
                        title=sanitize(field["title"]),
                    ),
                )
            )

    return results


def search_engine(alias: str, keywords: str):
    search = Search(alias, keywords)

    services = [
        service
        for service in search.services
        if any(
            i in service_alias
            for i in search.alias
            for service_alias in service["alias"]
        )
    ]

    queries = []

    with console.status("Searching..."):
        for service in services:
            if service["method"] == "GET":
                query = search_get(search, service)
            if service["method"] == "POST":
                query = search_post(search, service)

            results = parse_results(query, service, search.client)
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
