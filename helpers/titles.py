import re

from sortedcontainers import SortedKeyList
from abc import ABC

from helpers.utilities import string_cleaning


class Episode:
    def __init__(self, **kwargs) -> None:
        self.id = kwargs.get("id_")
        self.service = kwargs.get("service")
        self.title = kwargs.get("title")
        self.season = kwargs.get("season")
        self.number = kwargs.get("number")
        self.name = kwargs.get("name")
        self.year = kwargs.get("year")
        self.data = kwargs.get("data")
        self.subtitle = kwargs.get("subtitle")
        self.lic_url = kwargs.get("lic_url")
        self.synopsis = kwargs.get("synopsis")
        self.description = kwargs.get("description")

        self.title = self.title.strip()

        if self.name is not None:
            self.name = self.name.strip()
            if re.match(r"Episode ?#?\d+", self.name, re.IGNORECASE):
                self.name = None
            elif self.name.lower() == self.title.lower():
                self.name = None

    def __str__(self) -> str:
        return "{title} S{season:02}E{number:02} {name}".format(
            title=self.title,
            season=self.season,
            number=self.number,
            name=self.name or "",
        ).strip()

    def get_filename(self) -> str:
        name = "{title} S{season:02}E{number:02} {name}".format(
            title=self.title.replace("$", "S"),
            season=self.season,
            number=self.number,
            name=self.name or "",
        ).strip()

        return string_cleaning(name)


class Series(SortedKeyList, ABC):
    def __init__(self, iterable=None):
        super().__init__(iterable, key=lambda x: (x.season, x.number, x.year or 0))

    def __str__(self) -> str:
        if not self:
            return super().__str__()
        return self[0].title + (f" ({self[0].year})" if self[0].year else "")


class Movie:
    def __init__(self, **kwargs) -> None:
        self.id = kwargs.get("id_")
        self.service = kwargs.get("service")
        self.title = kwargs.get("title")
        self.name = kwargs.get("name")
        self.year = kwargs.get("year")
        self.data = kwargs.get("data")
        self.subtitle = kwargs.get("subtitle")
        self.lic_url = kwargs.get("lic_url")
        self.synopsis = kwargs.get("synopsis")

        self.name = self.name.strip()

    def __str__(self) -> str:
        if self.year:
            return f"{self.name} ({self.year})"
        return self.name

    def get_filename(self) -> str:
        name = str(self).replace("$", "S")

        return string_cleaning(name)


class Movies(SortedKeyList, ABC):
    def __init__(self, iterable=None):
        super().__init__(iterable, key=lambda x: x.year or 0)

    def __str__(self) -> str:
        if not self:
            return super().__str__()
        return self[0].title + (f" ({self[0].year})" if self[0].year else "")