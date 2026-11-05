"""Blob storage behind a minimal interface (ADR-007): S3 API (SeaweedFS by default) or local filesystem."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Protocol

from opennotebook.config import Settings, get_settings


class BlobStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...
    async def check(self) -> None: ...
    async def ensure_ready(self) -> None: ...


def _safe_key(key: str) -> str:
    parts = key.split("/")
    if not key or key.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"Invalid blob key: {key!r}")
    return key


class S3BlobStore:
    def __init__(self, settings: Settings) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}, connect_timeout=5),
        )

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=_safe_key(key),
            Body=data,
            ContentType=content_type,
        )

    async def get(self, key: str) -> bytes:
        resp = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=_safe_key(key))
        return await asyncio.to_thread(resp["Body"].read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=_safe_key(key))

    async def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            await asyncio.to_thread(self.client.head_object, Bucket=self.bucket, Key=_safe_key(key))
            return True
        except ClientError:
            return False

    async def check(self) -> None:
        await asyncio.to_thread(self.client.head_bucket, Bucket=self.bucket)

    async def ensure_ready(self) -> None:
        from botocore.exceptions import ClientError

        try:
            await self.check()
        except ClientError:
            await asyncio.to_thread(self.client.create_bucket, Bucket=self.bucket)


class FilesystemBlobStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / _safe_key(key)

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    async def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    async def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    async def check(self) -> None:
        if not self.root.is_dir() or not os.access(self.root, os.W_OK):
            raise OSError(f"{self.root} is not a writable directory")

    async def ensure_ready(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)


def get_blob_store(settings: Settings | None = None) -> BlobStore:
    settings = settings or get_settings()
    if settings.storage_backend == "filesystem":
        return FilesystemBlobStore(settings.filesystem_root)
    return S3BlobStore(settings)
