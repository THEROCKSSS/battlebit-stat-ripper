"""Image intake for profile portraits and clan emblems.

Every upload is decoded, orientation-corrected, centre-cropped, resized, and
re-encoded as WebP. That removes EXIF metadata, stops SVG/script payloads, and
keeps the site's media directory bounded.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_PIXELS = 24_000_000
SIZE = 512

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class ImageError(ValueError):
    pass


def _open_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.verify()
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageError("That file is not a PNG, JPEG, or WebP image.") from exc
    if image.width * image.height > MAX_PIXELS:
        raise ImageError("That image is too large. Use one under 24 megapixels.")
    if getattr(image, "is_animated", False):
        image.seek(0)
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    return image


def save_image(file_storage, kind: str, root: Path) -> str:
    """Save an uploaded image. Returns the stored filename."""
    if not file_storage or not file_storage.filename:
        raise ImageError("Choose an image file.")
    data = file_storage.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError("That image is larger than 6 MB.")
    if not data:
        raise ImageError("That image is empty.")

    image = _open_image(data)
    image = ImageOps.fit(
        image,
        (SIZE, SIZE),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.45),
    )
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.webp"
    image.save(folder / filename, "WEBP", quality=88, method=6)
    return filename


def delete_image(kind: str, filename: str | None, root: Path) -> None:
    if not filename:
        return
    # Stored names are always generated hex filenames; reject any path segment.
    if Path(filename).name != filename:
        return
    path = root / kind / filename
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
