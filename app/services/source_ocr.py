from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError


@dataclass(slots=True)
class OCRResult:
    text: str
    available: bool
    languages: str
    detail: str


def _tesseract_command() -> str | None:
    configured = os.getenv("TESSERACT_CMD", "").strip()
    if configured and Path(configured).is_file():
        return configured

    found = shutil.which("tesseract")
    if found:
        return found

    if os.name == "nt":
        for candidate in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ):
            if Path(candidate).is_file():
                return candidate

    return None


@lru_cache(maxsize=4)
def _available_languages(command: str) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            [command, "--list-langs"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ()

    if completed.returncode != 0:
        return ()

    languages = []
    for line in completed.stdout.splitlines():
        value = line.strip()
        if value and not value.lower().startswith("list of available"):
            languages.append(value)
    return tuple(languages)


def _selected_languages(command: str) -> str:
    available = set(_available_languages(command))
    configured = [
        item.strip()
        for item in os.getenv("TESSERACT_LANGS", "eng+nep").split("+")
        if item.strip()
    ]
    selected = [item for item in configured if item in available]

    if not selected and "eng" in available:
        selected = ["eng"]
    if not selected and available:
        selected = [sorted(available)[0]]

    return "+".join(selected)


def ocr_available() -> bool:
    command = _tesseract_command()
    return bool(command and _selected_languages(command))


def _prepare_image(source: Path, destination: Path) -> None:
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("L")

        width, height = image.size
        largest = max(width, height)
        if largest < 1800:
            scale = min(3.0, 1800 / max(largest, 1))
            image = image.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.Resampling.LANCZOS,
            )

        image = ImageOps.autocontrast(image)
        image = ImageEnhance.Contrast(image).enhance(1.35)
        image = image.filter(ImageFilter.SHARPEN)
        image.save(destination, format="PNG")


def _clean_ocr_text(text: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()

    for raw_line in text.replace("\x0c", "").splitlines():
        line = " ".join(raw_line.split()).strip()
        if len(line) < 2:
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)

    return "\n".join(lines).strip()


def extract_ocr_text(image_path: str | Path) -> OCRResult:
    source = Path(image_path)
    command = _tesseract_command()

    if command is None:
        return OCRResult(
            text="",
            available=False,
            languages="",
            detail=(
                "Tesseract OCR is not installed or not discoverable. "
                "Set TESSERACT_CMD after installing it."
            ),
        )

    languages = _selected_languages(command)
    if not languages:
        return OCRResult(
            text="",
            available=False,
            languages="",
            detail="Tesseract is installed but no usable language data was found.",
        )

    if not source.is_file():
        return OCRResult(
            text="",
            available=True,
            languages=languages,
            detail="OCR source image was not available locally.",
        )

    outputs: list[str] = []

    try:
        with tempfile.TemporaryDirectory(prefix="mp-ocr-") as temp_dir:
            prepared = Path(temp_dir) / "prepared.png"
            _prepare_image(source, prepared)

            for psm in (6, 11):
                try:
                    completed = subprocess.run(
                        [
                            command,
                            str(prepared),
                            "stdout",
                            "-l",
                            languages,
                            "--oem",
                            "3",
                            "--psm",
                            str(psm),
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=35,
                        check=False,
                    )
                except (OSError, subprocess.SubprocessError):
                    continue

                if completed.returncode == 0 and completed.stdout.strip():
                    outputs.append(completed.stdout)

    except (OSError, ValueError, UnidentifiedImageError):
        return OCRResult(
            text="",
            available=True,
            languages=languages,
            detail="The source image could not be prepared for OCR.",
        )

    text = _clean_ocr_text("\n".join(outputs))

    if text:
        return OCRResult(
            text=text,
            available=True,
            languages=languages,
            detail=f"OCR completed using: {languages}",
        )

    return OCRResult(
        text="",
        available=True,
        languages=languages,
        detail=(
            "OCR ran but no reliable text was detected. "
            "The administrator can still inspect the source image manually."
        ),
    )
