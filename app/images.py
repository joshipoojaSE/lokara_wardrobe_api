"""Decide an upload's format from its bytes, not from what the client called it.

A multipart `Content-Type` is a claim, not a fact: a file saved or renamed as
`photo.jpg` arrives labelled `image/jpeg` whatever is actually inside it.
Trusting that claim let AVIF bytes reach the vision model wrapped in a
`data:image/jpeg` URI, which OpenAI rejects — long after the upload had already
returned 201 and written the object to S3.

So the type is sniffed from the leading bytes. A format the API already stores
passes through with its content type corrected; any other image format is
transcoded to JPEG here, while the request is still open, so the failure a
client sees is a 422 on upload rather than `analysis_status="failed"` later.
"""

import io
from collections.abc import Sequence
from dataclasses import replace

from PIL import Image, ImageOps

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.storage.base import ImageUpload

# Re-encoding is already lossy; 90 keeps fabric texture and weave legible, which
# is the part of the picture the analysis prompt actually asks about.
_JPEG_QUALITY = 90

# ISO base media files all begin `....ftyp`; the brand that follows is what
# separates an AVIF from the HEIC an iPhone produces.
_ISO_BRANDS = {
    b"avif": "image/avif",
    b"avis": "image/avif",
    b"heic": "image/heic",
    b"heix": "image/heic",
    b"hevc": "image/heic",
    b"hevx": "image/heic",
    b"heim": "image/heif",
    b"heis": "image/heif",
    b"hevm": "image/heif",
    b"hevs": "image/heif",
    b"mif1": "image/heif",
    b"msf1": "image/heif",
}


def sniff_content_type(data: bytes) -> str | None:
    """The real media type, or None if the bytes are not a picture at all."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        return _ISO_BRANDS.get(data[8:12].lower())
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    return None


def normalize_upload(upload: ImageUpload) -> ImageUpload:
    """Return the upload with a truthful content type, transcoding if needed.

    Blocking and CPU-bound when it converts — call it in a worker thread.
    """
    sniffed = sniff_content_type(upload.data)
    if sniffed is None:
        raise ValidationError(
            f"{upload.filename!r} was sent as "
            f"{upload.content_type or 'untyped'} but its contents are not a "
            f"recognised image."
        )
    if sniffed in settings.image_allowed_content_types:
        if sniffed == upload.content_type:
            return upload
        return replace(upload, content_type=sniffed)
    return _to_jpeg(upload, sniffed)


def normalize_uploads(uploads: Sequence[ImageUpload]) -> list[ImageUpload]:
    return [normalize_upload(upload) for upload in uploads]


def _to_jpeg(upload: ImageUpload, sniffed: str) -> ImageUpload:
    """Transcode a format the vision model cannot read (AVIF, HEIC, TIFF...)."""
    try:
        with Image.open(io.BytesIO(upload.data)) as image:
            image.load()
            # Phone cameras store rotation in EXIF rather than in the pixels,
            # and JPEG output here drops the tag — bake it in or a sideways
            # photo is what the model gets asked about.
            flattened = _drop_alpha(ImageOps.exif_transpose(image) or image)
            buffer = io.BytesIO()
            flattened.save(buffer, format="JPEG", quality=_JPEG_QUALITY)
    except Exception as exc:  # Pillow raises OSError, ValueError and its own
        raise ValidationError(
            f"{upload.filename!r} is {sniffed}, which has to be converted, but "
            f"it could not be read as an image: {exc}"
        ) from exc
    return replace(upload, content_type="image/jpeg", data=buffer.getvalue())


def _drop_alpha(image: Image.Image) -> Image.Image:
    """JPEG has no alpha. Composite onto white rather than letting it go black.

    Garment colour is the whole point of the analysis, so a transparent cutout
    turning black would change the answer, not just the picture.
    """
    if image.mode not in ("RGBA", "LA", "P"):
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background
