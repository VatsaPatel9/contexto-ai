"""Cloudflare R2 object storage for uploaded document files.

R2 is S3-compatible, so we use boto3 with signature_version='s3v4' and
the R2 endpoint URL. Objects are laid out under a per-user prefix:

    users/<user_id>/<document_id>/<sanitized-filename>

Presigned GET URLs are short-lived (1 hour) and returned by API endpoints
so the frontend can fetch the original file directly from R2.
"""

from __future__ import annotations

import logging
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from backend.config import Settings

logger = logging.getLogger(__name__)

PRESIGNED_URL_EXPIRY_SECONDS = 3600  # 1 hour


_client_cache: dict[tuple[str, str], Any] = {}


def _is_configured(settings: Settings) -> bool:
    return all(
        [
            settings.r2_account_id,
            settings.r2_access_key_id,
            settings.r2_secret_access_key,
            settings.r2_bucket,
        ]
    )


def _client(settings: Settings):
    if not _is_configured(settings):
        raise RuntimeError(
            "R2 storage is not configured. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
            "R2_SECRET_ACCESS_KEY, R2_BUCKET."
        )

    cache_key = (settings.r2_account_id, settings.r2_access_key_id)
    client = _client_cache.get(cache_key)
    if client is None:
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )
        _client_cache[cache_key] = client
    return client


def _sanitize(filename: str) -> str:
    return "".join(c if c.isalnum() or c in "._- " else "_" for c in filename).strip() or "file"


def build_key(user_id: str, document_id: str, filename: str) -> str:
    """Per-user key layout: users/<user_id>/<doc_id>/<safe-filename>."""
    return f"users/{user_id}/{document_id}/{_sanitize(filename)}"


def upload_document(
    settings: Settings,
    *,
    key: str,
    body: bytes,
    content_type: str,
) -> None:
    client = _client(settings)
    try:
        client.put_object(
            Bucket=settings.r2_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.error("R2 put_object failed (key=%s): %s", key, exc)
        raise


def get_presigned_download_url(
    settings: Settings,
    key: str,
    expires_in: int = PRESIGNED_URL_EXPIRY_SECONDS,
) -> str | None:
    if not _is_configured(settings) or not key:
        return None
    client = _client(settings)
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.r2_bucket, "Key": key},
            ExpiresIn=expires_in,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.warning("R2 presign failed (key=%s): %s", key, exc)
        return None


def delete_document(settings: Settings, key: str) -> None:
    if not _is_configured(settings) or not key:
        return
    client = _client(settings)
    try:
        client.delete_object(Bucket=settings.r2_bucket, Key=key)
    except (BotoCoreError, ClientError) as exc:
        logger.warning("R2 delete_object failed (key=%s, continuing): %s", key, exc)
