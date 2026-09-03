import logging
import os
import shutil
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class LocalStorageManager:
    """Stores rendered video clips and thumbnails on the local filesystem and serves them via relative HTTP URLs."""

    def __init__(self, storage_dir: str = "./storage/clips", base_url: str = "/clips"):
        self.storage_dir = os.path.abspath(storage_dir)
        self.base_url = base_url.rstrip("/")
        os.makedirs(self.storage_dir, exist_ok=True)
        logger.info("[Storage] Local storage initialized at: %s", self.storage_dir)

    def store_clip_bundle(self, local_video_path: str, local_thumb_path: str) -> Tuple[str, str]:
        """Copies video and thumbnail into the permanent local storage directory and returns local access URLs."""
        video_filename = os.path.basename(local_video_path)
        thumb_filename = os.path.basename(local_thumb_path)

        dest_video = os.path.join(self.storage_dir, video_filename)
        dest_thumb = os.path.join(self.storage_dir, thumb_filename)

        shutil.copy2(local_video_path, dest_video)
        shutil.copy2(local_thumb_path, dest_thumb)

        video_url = f"{self.base_url}/{video_filename}"
        thumb_url = f"{self.base_url}/{thumb_filename}"

        logger.info("[Storage] Saved clip locally: %s -> %s", video_filename, video_url)
        return video_url, thumb_url

    def delete_clip_bundle(self, video_url: str, thumb_url: Optional[str] = None) -> bool:
        """Deletes video and thumbnail files from local storage."""
        deleted = False
        for url in (video_url, thumb_url):
            if not url:
                continue
            filename = os.path.basename(url)
            target = os.path.join(self.storage_dir, filename)
            if os.path.exists(target):
                try:
                    os.remove(target)
                    deleted = True
                    logger.info("[Storage] Deleted file: %s", target)
                except OSError as e:
                    logger.error("[Storage] Failed to delete file %s: %s", target, e)
        return deleted
