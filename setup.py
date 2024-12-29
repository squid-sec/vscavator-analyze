"""Setup scripts"""

import os
import logging
from logging import Logger

def configure_logger() -> Logger:
    """Configures the logger for the application"""

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logger = logging.getLogger(os.getenv("LOGGER_NAME"))
    return logger
