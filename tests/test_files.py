from io import BytesIO

import pytest
from fastapi import UploadFile
from PIL import Image

from app.services.files import save_image


@pytest.mark.asyncio
async def test_image_upload_is_validated_and_reencoded(tmp_path):
    stream = BytesIO()
    Image.new("RGB", (100, 100), "white").save(stream, format="JPEG", exif=b"Exif\x00\x00test")
    upload = UploadFile(filename="person.jpg", file=BytesIO(stream.getvalue()), headers={"content-type": "image/jpeg"})
    name = await save_image(upload, tmp_path)
    assert name and name.endswith(".jpg")
    saved = Image.open(tmp_path / name)
    assert saved.size == (100, 100)
    assert not saved.getexif()
