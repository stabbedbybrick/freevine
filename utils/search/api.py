import re
import uuid


def _sanitize(title: str) -> str:
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


def _dict(keywords: str):
    return [
        {
            "name": "BBC iPlayer",
            "alias": ["BBC", "IPLAYER", "BBCIPLAYER"],
            "url": "https://search.api.bbci.co.uk/formula/iplayer-ibl-root",
            "params": {
                "q": f"{keywords}",
                "apikey": "D2FgtcTxGqqIgLsfBWTJdrQh2tVdeaAp",
            },
            "method": "GET",
        },
        {
            "name": "ALL4",
            "alias": ["ALL4", "CHANNEL4", "C4", "CH4"],
            "url": "https://all4nav.channel4.com/v1/api/search",
            "params": {
                "expand": "default",
                "q": f"{keywords}",
                "limit": "100",
                "offset": "0",
            },
            "method": "GET",
        },
        {
            "name": "My5",
            "alias": ["MY5", "CHANNEL5", "C5", "CH5"],
            "url": "https://corona.channel5.com/shows/search.json",
            "params": {
                "platform": "my5desktop",
                "friendly": "1",
                "query": f"{keywords}",
            },
            "method": "GET",
        },
        {
            "name": "CRACKLE",
            "alias": ["CRACKLE", "CRKL"],
            "url": f"https://prod-api.crackle.com/contentdiscovery/search/{keywords}",
            "header": {"x-crackle-platform": "5FE67CCA-069A-42C6-A20F-4B47A8054D46"},
            "params": {
                "useFuzzyMatching": "false",
                "enforcemediaRights": "true",
                "pageNumber": "1",
                "pageSize": "20",
                "contentType": "Channels",
                "searchFields": "Title,Cast",
            },
            "method": "GET",
        },
        {
            "name": "CTV",
            "alias": ["CTV"],
            "url": "https://www.ctv.ca/space-graphql/apq/graphql",
            "payload": {
                "operationName": "searchMedia",
                "variables": {"title": f"{keywords}"},
                "query": """
                        query searchMedia($title: String!) {searchMedia(titleMatches: $title) {
                        ... on Medias {page {items {title\npath}}}}}, """,
            },
            "method": "POST",
        },
        {
            "name": "SVTPlayer",
            "alias": ["SVTPLAYER", "SVT", "SVT Player"],
            "url": "https://contento-search.svt.se/graphql",
            "params": {
                "operationName": "SearchPage",
                "variables": f'{{"abTestVariants":[],"query":"{keywords}"}}',
                "extensions": '{"persistedQuery":{"sha256Hash":"65a6875f886e590a917da4c90ac7ae0249ab0025ffc6d414b058801dc8f06d9d","version":1}}',
                "ua": "svtplaywebb-render-prod-client",
            },
            "method": "GET",
        },
        {
            "name": "CBC Gem",
            "alias": ["CBC", "GEM"],
            "url": "https://services.radio-canada.ca/ott/catalog/v1/gem/search",
            "params": {
                "device": "web",
                "pageNumber": "1",
                "pageSize": "20",
                "term": f"{keywords}",
            },
            "method": "GET",
        },
        {
            "name": "ITV",
            "alias": ["ITV", "ITVX"],
            "url": "https://textsearch.prd.oasvc.itv.com/search",
            "params": {
                "broadcaster": "itv",
                "featureSet": "clearkey,outband-webvtt,hls,aes,playready,widevine,fairplay,bbts,progressive,hd,rtmpe",
                "onlyFree": "false",
                "platform": "dotcom",
                "query": f"{keywords}",
            },
            "method": "GET",
        },
        {
            "name": "PlutoTV",
            "alias": ["PLUTOTV", "PLUTO"],
            "url": "https://service-media-search.clusters.pluto.tv/v1/search",
            "params": {
                "q": f"{keywords}",
                "limit": "100",
            },
            "method": "GET",
        },
        {
            "name": "The Roku Channel",
            "alias": ["ROKU", "ROKUCHANNEL", "THEROKUCHANNEL"],
            "url": "https://therokuchannel.roku.com/api/v1/search",
            "token": "https://therokuchannel.roku.com/api/v1/csrf",
            "payload": {
                "query": f"{keywords}",
            },
            "method": "POST",
        },
        {
            "name": "STV Player",
            "alias": ["STV", "STVPLAYER"],
            "url": "https://search-api.swiftype.com/api/v1/public/engines/suggest.json",
            "params": None,
            "method": "POST",
            "payload": {
                "engine_key": "S1jgssBHdk8ZtMWngK_y",
                "per_page": 10,
                "page": 1,
                "fetch_fields": {
                    "page": ["title", "body", "resultDescriptionTx", "url"]
                },
                "search_fields": {"page": ["title^3", "body"]},
                "q": f"{keywords}",
                "spelling": "strict",
            },
        },
        {
            "name": "TubiTV",
            "alias": ["TUBI"],
            "url": f"https://tubitv.com/oz/search/{keywords}",
            "collect": {
                "connect.sid": "s%3Al5xcbiTUygyjM1olYs6zqLwQuqEtdTuU.8Z%2B0IcWqpmn4De9thyYAkjJ7rFe9FIj%2FmHOQxtXnbxs"
            },
            "params": {
                "isKidsMode": "false",
                "useLinearHeader": "true",
                "isMobile": "false",
            },
            "method": "GET",
        },
        {
            "name": "UKTV Play",
            "alias": ["UKTV", "UKTVP", "UKTVPLAY"],
            "url": "https://vschedules.uktv.co.uk/vod/search/",
            "params": {
                "q": f"{keywords}",
            },
            "method": "GET",
        },
        {
            "name": "ABC iView",
            "alias": ["ABC", "IVIEW", "IV"],
            "url": (
                "https://y63q32nvdl-1.algolianet.com/1/indexes/*/queries?x-algolia-agent=Algolia"
                "%20for%20JavaScript%20(4.9.1)%3B%20Browser%20(lite)%3B%20react%20(17.0.2)%3B%20"
                "react-instantsearch%20(6.30.2)%3B%20JS%20Helper%20(3.10.0)&x-"
                "algolia-api-key=bcdf11ba901b780dc3c0a3ca677fbefc&x-algolia-application-id=Y63Q32NVDL"
            ),
            "payload": {
                "requests": [
                    {
                        "indexName": "ABC_production_iview_web",
                        "params": f"query={keywords}&tagFilters=&userToken=anonymous-74be3cf1-1dc7-4fa1-9cff-19592162db1c",
                    }
                ],
            },
            "method": "POST",
        },
        {
            "name": "The CW",
            "alias": ["CW", "CWTV", "THECW"],
            "url": "https://www.cwtv.com/search/",
            "params": {
                "q": f"{keywords}".replace(" ", "%2520"),
                "format": "json2",
                "service": "t",
            },
            "method": "GET",
        },
        {
            "name": "Plex",
            "alias": ["PLEX", "PLEX.TV"],
            "url": f"https://discover.provider.plex.tv/library/search?searchTypes=livetv,movies,people,tv&searchProviders=discover,plexAVOD,plexFAST&includeMetadata=1&filterPeople=1&limit=10&query={keywords}",
            "header": {
                "authority": "discover.provider.plex.tv",
                "accept": "application/json",
                "content-type": "application/json",
                "origin": "https://watch.plex.tv",
                "referer": "https://watch.plex.tv/",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                "x-plex-client-identifier": "e3109fe5-d10c-4d8a-b71b-24f60c2c550b",
                "x-plex-language": "en",
                "x-plex-product": "Plex Mediaverse",
                "x-plex-provider-version": "6.5.0",
            },
            "method": "GET",
        },
        {
            "name": "TVNZ",
            "alias": ["TVNZ"],
            "url": "https://apis-public-prod.tech.tvnz.co.nz/api/v1/web/play/search",
            "params": {
                "q": f"{keywords}",
                "includeTypes": [
                    "show",
                    "channel",
                    "category",
                    "tvguide",
                    "hub",
                    "sportVideo",
                ],
            },
            "method": "GET",
        },
    ]


