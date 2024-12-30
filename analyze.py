"""Orchestrates the extension analysis process"""

import os
import re
import json
import zipfile
from urllib.parse import urlparse
from dotenv import load_dotenv
from botocore.client import BaseClient
import boto3

from setup import configure_logger

def get_all_object_keys(s3_client: BaseClient) -> list:
    """Retrieves all object key names from the bucket"""

    paginator = s3_client.get_paginator("list_objects_v2")
    return [
        s3_object["Key"]
        for page in paginator.paginate(Bucket=os.getenv("S3_BUCKET_NAME"))
        for s3_object in page["Contents"]
    ]

def get_object(s3_client: BaseClient, object_key: str) -> None:
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
        with zipfile.ZipFile(destination_path, 'r') as zip_ref:
            zip_ref.extractall(unzip_folder)

def find_package_json(object_key: str) -> dict:
    """TODO"""

    folder_path = "extensions/unzipped/" + object_key.replace("/", "-")
    package_data = None

    for root, _, files in os.walk(folder_path):
        if "package.json" in files:
            package_json_path = os.path.join(root, "package.json")
            with open(package_json_path, 'r', encoding='utf-8') as f:
                package_data = json.load(f)
            break

    return package_data

def find_external_urls(object_key: str) -> list:
    """TODO"""

    url_pattern = re.compile(
        r'https?://[^\s\"\'<>]+', # Matches URLs starting with http:// or https://
        re.IGNORECASE
    )
    folder_path = "extensions/unzipped/" + object_key.replace("/", "-")
    external_urls = set()

    for root, _, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            if file.endswith('extension.js'):
                with open(file_path, 'r', encoding='utf-8') as f:
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


def main():
    """Executes the entire extension analysis process"""

    # Setup
    load_dotenv()
    logger = configure_logger()
    s3_client = boto3.client("s3")

    object_keys = get_all_object_keys(s3_client)
    for object_key in object_keys:
        get_object(s3_client, object_key)
        unzip_vsix_file(object_key)
        object_key = "GitHub.copilot-1.254.1278"
        package_json = find_package_json(object_key)
        external_urls = find_external_urls(object_key)


if __name__ == "__main__":
    main()
