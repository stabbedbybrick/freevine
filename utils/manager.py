import importlib.util
import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml


class Service:
    def __init__(
        self,
        name: str,
        alias: str,
        path: Path,
        api: Path,
        config: Path,
        profile: Path,
        cookies: Path,
    ) -> None:
        self.name = name
        self.alias = alias
        self.path = path
        self.api = api
        self.config = config
        self.profile = profile
        self.cookies = cookies

    def import_service(self):
        spec = importlib.util.spec_from_file_location(self.name, str(self.path))
        service_module = importlib.util.module_from_spec(spec)
        sys.modules[self.name] = service_module
        spec.loader.exec_module(service_module)
        return getattr(service_module, self.name)


class ServiceManager:
    def __init__(self):
        self.settings = Path("utils") / "settings"
        with open("config.yaml", "r") as f:
            self.config = yaml.safe_load(f)

        with open(self.settings / "services.json") as f:
            data = json.load(f)
        for service, details in data.items():
            details["path"] = Path(details["path"])
            details["api"] = Path(details["api"])
            details["config"] = Path(details["config"])
            details["profile"] = Path(details["profile"])
            details["cookies"] = Path(details["cookies"])

        self.services = {url: Service(**data) for url, data in data.items()}

    def get_service(self, url) -> tuple:
        log = logging.getLogger()
        service = self.services.get(urlparse(url).netloc)
        if service is None:
            log.error("URL did not match any supported service")
            sys.exit(1)

        log.info(f"\u001b[1m{service.alias[0]}\u001b[0m")

        if service.config.exists():
            log.info("+ Loading service config")
            with open(service.config, "r") as f:
                self.config.update(yaml.safe_load(f))

        if service.profile.exists():
            log.info("+ Loading user profile")
            with open(service.profile, "r") as f:
                self.config.update(yaml.safe_load(f))

        with open(service.api, "r") as f:
            self.config.update(yaml.safe_load(f))

        return service.import_service(), self.config


service_manager = ServiceManager()
