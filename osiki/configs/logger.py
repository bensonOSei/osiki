import sys

from loguru import logger


def setup_logging(log_level: str = "INFO", json_logs: bool = False) -> None:
    """Configure loguru logger for the application."""
    logger.remove()

    if json_logs:
        logger.add(
            sys.stdout,
            level=log_level,
            serialize=True,
        )
    else:
        logger.add(
            sys.stdout,
            level=log_level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            ),
            colorize=True,
        )


def get_logger(name: str = __name__) -> logger:  # type: ignore[valid-type]
    """Get a logger instance with the given name."""
    return logger.bind(name=name)