def _parse(query: dict, service: dict, client=None):
    template = """
    [bold]{service}[/bold]
    Title: {title}
    Type: {type}
    Synopsis: {synopsis}
    Link: {url}
    """

    results = []

    if service["name"] == "BBC iPlayer":
        if query:
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
        if query:
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

        if query:
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

        if query:
            for field in query["results"]:
                special = field["data"].get("specialTitle")
                standard = field["data"].get("programmeTitle")
                film = field["data"].get("filmTitle")
                title = special if special else standard if standard else film

                slug = _sanitize(title)

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
        if query:
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

        if query:
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

        if query:
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

    if service["name"] == "CBC Gem":
        link = "https://gem.cbc.ca/"

        if query:
            for field in query["result"]:
                results.append(
                    template.format(
                        service=service["name"],
                        title=field["title"],
                        synopsis=None,
                        type=field["type"],
                        url=f"{link}{field['url']}",
                    )
                )

    if service["name"] == "UKTV Play":
        link = "https://uktvplay.co.uk/shows/{slug}/watch-online"

        if query:
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

        if query:
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
                            title=_sanitize(field["content"]["title"]),
                        ),
                    )
                )
        else:
            results.append(
                template.format(
                    service=service["name"],
                    title="US IP-address required",
                    synopsis="",
                    type="",
                    url="",
                )
            )

    if service["name"] == "TubiTV":
        link = "https://tubitv.com/{type}/{id}/{title}"

        if query:
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
                            title=_sanitize(field["title"]),
                        ),
                    )
                )
        else:
            results.append(
                template.format(
                    service=service["name"],
                    title="US IP-address required",
                    synopsis="",
                    type="",
                    url="",
                )
            )

    if service["name"] == "ABC iView":
        link = "https://iview.abc.net.au/show/{slug}"

        if query:
            hits = [x for x in query["results"][0]["hits"] if x["docType"] == "Program"]
            for field in hits:
                results.append(
                    template.format(
                        service=service["name"],
                        title=field["title"],
                        synopsis=field.get("synopsis"),
                        type=field.get("subType"),
                        url=link.format(slug=field["slug"]),
                    )
                )
    if service["name"] == "The CW":
        link = "https://www.cwtv.com{slug}"

        if query:
            for field in query["items"]:
                if not field["type"] == "episodes":
                    results.append(
                        template.format(
                            service=service["name"],
                            title=field["title"],
                            synopsis=field.get("synopsis"),
                            type=field.get("type"),
                            url=link.format(slug=field["link"].split("?")[0]),
                        )
                    )
    if service["name"] == "SVTPlayer":
        link = "https://www.svtplay.se{slug}"

        if query:
            for field in query["data"]["searchPage"]["flat"]["hits"]:
                results.append(
                    template.format(
                        service=service["name"],
                        title=field["teaser"]["item"].get("name"),
                        synopsis=field["teaser"].get("description"),
                        type=field["teaser"]["item"].get("__typename"),
                        url=link.format(
                            slug=field["teaser"]["item"]["urls"]["svtplay"]
                        ),
                    )
                )
    if service["name"] == "Plex":
        link = "https://watch.plex.tv/{type}/{slug}"

        if query:
            media = query["MediaContainer"]["SearchResults"]
            search_results = next(
                x.get("SearchResult") for x in media if x.get("id") == "external"
            )
            for field in search_results:
                results.append(
                    template.format(
                        service=service["name"],
                        title=field["Metadata"]["title"],
                        synopsis=None,
                        type=field["Metadata"].get("type"),
                        url=link.format(
                            type=field["Metadata"].get("type"),
                            slug=field["Metadata"]["slug"],
                        ),
                    )
                )

    if service["name"] == "TVNZ":
        link = "https://www.tvnz.co.nz{slug}"

        if query:
            
            for field in query["results"]:
                results.append(
                    template.format(
                        service=service["name"],
                        title=field.get("title"),
                        synopsis=field.get("synopsis"),
                        type=field.get("type"),
                        url=link.format(slug=field["page"].get("url")
                        ),
                    )
                )

    return results
