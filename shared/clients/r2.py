"""
Cloudflare R2 Client
====================
Raw data lake. S3-compatible, zero egress fees.
Key: {source}/{data_type}/{YYYY}/{MM}/{DD}/{id}.{ext}
"""
import os
import json
from typing import Optional, Union
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "alpha-engine-raw")

_s3 = None


def _client():
    global _s3
    if _s3 is None and R2_ACCOUNT_ID:
        _s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
    return _s3


def r2_key(source: str, data_type: str, date_str: str, item_id: str, ext: str = "json") -> str:
    y, m, d = date_str[:4], date_str[5:7], date_str[8:10]
    return f"{source}/{data_type}/{y}/{m}/{d}/{item_id}.{ext}"


async def upload(key: str, data: Union[dict, list, str, bytes], content_type: str = "application/json") -> str:
    c = _client()
    if not c:
        return key
    if isinstance(data, (dict, list)):
        body = json.dumps(data, default=str).encode()
    elif isinstance(data, str):
        body = data.encode()
    else:
        body = data
    c.put_object(Bucket=R2_BUCKET_NAME, Key=key, Body=body, ContentType=content_type)
    return key


async def download(key: str) -> Optional[bytes]:
    c = _client()
    if not c:
        return None
    try:
        return c.get_object(Bucket=R2_BUCKET_NAME, Key=key)["Body"].read()
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return None
        raise
