#!/usr/bin/env python3
"""
S3 Compatible File upload
=========================

The intent of this script is to provide a simple and secure cli to upload files to S3.

It relies on boto3 to do the heavy-liftning of AWS v4 auth and the actual data-transfer.
Thus, the script here simply transforms cli-arguments and environment variables into a
S3 Bucket Upload operation.

This script was tested using the following S3 Compatible providers for an account with
1TB of storage:

* BackBlaze B2
  - Free egress up to 3TB; then 0.01/GB
* DigitalOcean (DO) Spaces
  - Free egress up to 1TB; then 0.01/GB
* iDrive e2
  - Free egress up to 1TB; then 0.01/GB
* Wasabi
  - Free egress up to 1TB; then account might be suspended

Cost varies between providers and whether you pay monthly or yearly, reduced rates for
first-year of hosting, vouchers for some providers etc. However, somewhere around 4-8$/
month and then egress of 0.01$/GB when exceeding the provider egress limit. BackBlaze
B2, seem like the best choice as it is the easiest to manage in terms of CaPeX.

One would change:

* S3_KEY
* S3_SECRET
* S3_ENDPOINT

Then the provider could be changed. When doing so, then it is probably easiest to
rebuild images, rather than transferring them from one provider to the other.

Note
----

Inititially then the script just took the endpoint-url, relying on url-naming/encoding
conventions of the bucket and region, however, since DO and Wasabi has different naming
conventions, then this approach quickly broke down. Thus, endpoint-url and bucket are
seperate cli-arguments. Also, when no object-key is provided then the filename is used.
"""
import argparse
import logging as log
import os
import sys
from pathlib import Path

import boto3
from botocore.client import Config


def parse_args():
    parser = argparse.ArgumentParser(
        description="Upload a file to S3-compatible storage."
    )
    parser.add_argument("path", type=Path, help="Path to file to upload")

    parser.add_argument(
        "--endpoint-url",
        required=True,
        type=str,
        help="The endpoint to connect to e.g. https://bucket.region.host.tld",
    )
    parser.add_argument(
        "--bucket",
        required=True,
        type=str,
        help="S3 Bucket e.g. 'whatever-i-named-it'",
    )
    parser.add_argument(
        "--object-key",
        type=str,
        help="For example foo.txt; uses filename when argument is not given",
    )

    args = parser.parse_args()
    args.path = args.path.resolve()

    return args


def main(args):

    s3_key = os.getenv("S3_KEY")
    s3_secret = os.getenv("S3_SECRET")
    if not s3_key or not s3_secret:
        print("Please set the S3_KEY and S3_SECRET environment variables.")
        return 1

    obj_key = args.object_key if args.object_key else args.path.name

    s3 = boto3.client(
        "s3",
        aws_access_key_id=s3_key,
        aws_secret_access_key=s3_secret,
        endpoint_url=args.endpoint_url,
        config=Config(signature_version="s3v4"),
    )
    s3.upload_file(args.path, args.bucket, obj_key)

    return 0


if __name__ == "__main__":
    log.basicConfig(
        stream=sys.stdout,
        level=log.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    sys.exit(main(parse_args()))
