from __future__ import annotations

import hashlib
import uuid
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
FORMAT_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_DIMENSION = 2400
Image.MAX_IMAGE_PIXELS = 40_000_000


async def save_image(upload: UploadFile | None, destination: Path) -> str | None:
    if upload is None or not upload.filename:
        return None
    if upload.content_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError("Only JPG, PNG, and WEBP images are allowed")

    content = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Image exceeds 10 MB limit")

    try:
        probe = Image.open(BytesIO(content))
        image_format = (probe.format or "").upper()
        probe.verify()
        if image_format not in FORMAT_EXTENSIONS:
            raise ValueError("Unsupported image format")

        # Re-open and re-encode so uploaded EXIF/GPS metadata is not published.
        image = Image.open(BytesIO(content))
        image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION))
        if image_format == "JPEG" and image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        output = BytesIO()
        save_kwargs = {"optimize": True}
        if image_format in {"JPEG", "WEBP"}:
            save_kwargs["quality"] = 90
        image.save(output, format=image_format, **save_kwargs)
        clean_content = output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("Uploaded file is not a valid supported image") from exc

    digest = hashlib.sha256(clean_content).hexdigest()[:16]
    filename = f"{uuid.uuid4().hex}-{digest}{FORMAT_EXTENSIONS[image_format]}"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / filename).write_bytes(clean_content)
    return filename
