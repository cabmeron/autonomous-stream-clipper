import os
import tempfile
import pytest
from services.storage.s3_uploader import StorageUploader


def test_storage_local_fallback():
    with tempfile.TemporaryDirectory() as tmpdir:
        fallback_dir = os.path.join(tmpdir, "local_clips")
        uploader = StorageUploader(local_fallback_dir=fallback_dir)

        # Create dummy video and thumbnail files
        video_src = os.path.join(tmpdir, "test_vid.mp4")
        thumb_src = os.path.join(tmpdir, "test_thumb.jpg")
        with open(video_src, "w") as f:
            f.write("dummy video data")
        with open(thumb_src, "w") as f:
            f.write("dummy thumb data")

        v_url, t_url = uploader.upload_clip_bundle(video_src, thumb_src, clip_id="abc-123")

        assert "/clips/" in v_url
        assert "/clips/" in t_url
        assert os.path.exists(os.path.join(fallback_dir, "abc-123_test_vid.mp4"))
        assert os.path.exists(os.path.join(fallback_dir, "abc-123_test_thumb.jpg"))
