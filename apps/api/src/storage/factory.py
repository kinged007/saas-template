"""Storage factory: selects the backend from STORAGE_DRIVER.

Local (filesystem) is the dev default; s3 speaks SigV4 HTTP to any
S3-compatible endpoint. Unknown drivers raise ValueError, same shape as the
email / secret-store factories.
"""

from __future__ import annotations

from src.storage.base import FileStorage, StorageDriver
from src.storage.local import LocalFileStorage
from src.storage.s3 import S3Config, S3FileStorage

_STORAGE_DRIVERS: dict[str, str] = {
    StorageDriver.LOCAL.value: "local",
    StorageDriver.S3.value: "s3",
}


def build_storage() -> FileStorage:
    from src.settings import settings

    driver = str(settings.storage_driver)
    if driver == StorageDriver.S3.value:
        if not settings.s3_endpoint or not settings.s3_bucket:
            from src.storage.base import StorageError

            raise StorageError("S3 storage needs S3_ENDPOINT and S3_BUCKET")
        return S3FileStorage(
            S3Config(
                endpoint=settings.s3_endpoint,
                bucket=settings.s3_bucket,
                region=settings.s3_region,
                access_key=settings.s3_access_key,
                secret_key=settings.s3_secret_key,
                timeout_s=settings.s3_timeout_s,
            )
        )
    if driver == StorageDriver.LOCAL.value:
        return LocalFileStorage(settings.storage_dir)
    raise ValueError(
        f"unsupported STORAGE_DRIVER: {driver!r} (available: {sorted(_STORAGE_DRIVERS)})"
    )
