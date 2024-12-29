"""Orchestrates the extension analysis process"""

import os
import zipfile
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
        break


if __name__ == "__main__":
    main()
