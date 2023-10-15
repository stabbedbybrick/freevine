
def _search(keywords: str):
    return [
        {
            "name": "BBC iPlayer",
            "alias": ["BBC", "IPLAYER", "BBCIPLAYER"],
            "url": "https://search.api.bbci.co.uk/formula/iplayer-ibl-root",
            "params": {
                "q": f"{keywords}",
                "apikey": "HJ34sajBaTjACnUJtGZ2Gvsy0QeqJ5UK",
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
                "fetch_fields": {"page": ["title", "body", "resultDescriptionTx", "url"]},
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
    ]
