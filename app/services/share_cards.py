from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import settings
from ..models import MissingPerson


def _font(size: int) -> ImageFont.ImageFont:
    # Use Pillow's bundled/default font to avoid shipping font files.
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def build_share_card(person: MissingPerson) -> bytes:
    width, height = 1200, 1200
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)

    draw.rectangle((0, 0, width, 150), fill="black")
    draw.text((60, 45), "MISSING PERSON", font=_font(54), fill="white")

    y = 210
    photo_file = settings.upload_dir / person.photo_path if person.photo_path else None
    if photo_file and photo_file.exists():
        try:
            photo = Image.open(photo_file).convert("RGB")
            photo.thumbnail((430, 430))
            x = (width - photo.width) // 2
            canvas.paste(photo, (x, y))
            y += photo.height + 35
        except Exception:
            pass

    draw.text((60, y), person.name, font=_font(48), fill="black")
    y += 70
    if person.name_ne:
        draw.text((60, y), person.name_ne, font=_font(38), fill="black")
        y += 55

    details = [
        f"Case: {person.case_number}",
        f"Age: {person.age if person.age is not None else 'Unknown'}",
        f"Last seen: {person.last_seen_location}",
        f"Date: {person.last_seen_date.isoformat() if person.last_seen_date else 'Unknown'}",
        f"Information contact: {person.public_contact_number or 'See case page'}",
        f"Details: {settings.public_base_url}/person/{person.case_number}",
    ]
    for line in details:
        draw.text((60, y), line, font=_font(30), fill="black")
        y += 48

    output = BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()
