import logging
from datetime import datetime

LEVEL = "{levelname}"
MSG = " : {message}"
TIME = "{asctime}"
FORMATS = {
    logging.DEBUG: f"{TIME} \u001b[4m\u001b[36m{LEVEL}\u001b[0m{MSG}",
    logging.INFO: f"{TIME} \u001b[4m\u001b[32m{LEVEL}\u001b[0m{MSG}",
    logging.WARNING: f"{TIME} \u001b[4m\u001b[33m{LEVEL}\u001b[0m{MSG}",
    logging.ERROR: f"{TIME} \u001b[4m\u001b[31m{LEVEL}\u001b[0m{MSG}",
    logging.CRITICAL: f"{TIME} \u001b[4m\u001b[31m{LEVEL}\u001b[0m{MSG}",
}


class CustomFormatter(logging.Formatter):
    def format(self, record):
        log_fmt = FORMATS[record.levelno]
        formatter = logging.Formatter(
            log_fmt, datefmt=datetime.now().strftime("%H:%M:%S.%f")[:-3], style="{"
        )
        return formatter.format(record)


custom_handler = logging.StreamHandler()
custom_handler.setFormatter(CustomFormatter())
