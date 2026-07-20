"""Server-side validation for user-uploaded catalogue images.

The point isn't the file extension (a client controls that) — it's opening the
bytes with Pillow and confirming they really are an image of an allowed format
and a sane size. This is the part card-assets-spec.md §82-84 flags as the serious
work of user uploads.
"""
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_BYTES = 3 * 1024 * 1024  # 3 MB
MAX_DIMENSION = 3000  # px, either side
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}


def validate_image_upload(f):
    """Raise ValidationError unless ``f`` is a real, allowed, reasonably-sized image.

    Leaves the file pointer rewound so the caller can save it.
    """
    if f is None:
        raise ValidationError("No image provided.")
    if f.size > MAX_UPLOAD_BYTES:
        raise ValidationError(f"Image too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")

    # verify() checks integrity but leaves the image unusable, so re-open after.
    try:
        f.seek(0)
        Image.open(f).verify()
        f.seek(0)
        img = Image.open(f)
    except (UnidentifiedImageError, OSError, ValueError):
        raise ValidationError("Not a valid image file.")

    if img.format not in ALLOWED_FORMATS:
        raise ValidationError(f"Unsupported format {img.format or '?'} (use PNG, JPEG or WEBP).")
    if img.width > MAX_DIMENSION or img.height > MAX_DIMENSION:
        raise ValidationError(f"Image too big ({img.width}x{img.height}; max {MAX_DIMENSION}px a side).")

    f.seek(0)
