import logging
import os
from typing import Optional, Tuple
from services.storage.local_storage import LocalStorageManager

logger = logging.getLogger(__name__)


class StorageUploader:
    """Unified storage interface defaulting to 100% local storage with optional S3 support."""

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        public_base_url: Optional[str] = None,
        local_fallback_dir: str = "./storage/clips",
    ):
        self.local_manager = LocalStorageManager(storage_dir=local_fallback_dir)
        self.bucket_name = bucket_name or os.getenv("S3_BUCKET_NAME")
        self.endpoint_url = endpoint_url or os.getenv("S3_ENDPOINT_URL")
        self.aws_access_key_id = aws_access_key_id or os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = aws_secret_access_key or os.getenv("AWS_SECRET_ACCESS_KEY")
        self.public_base_url = public_base_url or os.getenv("S3_PUBLIC_BASE_URL")
        self.s3_client = None

        if self.bucket_name and self.aws_access_key_id and self.aws_secret_access_key:
            try:
                import boto3
                from botocore.config import Config
                self.s3_client = boto3.client(
                    "s3",
                    endpoint_url=self.endpoint_url,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                    config=Config(signature_version="s3v4"),
                )
                logger.info("[Storage] S3 cloud store enabled for bucket: %s", self.bucket_name)
            except Exception as e:
                logger.warning("[Storage] Failed to initialize S3 client: %s. Using local storage.", e)
        else:
            logger.info("[Storage] Running in 100%% LOCAL mode. Clips stored at: %s", self.local_manager.storage_dir)

    def upload_file(self, file_path: str, object_name: Optional[str] = None, content_type: Optional[str] = None) -> str:
        """Stores file locally, or to S3 if configured."""
        if self.s3_client and self.bucket_name:
            key = object_name or os.path.basename(file_path)
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type
            elif key.endswith(".mp4"):
                extra_args["ContentType"] = "video/mp4"
            elif key.endswith(".jpg") or key.endswith(".jpeg"):
                extra_args["ContentType"] = "image/jpeg"

            try:
                self.s3_client.upload_file(file_path, self.bucket_name, key, ExtraArgs=extra_args)
                if self.public_base_url:
                    return f"{self.public_base_url.rstrip('/')}/{key}"
                return f"https://{self.bucket_name}.s3.amazonaws.com/{key}"
            except Exception as err:
                logger.error("[Storage] S3 upload error: %s. Storing locally instead.", err)

        return self.local_manager.store_file(file_path, filename=object_name)

    def upload_clip_bundle(
        self,
        video_path: str,
        thumbnail_path: Optional[str] = None,
        clip_id: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        """Stores both the rendered vertical clip and thumbnail."""
        prefix = f"{clip_id}_" if clip_id else ""
        video_name = f"{prefix}{os.path.basename(video_path)}"
        video_url = self.upload_file(video_path, object_name=video_name, content_type="video/mp4")

        thumb_url = None
        if thumbnail_path and os.path.exists(thumbnail_path):
            thumb_name = f"{prefix}{os.path.basename(thumbnail_path)}"
            thumb_url = self.upload_file(thumbnail_path, object_name=thumb_name, content_type="image/jpeg")

        return video_url, thumb_url
