import logging
import os
from services.storage.local_storage import LocalStorageManager

logger = logging.getLogger(__name__)


class StorageUploader:
    """Storage adapter defaulting to 100% local filesystem storage."""

    def __init__(self, bucket_name: str = None, region_name: str = None):
        self.local_manager = LocalStorageManager(
            storage_dir=os.getenv("STORAGE_DIR", "./storage/clips")
        )

    def upload_clip(self, local_path: str, destination_key: str) -> str:
        filename = os.path.basename(local_path)
        dest = os.path.join(self.local_manager.storage_dir, filename)
        if os.path.abspath(local_path) != os.path.abspath(dest):
            import shutil
            shutil.copy2(local_path, dest)
        return f"/clips/{filename}"

    def upload_thumbnail(self, local_path: str, destination_key: str) -> str:
        return self.upload_clip(local_path, destination_key)
