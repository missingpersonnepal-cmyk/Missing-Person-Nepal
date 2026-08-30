from __future__ import annotations

import hashlib
import uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_DIMENSION = 2400

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

FORMAT_EXTENSIONS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
}

Image.MAX_IMAGE_PIXELS = 40_000_000


def is_allowed_public_image_url(url: str) -> bool:
    """Allow only public HTTPS image hosts used by Meta.

    This prevents the AI JSON from turning the server into
    an unrestricted URL fetcher.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme.casefold() != "https":
        return False

    host = (parsed.hostname or "").casefold().rstrip(".")

    if not host:
        return False

    allowed_exact = {
        "facebook.com",
        "www.facebook.com",
        "instagram.com",
        "www.instagram.com",
    }

    allowed_suffixes = (
        ".facebook.com",
        ".fbcdn.net",
        ".fbsbx.com",
        ".cdninstagram.com",
        ".instagram.com",
    )

    return (
        host in allowed_exact
        or any(
            host.endswith(suffix)
            for suffix in allowed_suffixes
        )
    )


def save_public_image_bytes(
    content: bytes,
    destination: Path,
) -> str:
    if not content:
        raise ValueError("Empty image")

    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds 10 MB")

    try:
        probe = Image.open(BytesIO(content))
        image_format = (
            probe.format or ""
        ).upper()

        probe.verify()

        if image_format not in FORMAT_EXTENSIONS:
            raise ValueError(
                "Unsupported image format"
            )

        image = Image.open(BytesIO(content))

        image.thumbnail(
            (
                MAX_IMAGE_DIMENSION,
                MAX_IMAGE_DIMENSION,
            )
        )

        if (
            image_format == "JPEG"
            and image.mode not in {"RGB", "L"}
        ):
            image = image.convert("RGB")

        output = BytesIO()

        kwargs = {
            "optimize": True,
        }

        if image_format in {
            "JPEG",
            "WEBP",
        }:
            kwargs["quality"] = 90

        # Re-encoding strips EXIF/GPS metadata.
        image.save(
            output,
            format=image_format,
            **kwargs,
        )

        clean = output.getvalue()

    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise ValueError(
            "Invalid source image"
        ) from exc

    digest = hashlib.sha256(
        clean
    ).hexdigest()[:16]

    filename = (
        f"{uuid.uuid4().hex}-"
        f"{digest}"
        f"{FORMAT_EXTENSIONS[image_format]}"
    )

    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        destination
        / filename
    ).write_bytes(clean)

    return filename


async def download_public_source_image(
    url: str,
    destination: Path,
) -> str | None:
    """Download a direct public Meta image when safely accessible.

    Failure to fetch an image never rejects the underlying
    missing-person submission.
    """
    if not is_allowed_public_image_url(url):
        return None

    current = url

    timeout = httpx.Timeout(
        15.0,
        connect=5.0,
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(compatible; MissingPersonHub/1.0)"
        )
    }

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers=headers,
        ) as client:

            for _ in range(4):

                async with client.stream(
                    "GET",
                    current,
                ) as response:

                    if response.status_code in {
                        301,
                        302,
                        303,
                        307,
                        308,
                    }:
                        location = (
                            response.headers.get(
                                "location"
                            )
                        )

                        if not location:
                            return None

                        next_url = urljoin(
                            current,
                            location,
                        )

                        if not is_allowed_public_image_url(
                            next_url
                        ):
                            return None

                        current = next_url
                        continue

                    if response.status_code != 200:
                        return None

                    content_type = (
                        response.headers
                        .get(
                            "content-type",
                            "",
                        )
                        .split(
                            ";",
                            1,
                        )[0]
                        .strip()
                        .casefold()
                    )

                    if (
                        content_type
                        not in ALLOWED_CONTENT_TYPES
                    ):
                        return None

                    chunks: list[bytes] = []
                    total = 0

                    async for chunk in (
                        response.aiter_bytes()
                    ):
                        total += len(chunk)

                        if total > MAX_IMAGE_BYTES:
                            return None

                        chunks.append(chunk)

                    return save_public_image_bytes(
                        b"".join(chunks),
                        destination,
                    )

    except (
        httpx.HTTPError,
        ValueError,
        OSError,
    ):
        return None

    return None



MAX_POST_HTML_BYTES = 2 * 1024 * 1024


def is_public_facebook_content_url(
    url: str,
) -> bool:
    """Accept only actual public Facebook content URLs."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme.casefold() != "https":
        return False

    host = (
        parsed.hostname
        or ""
    ).casefold().rstrip(".")

    facebook_host = (
        host == "facebook.com"
        or host.endswith(".facebook.com")
        or host == "fb.com"
        or host.endswith(".fb.com")
    )

    if not facebook_host:
        return False

    path = parsed.path.casefold()

    return (
        "/posts/" in path
        or "permalink.php" in path
        or "story.php" in path
        or "/reel/" in path
        or "/reels/" in path
        or "/photo/" in path
        or "/photos/" in path
        or "/share/p/" in path
        or "/share/v/" in path
    )


