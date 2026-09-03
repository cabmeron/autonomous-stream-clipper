import logging
import os
import shutil
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class LocalStorageManager:
    """Manages local filesystem storage for rendered clips and thumbnails without external services."""

    def __init__(self, storage_dir: str = "./storage/clips", public_prefix: str = "/clips"):
        self.storage_dir = os.path.abspath(storage_dir)
        self.public_prefix = public_prefix.rstrip("/")
        os.makedirs(self.storage_dir, exist_ok=True)
        logger.info("[Storage] Local storage initialized at: %s", self.storage_dir)

    def store_file(self, file_path: str, filename: Optional[str] = None) -> str:
        """Copies a media file to the local storage directory and returns its local web URL."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Source file not found: {file_path}")

        name = filename or os.path.basename(file_path)
        dest_path = os.path.join(self.storage_dir, name)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        if os.path.abspath(file_path) != dest_path:
            shutil.copy2(file_path, dest_path)

        return f"{self.public_prefix}/{name}"

    def store_clip_bundle(
        self,
        video_path: str,
        thumbnail_path: Optional[str] = None,
        clip_id: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        """Stores both the vertical clip video and thumbnail locally."""
        prefix = f"{clip_id}_" if clip_id else ""
        video_name = f"{prefix}{os.path.basename(video_path)}"
        video_url = self.store_file(video_path, filename=video_name)

        thumb_url = None
        if thumbnail_path and os.path.exists(thumbnail_path):
            thumb_name = f"{prefix}{os.path.basename(thumbnail_path)}"
            thumb_url = self.store_file(thumbnail_path, filename=thumb_name)

        return video_url, thumb_url
