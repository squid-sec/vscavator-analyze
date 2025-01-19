"""Orchestrates the extension analysis process"""

import os
import json
import zipfile
import shutil
import subprocess
from datetime import date
from logging import Logger
from dotenv import load_dotenv
import pandas as pd
from botocore.client import BaseClient
import boto3
import psycopg2

from setup import configure_logger, setup_db
from util import (
    connect_to_database,
    select_extensions,
    select_publishers,
    select_releases,
    combine_dataframes,
    select_analyses,
    upsert_data,
)


def download_vsix_file(logger: Logger, s3_client: BaseClient, object_key: str) -> None:
    """Downloads the S3 object associated with the given key"""

    bucket_name = os.getenv("S3_BUCKET_NAME")

    destination_folder = "extensions/vsix"
    os.makedirs(destination_folder, exist_ok=True)
    destination_path = os.path.join(destination_folder, object_key.replace("/", "-"))

    s3_client.download_file(bucket_name, object_key, destination_path)
    logger.info("download_vsix_file: dowloaded S3 object %s", object_key)


def unzip_vsix_file(logger: Logger, object_key: str) -> None:
    """Unzips the .vsix extension file"""

    destination_path = "extensions/vsix/" + object_key.replace("/", "-")
    destination_folder = "extensions/unzipped"

    if zipfile.is_zipfile(destination_path):
        unzip_folder = os.path.join(destination_folder, os.path.splitext(object_key)[0])
        os.makedirs(unzip_folder, exist_ok=True)
        with zipfile.ZipFile(destination_path, "r") as zip_ref:
            zip_ref.extractall(unzip_folder)
            logger.info(
                "unzip_vsix_file: unzipped .vsix file into %s", destination_path
            )


def find_package_json(logger: Logger, object_key: str) -> dict:
    """Retrieves the package.json file data"""

    folder_path = "extensions/unzipped/" + object_key.replace(".vsix", "")
    package_data = None

    for root, _, files in os.walk(folder_path):
        if "package.json" in files:
            package_json_path = os.path.join(root, "package.json")
            with open(package_json_path, "r", encoding="utf-8") as file:
                package_data = json.load(file)
                return package_data

    logger.error(
        "find_package_json: failed to find package.json file in %s", folder_path
    )
    return package_data


def extract_package_metadata(package_json: dict) -> dict:
    """Extracts relevant package.json metadata"""

    return {
        "dependencies": package_json.get("dependencies", {}),
        "activation_events": package_json.get("activationEvents", []),
    }


