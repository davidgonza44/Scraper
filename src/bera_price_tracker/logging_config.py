"""Standard-library logging setup."""

import logging


def configure_logging(level: str) -> None:
    """Configure concise process-wide logging for command-line execution."""

    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"invalid logging level: {level}")
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
