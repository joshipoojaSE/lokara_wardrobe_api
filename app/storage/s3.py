from collections.abc import Sequence
from functools import partial

import anyio.to_thread
import boto3
from botocore.config import Config

from app.storage.base import ImageUpload


class S3ImageStorage:
    """boto3 is blocking, so every network call is pushed to a worker thread.

    `url_for` is the exception: presigning is local signing, not a request.
    """

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        presign_expiry_seconds: int = 3600,
    ) -> None:
        self.bucket = bucket
        self.presign_expiry_seconds = presign_expiry_seconds
        # "auto" presigns against the region-less global host while signing for
        # the configured region, which S3 rejects after its redirect. Pin the
        # style: virtual-host for AWS, path for MinIO/LocalStack, which cannot
        # resolve a bucket subdomain.
        addressing_style = "path" if endpoint_url else "virtual"
        self._client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(
                signature_version="s3v4", s3={"addressing_style": addressing_style}
            ),
        )

    async def upload(self, *, key: str, upload: ImageUpload) -> None:
        await anyio.to_thread.run_sync(
            partial(
                self._client.put_object,
                Bucket=self.bucket,
                Key=key,
                Body=upload.data,
                ContentType=upload.content_type,
            )
        )

    async def download(self, key: str) -> ImageUpload:
        """Read an object back. The key stands in for the filename."""
        response = await anyio.to_thread.run_sync(
            partial(self._client.get_object, Bucket=self.bucket, Key=key)
        )
        body = await anyio.to_thread.run_sync(response["Body"].read)
        return ImageUpload(
            filename=key,
            content_type=response.get("ContentType", ""),
            data=body,
        )

    async def delete(self, keys: Sequence[str]) -> None:
        if not keys:
            return
        await anyio.to_thread.run_sync(
            partial(
                self._client.delete_objects,
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": key} for key in keys]},
            )
        )

    def url_for(self, key: str) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.presign_expiry_seconds,
        )
