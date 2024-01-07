import re
from abc import ABC

from sortedcontainers import SortedKeyList

from utils.utilities import string_cleaning


class Episode:
    """Create object of each episode and store them in a list"""

    def __init__(
        self,
        id_=None,
        service=None,
        title=None,
        season=None,
        number=None,
        name=None,
        year=None,
        data=None,
        subtitle=None,
        lic_url=None,
        drm=None,
        synopsis=None,
        description=None,
        special=None,
    ) -> None:
        if name is not None:
            name = name.strip()
            if name.lower() == title.lower():
                name = ""
            if re.match(r"Episode ?#?\d+", name, re.IGNORECASE):
                name = ""

        self.id = id_
        self.service = service
        self.title = title
        self.season = season
        self.number = number
        self.name = name
        self.year = year
        self.data = data
        self.subtitle = subtitle
        self.lic_url = lic_url
        self.drm = drm
        self.synopsis = synopsis
        self.description = description
        self.special = special

    def __str__(self) -> str:
        if self.season == 0 and self.number == 0:
            return "{title} {name}".format(title=self.title, name=self.name).strip()

        elif self.season == 0 and self.number > 0:
            return "{title} E{number:02} {name}".format(
                title=self.title, number=self.number, name=self.name
            ).strip()

        elif self.number == 0 and self.season > 0:
            return "{title} S{season:02} {name}".format(
                title=self.title, season=self.season, name=self.name
            ).strip()

        else:
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
    def __init__(
        self,
        id_=None,
        service=None,
        title=None,
        name=None,
        year=None,
        data=None,
        subtitle=None,
        lic_url=None,
        synopsis=None,
        drm=None,
    ) -> None:
        if name is not None:
            name = name.strip()

        self.id = id_
        self.service = service
        self.title = title
        self.name = name
        self.year = year
        self.data = data
        self.subtitle = subtitle
        self.lic_url = lic_url
        self.synopsis = synopsis
        self.drm = drm

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
        return self[0].name + (f" ({self[0].year})" if self[0].year else "")
