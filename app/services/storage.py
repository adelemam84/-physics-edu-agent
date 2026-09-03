from __future__ import annotations

import os
from functools import lru_cache

BUCKET = os.getenv('PHYSICS_PDF_BUCKET', 'physics-pdf-sources').strip() or 'physics-pdf-sources'
_REQUIRED = ('AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_ENDPOINT_URL_S3','AWS_REGION')


def storage_configured() -> bool:
    return all(os.getenv(k, '').strip() for k in _REQUIRED)


@lru_cache(maxsize=1)
def _client():
    if not storage_configured():
        raise RuntimeError('Neon Object Storage credentials are not configured')
    import boto3
    return boto3.client(
        's3',
        region_name=os.environ['AWS_REGION'],
        endpoint_url=os.environ['AWS_ENDPOINT_URL_S3'],
        aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
    )


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    _client().put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=content_type)


def get_bytes(key: str) -> bytes:
    obj = _client().get_object(Bucket=BUCKET, Key=key)
    return obj['Body'].read()


def delete_object(key: str) -> None:
    _client().delete_object(Bucket=BUCKET, Key=key)


def presigned_get(key: str, expires: int = 900) -> str:
    return _client().generate_presigned_url(
        'get_object', Params={'Bucket': BUCKET, 'Key': key}, ExpiresIn=expires
    )
