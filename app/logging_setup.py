import logging


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="[%(levelname)s] %(asctime)s %(name)s - %(message)s",
    )
