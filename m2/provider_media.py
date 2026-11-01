"""Bounded, explicitly selected person chart input for documented vision models.

The SIWC catalog does not advertise input modalities. Only slugs with a
first-party documented image-input contract are enabled here. Other slugs
remain text-only until their plan-usage capability is established.
"""

from base64 import b64encode
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from m2.attachments import MAX_ATTACHMENT, _media_type


# https://developers.openai.com/api/docs/models/gpt-6.1-sol
# https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
VISION_MODELS = frozenset({'gpt-6.1-sol'})
MAX_IMAGE_EDGE = 4096
MAX_IMAGE_PIXELS = 12_000_000
MAX_PDF_PAGES = 4


def validate_chart_file(row, content):
    """Validate local size and structure; do not render or execute untrusted PDF data."""
    if not content or len(content) > MAX_ATTACHMENT or _media_type(content) != row['media_type']:
        raise ValueError('Invalid or oversized selected chart file')
    media_type = row['media_type']
    if media_type == 'application/pdf':
        try:
            reader = PdfReader(BytesIO(content), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
                raise ValueError('Select an unencrypted PDF of at most four pages')
        except (ValueError, TypeError, KeyError, OSError, PyPdfError) as exc:
            raise ValueError('Selected chart PDF cannot be safely processed') from exc
        return {'pages': len(reader.pages)}
    try:
        with Image.open(BytesIO(content)) as image:
            if (image.format != {'image/png': 'PNG', 'image/jpeg': 'JPEG',
                                 'image/webp': 'WEBP'}[media_type] or
                    not 0 < image.width <= MAX_IMAGE_EDGE or
                    not 0 < image.height <= MAX_IMAGE_EDGE or
                    image.width * image.height > MAX_IMAGE_PIXELS or
                    getattr(image, 'n_frames', 1) != 1):
                raise ValueError('Selected image dimensions or format not supported')
            size = {'width': image.width, 'height': image.height}
            image.load()
            return size
    except (UnidentifiedImageError, OSError, SyntaxError, TypeError) as exc:
        raise ValueError('Selected chart image cannot be safely processed') from exc


def chart_content(row, content):
    """Inline one already authorized, validated file; no Files API or URL upload."""
    validate_chart_file(row, content)
    data = b64encode(content).decode('ascii')
    if row['media_type'] == 'application/pdf':
        return {'type': 'input_file', 'filename': 'chart.pdf',
                'file_data': 'data:application/pdf;base64,' + data, 'detail': 'low'}
    return {'type': 'input_image', 'image_url': f'data:{row["media_type"]};base64,{data}',
            'detail': 'low'}
