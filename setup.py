"""Setup scripts"""

import os
import logging
from logging import Logger
import psycopg2

from util import connect_to_database

CREATE_ANALYSES_TABLE_QUERY = """
    CREATE TABLE IF NOT EXISTS analyses (
        analysis_id VARCHAR(255) PRIMARY KEY NOT NULL,
        dependencies JSONB NOT NULL,
        activation_events JSONB NOT NULL,
        FOREIGN KEY (release_id) REFERENCES releases (release_id) ON DELETE CASCADE
    );
"""


def create_table(
    logger: Logger,
    connection: psycopg2.extensions.connection,
    table_name: str,
    create_table_query: str,
) -> None:
    """Executes the create table query for the given table"""

    if connection is None:
        logger.error(
            "create_table: Failed to create %s table: no database connection",
            table_name,
        )
        return

    cursor = connection.cursor()
    cursor.execute(create_table_query)
    connection.commit()
    cursor.close()

    logger.info("create_table: Created %s table", table_name)


def setup_db(logger: Logger) -> None:
    """Creates the analyses table"""

    connection = connect_to_database(logger)
    create_table(logger, connection, "analyses", CREATE_ANALYSES_TABLE_QUERY)
    connection.close()


def configure_logger() -> Logger:
    """Configures the logger for the application"""

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logger = logging.getLogger(os.getenv("LOGGER_NAME"))
    return logger
