"""Profile photo storage. Files live in backend/uploads/members/ (not in Git)."""
import uuid
from pathlib import Path
from typing import Optional

from app.exceptions import AppError, BadRequestError, NotFoundError
from app.utils.images import MAX_PHOTO_BYTES, MEDIA_TYPES, detect_image_extension

# backend/uploads/members  (this file is backend/app/services/photo_service.py)
UPLOAD_ROOT: Path = Path(__file__).resolve().parents[2] / "uploads" / "members"


def validate_and_save(member_code: str, data: bytes) -> str:
    """Checks the bytes really are a JPEG/PNG/WEBP, saves them, returns the file name."""
    if len(data) > MAX_PHOTO_BYTES:
        raise AppError("Photo is too large (max 2 MB)", status_code=413)
    extension = detect_image_extension(data)
    if extension is None:
        raise BadRequestError("Only JPEG, PNG or WEBP images are allowed")

    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    # Random name: the original file name from the user is never used.
    filename = f"{member_code}-{uuid.uuid4().hex}{extension}"
    (UPLOAD_ROOT / filename).write_bytes(data)
    return filename


def resolve(filename: Optional[str]) -> tuple[Path, str]:
    """Returns (path, media_type) for a stored file name, guarding against path tricks."""
    if not filename:
        raise NotFoundError("This member has no photo")
    root = UPLOAD_ROOT.resolve()
    path = (root / filename).resolve()
    if root not in path.parents or not path.is_file():
        raise NotFoundError("Photo file not found")
    return path, MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def delete_file(filename: Optional[str]) -> None:
    if not filename:
        return
    try:
        path, _ = resolve(filename)
        path.unlink(missing_ok=True)
    except NotFoundError:
        pass
