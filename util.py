"""Contains helper functions"""

import os
from typing import List
from logging import Logger
import psycopg2
import pandas as pd


def connect_to_database(logger: Logger) -> psycopg2.extensions.connection:
    """Establishes a connection to the SQL database"""

    connection = psycopg2.connect(
        dbname=os.getenv("PG_DATABASE"),
        user=os.getenv("PG_USER"),
        password=os.getenv("PG_PASSWORD"),
        host=os.getenv("PG_HOST"),
        port=os.getenv("PG_PORT"),
    )

    if connection:
        logger.info(
            "connect_to_database: Connected to database %s on host %s:%s",
            os.getenv("PG_DATABASE"),
            os.getenv("PG_HOST"),
            os.getenv("PG_PORT"),
        )
        return connection

    logger.error(
        "connect_to_database: Failed to connect to database %s on host %s",
        os.getenv("PG_DATABASE"),
        os.getenv("PG_HOST"),
    )
    return None


def select_data(
    logger: Logger,
    connection: psycopg2.extensions.connection,
    table_name: str,
    select_data_query: str,
) -> pd.DataFrame:
    """Executes the select data query on the given table"""

    chunks = []
    for chunk in pd.read_sql_query(select_data_query, connection, chunksize=10000):
        chunks.append(chunk)
        logger.info(
            "select_data: Processed chunk of %s with %d rows", table_name, len(chunk)
        )

    return pd.concat(chunks, ignore_index=True)


def select_extensions(
    logger: Logger,
    connection: psycopg2.extensions.connection,
) -> pd.DataFrame:
    """Retrieves all extensions from the database"""

    query = """
        SELECT
            extension_id,
            extension_name,
            publisher_id,
        FROM
            extensions;
    """
    return select_data(logger, connection, "extensions", query)


def select_publishers(
    logger: Logger,
    connection: psycopg2.extensions.connection,
) -> pd.DataFrame:
    """Retrieves all publishers from the database"""

    query = """
        SELECT
            publisher_id,
            publisher_name
        FROM
            publishers;
    """
    return select_data(logger, connection, "publishers", query)


def select_releases(
    logger: Logger,
    connection: psycopg2.extensions.connection,
) -> pd.DataFrame:
    """Retrieves all releases from the database"""

    query = """
        SELECT
            release_id,
            uploaded_to_s3
        FROM
            releases;
    """
    return select_data(logger, connection, "releases", query)


def select_analyses(
    logger: Logger,
    connection: psycopg2.extensions.connection,
) -> pd.DataFrame:
    """Retrieves all analyses from the database"""

    query = """
        SELECT
            release_id
        FROM
            analyses;
    """
    return select_data(logger, connection, "analyses", query)


def combine_dataframes(
    dataframes: List[pd.DataFrame], keys: List[str], how: str = "inner"
) -> pd.DataFrame:
    """Generic function to merge multiple dataframes based on the specified keys"""

    if len(dataframes) - 1 != len(keys):
        raise ValueError(
            "Number of keys must be one less than the number of dataframes."
        )

    combined_df = dataframes[0]
    for i, key in enumerate(keys):
        combined_df = combined_df.merge(dataframes[i + 1], on=key, how=how)

    return combined_df
