import logging

from app.core.config import settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format=LOG_FORMAT,
        force=True,
    )
    logging.getLogger("uvicorn.access").handlers.clear()
