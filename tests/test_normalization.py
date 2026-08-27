from app.services.normalization import canonicalize_url, normalize_phone, normalize_text


def test_normalize_phone_nepal_prefixes():
    assert normalize_phone("+977 981-234-5678") == "9812345678"
    assert normalize_phone("00977 9812345678") == "9812345678"


def test_canonicalize_url_removes_tracking():
    value = canonicalize_url("https://www.facebook.com/groups/test/posts/123/?utm_source=x&fbclid=abc")
    assert value == "https://facebook.com/groups/test/posts/123"


def test_nepali_text_preserved():
    assert normalize_text("  सम्पर्कविहीन  ") == "सम्पर्कविहीन"

from app.services.normalization import detect_platform


def test_detect_social_platforms():
    assert detect_platform("https://www.facebook.com/groups/test/posts/1") == "facebook"
    assert detect_platform("https://instagram.com/p/abc") == "instagram"
    assert detect_platform("https://www.tiktok.com/@x/video/1") == "tiktok"
    assert detect_platform("https://x.com/example/status/1") == "x"
    assert detect_platform("https://reddit.com/r/Nepal/comments/abc") == "reddit"
    assert detect_platform("https://example.org/report") == "website"
