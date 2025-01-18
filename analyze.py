"""Orchestrates the extension analysis process"""

import os
import re
import json
import zipfile
import shutil
from urllib.parse import urlparse
from dotenv import load_dotenv
from botocore.client import BaseClient
import boto3

from setup import configure_logger, setup_db
from util import (
    connect_to_database,
    select_extensions,
    select_publishers,
    select_releases,
    combine_dataframes,
    select_analyses,
)


def download_vsix_file(s3_client: BaseClient, object_key: str) -> None:
    """Downloads the S3 object associated with the given key"""

    bucket_name = os.getenv("S3_BUCKET_NAME")

    destination_folder = "extensions/vsix"
    os.makedirs(destination_folder, exist_ok=True)
    destination_path = os.path.join(destination_folder, object_key.replace("/", "-"))

    s3_client.download_file(bucket_name, object_key, destination_path)


def unzip_vsix_file(object_key: str) -> None:
    """Unzips the .vsix extension file"""

    destination_path = "extensions/vsix/" + object_key.replace("/", "-")
    destination_folder = "extensions/unzipped"

    if zipfile.is_zipfile(destination_path):
        unzip_folder = os.path.join(destination_folder, os.path.splitext(object_key)[0])
        os.makedirs(unzip_folder, exist_ok=True)
        with zipfile.ZipFile(destination_path, "r") as zip_ref:
            zip_ref.extractall(unzip_folder)


def find_package_json(object_key: str) -> dict:
    """TODO"""

    folder_path = "extensions/unzipped/" + object_key.replace("/", "-")
    package_data = None

    for root, _, files in os.walk(folder_path):
        if "package.json" in files:
            package_json_path = os.path.join(root, "package.json")
            with open(package_json_path, "r", encoding="utf-8") as f:
                package_data = json.load(f)
            break

    return package_data


def find_external_urls(object_key: str) -> list:
    """TODO"""

    url_pattern = re.compile(
        r"https?://[^\s\"\'<>]+",  # Matches URLs starting with http:// or https://
        re.IGNORECASE,
    )
    folder_path = "extensions/unzipped/" + object_key.replace("/", "-")
    external_urls = set()

    for root, _, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            if file.endswith("extension.js"):
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                    # Find all URLs in the file
                    urls = url_pattern.findall(content)
                    if urls:
                        for url in urls:
                            try:
                                parsed_url = urlparse(url)
                                base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                                external_urls.add(base_url.lower())
                            except ValueError as e:
                                print(e)

    external_urls_list = list(external_urls)
    external_urls_list.sort()
    return external_urls_list


def clear_directory(directory):
    """TODO"""

    if os.path.exists(directory):
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if os.path.isfile(item_path) or os.path.islink(item_path):
                os.unlink(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)


def main():
    """Executes the entire extension analysis process"""

    # Setup
    load_dotenv()
    logger = configure_logger()

    setup_db(logger)
    connection = connect_to_database(logger)
    s3_client = boto3.client("s3")

    extensions_df = select_extensions(logger, connection)
    publishers_df = select_publishers(logger, connection)
    releases_df = select_releases(logger, connection)
    combined_df = combine_dataframes(
        [releases_df, extensions_df, publishers_df], ["extension_id", "publisher_id"]
    )

    analyses_df = select_analyses(logger, connection)
    analyzed_release_ids = set(analyses_df["release_id"])

    for _, row in combined_df.iterrows():
        if row["uploaded_to_s3"] and row["release_id"] not in analyzed_release_ids:
            publisher_name = row["publisher_name"]
            extension_name = row["extension_name"]
            release_version = row["version"]

            object_key = (
                f"extensions/{publisher_name}/{extension_name}/{release_version}.vsix"
            )
            download_vsix_file(s3_client, object_key)
            unzip_vsix_file(object_key)

            # Perform static and dynamic analysis here

            clear_directory("extensions")
            break


if __name__ == "__main__":
    main()
