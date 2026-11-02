"""Offline, content-addressed reference package from operator-supplied extracted leaves.

No PDF parser, OCR, network, database, or automatic source selection. The raw
source and extracted leaf transcript are inputs; their identity is bound to the
manifest. Correction to either input makes a different immutable edition.
"""

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import NamedTuple
from urllib.parse import urlparse

MAX_RAW = 16 * 1024 * 1024
MAX_TEXT = 4 * 1024 * 1024
MAX_MANIFEST = 8 * 1024 * 1024
MAX_PASSAGES = 512
MAX_LEAVES = 1024
MAX_PASSAGE_CHARS = 3000
VERSION = 1


class ValidatedPackage(NamedTuple):
    manifest: dict
    raw: bytes
    transcript: bytes
    normalized: str


def digest(data):
    return sha256(data).hexdigest()


def bounded_file(path, limit):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Package input must be a regular file')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Package input exceeds bound')
    return data


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


def decode_text(raw):
    text = raw.decode('utf-8')
    if text.startswith('\ufeff') or '\x00' in text:
        raise ValueError('Invalid UTF-8 text')
    return text


def prepare(source_path, leaves_path, metadata_path, output_root, *, _verify=True):
    """Create an atomic immutable package; existing valid identical work is reused."""
    raw = bounded_file(source_path, MAX_RAW)
    leaves_raw = bounded_file(leaves_path, MAX_TEXT)
    meta_raw = bounded_file(metadata_path, 32768)
    leaves = json.loads(decode_text(leaves_raw))
    metadata = json.loads(decode_text(meta_raw))
    if not isinstance(leaves, list) or not 1 <= len(leaves) <= MAX_LEAVES:
        raise ValueError('Invalid extracted leaves')
    if not isinstance(metadata, dict) or set(metadata) != {
            'author', 'title', 'edition', 'tradition', 'technique', 'provenance',
            'rights_evidence', 'rights_basis', 'language', 'source_url',
            'extraction_note', 'supersedes_source_id', 'processing_revision'}:
        raise ValueError('Invalid edition metadata')
    if metadata['rights_basis'] not in ('synthetic_fixture', 'public_domain_edition',
                                         'open_license', 'user_permitted_private'):
        raise ValueError('Invalid rights basis')
    if any(not isinstance(value, str) or not value or len(value) > 512
           for key, value in metadata.items() if key not in ('source_url', 'supersedes_source_id')):
        raise ValueError('Invalid edition metadata value')
    if metadata['source_url'] is not None:
        url = metadata['source_url']
        if not isinstance(url, str) or len(url.encode()) > 512:
            raise ValueError('Invalid source URL')
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Source URL must be HTTPS without credentials')
    if metadata['supersedes_source_id'] is not None and not isinstance(metadata['supersedes_source_id'], str):
        raise ValueError('Invalid predecessor')
    segments, pages, length = [], [], 0
    for leaf in leaves:
        if not isinstance(leaf, dict) or set(leaf) != {
                'text', 'page', 'printed_page', 'source_locator', 'section',
                'parent_section', 'extraction_status', 'review_status'}:
            raise ValueError('Invalid leaf fields')
        if (type(leaf['page']) is not int or not 1 <= leaf['page'] <= 10000 or
                (pages and leaf['page'] < pages[-1]['page']) or
                (leaf['printed_page'] is not None and
                 (type(leaf['printed_page']) is not int or not 1 <= leaf['printed_page'] <= 10000)) or
                any(not isinstance(leaf[key], str) or not leaf[key] or len(leaf[key]) > 256
                    for key in ('source_locator', 'section', 'parent_section',
                                'extraction_status', 'review_status')) or
                leaf['extraction_status'] not in ('unverified_ocr', 'unverified_transcription',
                                                  'verified_extraction') or
                leaf['review_status'] not in ('not_reviewed', 'sampled', 'reviewed') or
                not isinstance(leaf['text'], str) or not leaf['text'].strip() or '\x00' in leaf['text']):
            raise ValueError('Invalid extracted leaf')
        if pages and leaf['source_locator'] == pages[-1]['source_locator']:
            raise ValueError('Duplicate source leaf locator')
        if (pages and leaf['printed_page'] is not None and
                pages[-1]['printed_page'] is not None and
                leaf['printed_page'] <= pages[-1]['printed_page']):
            raise ValueError('Printed pages must increase when mapped')
        start = length
        segment = leaf['text'] + '\n\n'
        segments.append(segment)
        length += len(segment)
        pages.append({'page': leaf['page'], 'printed_page': leaf['printed_page'],
                      'source_locator': leaf['source_locator'],
                      'start': start, 'end': length,
                      **{key: leaf[key] for key in ('section', 'parent_section',
                                                     'extraction_status', 'review_status')}})
    normalized = ''.join(segments)
    text_bytes = normalized.encode()
    if len(text_bytes) > MAX_TEXT:
        raise ValueError('Normalized text exceeds bound')
    passages = []
    start = 0
    while start < len(normalized):
        end = min(start + MAX_PASSAGE_CHARS, len(normalized))
        current = next(page for page in pages if page['start'] <= start < page['end'])
        for page in pages:
            if (page['start'] > start and
                    (page['parent_section'], page['section']) !=
                    (current['parent_section'], current['section'])):
                end = min(end, page['start'])
                break
        if end < len(normalized):
            # Prefer a paragraph, then a word boundary; include its whitespace
            # in the preceding exact slice so no characters silently disappear.
            for separator in ('\n\n', ' '):
                boundary = normalized.rfind(separator, start + MAX_PASSAGE_CHARS // 2, end)
                if boundary >= 0:
                    end = boundary + len(separator)
                    break
        locations = [page for page in pages if page['start'] < end and page['end'] > start]
        if not locations:
            raise ValueError('Passage has no source location')
        first = locations[0]
        parent = (first['parent_section'] if all(p['parent_section'] == first['parent_section']
                                                 for p in locations) else 'mixed_sections')
        extraction = (first['extraction_status'] if all(
            p['extraction_status'] == first['extraction_status'] for p in locations)
            else 'mixed_unverified')
        review = ('reviewed' if all(p['review_status'] == 'reviewed' for p in locations)
                  else 'not_reviewed' if any(p['review_status'] == 'not_reviewed' for p in locations)
                  else 'sampled')
        passages.append({'id': f'p-{start:07d}', 'ordinal': len(passages),
                         'start': start, 'end': end, 'content': normalized[start:end],
                         'content_sha256': digest(normalized[start:end].encode()),
                         'section': first['section'], 'parent_section': parent,
                         'page_start': first['page'], 'page_end': locations[-1]['page'],
                         'printed_page_start': first['printed_page'],
                         'printed_page_end': locations[-1]['printed_page'],
                         'source_locator_start': first['source_locator'],
                         'source_locator_end': locations[-1]['source_locator'],
                         'extraction_status': extraction, 'review_status': review})
        start = end
    if not 1 <= len(passages) <= MAX_PASSAGES:
        raise ValueError('Passage count exceeds bound')
    source_hash, transcript_hash = digest(raw), digest(json_bytes(leaves))
    config_hash = digest(json_bytes(metadata))
    revision = digest(json_bytes({'version': VERSION, 'source': source_hash,
                                  'transcript': transcript_hash, 'config': config_hash}))
    manifest = {'package_version': VERSION, 'source_id': 'book-' + revision[:32],
                'source_sha256': source_hash, 'transcript_sha256': transcript_hash,
                'processing_sha256': config_hash, 'normalized_sha256': digest(text_bytes),
                'metadata': metadata, 'pages': pages, 'passages': passages}
    root = Path(output_root)
    if root.is_symlink():
        raise ValueError('Unsafe package root')
    root.mkdir(parents=True, exist_ok=True)
    destination = root / manifest['source_id']
    if destination.exists() or destination.is_symlink():
        existing = validate(destination) if _verify else manifest
        if existing != manifest:
            raise ValueError('Existing package identity differs')
        return destination
    with tempfile.TemporaryDirectory(prefix='.book-stage-', dir=root) as stage:
        path = Path(stage)
        (path / 'source.bin').write_bytes(raw)
        (path / 'transcript.json').write_bytes(json_bytes(leaves))
        (path / 'normalized.txt').write_bytes(text_bytes)
        encoded_manifest = json_bytes(manifest)
        if len(encoded_manifest) > MAX_MANIFEST:
            raise ValueError('Package manifest exceeds bound')
        (path / 'manifest.json').write_bytes(encoded_manifest)
        if _verify:
            validate(path)
        try:
            os.rename(path, destination)  # one complete directory or no new package
        except FileExistsError:
            if (validate(destination) if _verify else manifest) != manifest:
                raise ValueError('Concurrent package identity differs')
    return destination


def validate(package):
    """Check package and return its manifest for offline inspection."""
    return validated_snapshot(package).manifest


def validated_snapshot(package):
    """Validate once and retain the exact bytes the importer must commit."""
    path = Path(package)
    if path.is_symlink() or not path.is_dir() or {p.name for p in path.iterdir()} != {
            'source.bin', 'transcript.json', 'normalized.txt', 'manifest.json'}:
        raise ValueError('Invalid package layout')
    raw = bounded_file(path / 'source.bin', MAX_RAW)
    transcript_bytes = bounded_file(path / 'transcript.json', MAX_TEXT)
    transcript = json.loads(decode_text(transcript_bytes))
    if transcript_bytes != json_bytes(transcript):
        raise ValueError('Transcript must use canonical JSON bytes')
    text = decode_text(bounded_file(path / 'normalized.txt', MAX_TEXT))
    manifest = json.loads(decode_text(bounded_file(path / 'manifest.json', MAX_MANIFEST)))
    if not isinstance(manifest, dict) or set(manifest) != {
            'package_version', 'source_id', 'source_sha256', 'transcript_sha256',
            'processing_sha256', 'normalized_sha256', 'metadata', 'pages', 'passages'}:
        raise ValueError('Invalid package manifest')
    if not isinstance(manifest['passages'], list) or not 1 <= len(manifest['passages']) <= MAX_PASSAGES:
        raise ValueError('Invalid package passage count')
    # Recompute, don't trust serialized page boundaries, passage locators or identity.
    with tempfile.TemporaryDirectory(prefix='kat-book-verify-') as temp:
        temp = Path(temp)
        (temp / 'source').write_bytes(raw)
        (temp / 'leaves').write_bytes(json_bytes(transcript))
        (temp / 'metadata').write_bytes(json_bytes(manifest['metadata']))
        # Avoid recursive validation: rebuild via a fresh destination; also checks metadata.
        built = prepare(temp / 'source', temp / 'leaves', temp / 'metadata', temp / 'out', _verify=False)
        rebuilt = json.loads((built / 'manifest.json').read_text(encoding='utf-8'))
    if rebuilt != manifest or text != ''.join(p['content'] for p in manifest['passages']):
        raise ValueError('Package identity or spans mismatch')
    return ValidatedPackage(manifest, raw, transcript_bytes, text)