def semgrep_analysis(logger: Logger) -> dict:
    """Performs static code analysis using semgrep"""

    try:
        result = subprocess.run(
            ["semgrep", "--config", "semgrep", "extensions/unzipped", "--json"],
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as err:
        logger.error("semgrep_analysis: error running semgrep analysis - %s", str(err))

    return {}


def extract_semgrep_metadata(semgrep_output: dict) -> dict:
    """Extracts relevant semgrep metadata"""

    semgrep_metadata = {"semgrep_detections": []}

    results = semgrep_output["results"]
    for result in results:
        if result["extra"]["message"] not in semgrep_metadata["semgrep_detections"]:
            semgrep_metadata["semgrep_detections"].append(result["extra"]["message"])

    return semgrep_metadata


def create_package_json_file(dependencies: dict) -> None:
    """Creates a temporary package.json file"""

    package_json = {
        "name": "temp-package",
        "version": "1.0.0",
        "dependencies": dependencies,
    }

    # Ensure the directory exists
    file_path = "extensions/packages/package.json"
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(package_json, file, indent=2)


def install_package_lock_only(logger: Logger) -> None:
    """Installs dependencies to generate package-lock.json (without installing packages)"""

    try:
        subprocess.run(
            ["npm", "install", "--package-lock-only"],
            cwd="extensions/packages",
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as err:
        logger.error(
            "install_package_lock_only: error running npm install - %s", str(err)
        )


def run_npm_audit(logger: Logger) -> dict:
    """Runs npm audit"""

    try:
        result = subprocess.run(
            ["npm", "audit", "--json"],
            cwd="extensions/packages",
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as err:
        logger.error("run_npm_audit: error running npm audit - %s", str(err))

    return {}


def parse_audit_result(audit_json):
    """Parses the npm audit result"""

    parsed_vulnerabilities = {"npm_audit_vulnerabilities": []}

    vulnerabilities = audit_json.get("advisories", {})
    for _, advisory in vulnerabilities.items():
        parsed_vulnerabilities["npm_audit_vulnerabilities"].append(
            {
                "package": advisory.get("module_name"),
                "severity": advisory.get("severity"),
                "title": advisory.get("title"),
                "url": advisory.get("url"),
            }
        )

    return parsed_vulnerabilities


def upsert_analyses(
    logger: Logger,
    connection: psycopg2.extensions.connection,
    analyses_df: pd.DataFrame,
    batch_size: int = 5000,
) -> None:
    """Upserts the given analyses to the database in batches"""

    upsert_query = """
        INSERT INTO analyses (
            analysis_id, release_id, insertion_date, dependencies, activation_events, semgrep_detections, npm_audit_vulnerabilities
        ) VALUES %s
        ON CONFLICT (analysis_id) DO UPDATE SET
            release_id = EXCLUDED.release_id,
            insertion_date = EXCLUDED.insertion_date,
            dependencies = EXCLUDED.dependencies,
            activation_events = EXCLUDED.activation_events,
            semgrep_detections = EXCLUDED.semgrep_detections,
            npm_audit_vulnerabilities = EXCLUDED.npm_audit_vulnerabilities;
    """

    values = [
        (
            row["analysis_id"],
            row["release_id"],
            row["insertion_date"],
            json.dumps(row["dependencies"]),
            json.dumps(row["activation_events"]),
            json.dumps(row["semgrep_detections"]),
            json.dumps(row["npm_audit_vulnerabilities"]),
        )
        for _, row in analyses_df.iterrows()
    ]

    for i in range(0, len(values), batch_size):
        batch = values[i : i + batch_size]
        upsert_data(logger, connection, "analyses", upsert_query, batch)
        logger.info(
            "upsert_analyses: Upserted analyses batch %d of %d rows",
            i // batch_size + 1,
            len(batch),
        )


def clear_directory(logger: Logger, directory: str = "extensions"):
    """Deletes the given directory and its contents"""

    if os.path.exists(directory):
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if os.path.isfile(item_path) or os.path.islink(item_path):
                os.unlink(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
    logger.info("clear_directory: deleted all the contents from %s", directory)


def analyze_extension(logger: Logger, s3_client: BaseClient, row: pd.Series) -> dict:
    """Performs analysis of the given extension"""

    analysis_data = {
        "analysis_id": "analysis-" + row["release_id"],
        "release_id": row["release_id"],
        "insertion_date": date.today(),
    }

    publisher_name = row["publisher_name"]
    extension_name = row["extension_name"]
    release_version = row["version"]

    # Fetch .vsix file from S3
    object_key = f"extensions/{publisher_name}/{extension_name}/{release_version}.vsix"
    download_vsix_file(logger, s3_client, object_key)
    unzip_vsix_file(logger, object_key)

    # package.json analysis
    package_json = find_package_json(logger, object_key)
    package_metadata = extract_package_metadata(package_json)
    analysis_data.update(package_metadata)

    # npm audit analysis
    create_package_json_file(package_metadata["dependencies"])
    install_package_lock_only(logger)
    audit_json = run_npm_audit(logger)
    audit_metadata = parse_audit_result(audit_json)
    analysis_data.update(audit_metadata)

    # semgrep analysis
    semgrep_output = semgrep_analysis(logger)
    semgrep_metadata = extract_semgrep_metadata(semgrep_output)
    analysis_data.update(semgrep_metadata)

    clear_directory(logger)

    return analysis_data


def main():
    """Executes the entire extension analysis process"""

    # Setup
    load_dotenv()
    logger = configure_logger()
    setup_db(logger)
    connection = connect_to_database(logger)
    s3_client = boto3.client("s3")

    # Fetch extension data
    extensions_df = select_extensions(logger, connection)
    publishers_df = select_publishers(logger, connection)
    releases_df = select_releases(logger, connection)
    combined_df = combine_dataframes(
        [releases_df, extensions_df, publishers_df], ["extension_id", "publisher_id"]
    )

    # Fetch existing analyses
    analyses_df = select_analyses(logger, connection)
    analyzed_release_ids = set(analyses_df["release_id"])

    # Analyze extension
    analysis_metadata = []
    for _, row in combined_df.iterrows():
        # Ensure the release is uploaded to S3 and hasn't been analyzed before
        if row["uploaded_to_s3"] and row["release_id"] not in analyzed_release_ids:
            analysis = analyze_extension(logger, s3_client, row)
            analysis_metadata.append(analysis)

    # Upsert analyses
    new_analyses = pd.DataFrame(analysis_metadata)
    upsert_analyses(logger, connection, new_analyses)


if __name__ == "__main__":
    main()
