import os
from services.storage.s3_uploader import StorageUploader


def test_storage_local_fallback(tmp_path):
    uploader = StorageUploader()
    test_file = tmp_path / "clip.mp4"
    test_file.write_text("dummy video")

    url = uploader.upload_clip(str(test_file), "clips/clip.mp4")
    assert url.startswith("/clips/")
    assert os.path.exists(os.path.join(uploader.local_manager.storage_dir, "clip.mp4"))
