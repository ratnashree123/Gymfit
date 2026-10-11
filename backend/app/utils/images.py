"""Image checks that use only the standard library."""
from typing import Optional

MAX_PHOTO_BYTES = 2 * 1024 * 1024  # 2 MB

MEDIA_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def detect_image_extension(data: bytes) -> Optional[str]:
    """Look at the first bytes of the file (its 'magic number'), not at the file name.

    Returns '.jpg', '.png' or '.webp', or None if it is not one of those images.
    A renamed .exe or .svg will be rejected.
    """
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None