def extract_public_image_url_from_html(
    html: str,
    base_url: str,
) -> str | None:
    """Extract a direct public Meta image URL from post metadata."""

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    candidates: list[str] = []

    for property_name in (
        "og:image",
        "og:image:url",
        "twitter:image",
        "twitter:image:src",
    ):
        tag = soup.find(
            "meta",
            attrs={
                "property": property_name,
            },
        )

        if tag is None:
            tag = soup.find(
                "meta",
                attrs={
                    "name": property_name,
                },
            )

        if tag is not None:
            content = str(
                tag.get("content")
                or ""
            ).strip()

            if content:
                candidates.append(content)

    image_src = soup.find(
        "link",
        attrs={
            "rel": "image_src",
        },
    )

    if image_src is not None:
        href = str(
            image_src.get("href")
            or ""
        ).strip()

        if href:
            candidates.append(href)

    for candidate in candidates:
        absolute = urljoin(
            base_url,
            candidate,
        )

        if is_allowed_public_image_url(
            absolute
        ):
            return absolute

    return None


async def discover_public_post_image(
    post_url: str,
) -> str | None:
    """Best-effort image discovery from a public Facebook post.

    No login, cookie bypass, private-group access or CAPTCHA
    bypass is attempted.
    """

    if not is_public_facebook_content_url(
        post_url
    ):
        return None

    current = post_url

    timeout = httpx.Timeout(
        15.0,
        connect=5.0,
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(compatible; MissingPersonHub/1.0)"
        )
    }

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers=headers,
        ) as client:

            for _ in range(4):

                async with client.stream(
                    "GET",
                    current,
                ) as response:

                    if response.status_code in {
                        301,
                        302,
                        303,
                        307,
                        308,
                    }:
                        location = (
                            response.headers.get(
                                "location"
                            )
                        )

                        if not location:
                            return None

                        next_url = urljoin(
                            current,
                            location,
                        )

                        # Do not follow login/checkpoint redirects.
                        if not is_public_facebook_content_url(
                            next_url
                        ):
                            return None

                        current = next_url
                        continue

                    if response.status_code != 200:
                        return None

                    content_type = (
                        response.headers
                        .get(
                            "content-type",
                            "",
                        )
                        .split(
                            ";",
                            1,
                        )[0]
                        .strip()
                        .casefold()
                    )

                    if content_type not in {
                        "text/html",
                        "application/xhtml+xml",
                    }:
                        return None

                    chunks: list[bytes] = []
                    total = 0

                    async for chunk in (
                        response.aiter_bytes()
                    ):
                        total += len(chunk)

                        if (
                            total
                            > MAX_POST_HTML_BYTES
                        ):
                            return None

                        chunks.append(chunk)

                    html = b"".join(
                        chunks
                    ).decode(
                        "utf-8",
                        errors="replace",
                    )

                    return (
                        extract_public_image_url_from_html(
                            html,
                            current,
                        )
                    )

    except (
        httpx.HTTPError,
        OSError,
        ValueError,
    ):
        return None

    return None
