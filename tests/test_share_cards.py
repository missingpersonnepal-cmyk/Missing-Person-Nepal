from datetime import date
from io import BytesIO

from PIL import Image

from app.models import MissingPerson
from app.services.share_cards import build_share_card


def test_share_card_generates_valid_png_without_photo():
    person = MissingPerson(
        case_number="NP-2026-RF-00001",
        disaster_id=1,
        name="Test Person",
        name_ne="परीक्षण व्यक्ति",
        age=30,
        last_seen_date=date(2026, 8, 26),
        last_seen_location="Timure, Rasuwa",
        public_contact_number="9812345678",
    )
    payload = build_share_card(person)
    image = Image.open(BytesIO(payload))
    assert image.format == "PNG"
    assert image.size == (1200, 1200)
