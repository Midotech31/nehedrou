"""Scoped technical origin from a predecessor chain and an immutable import receipt."""
import re
from uuid import UUID

from .integrity import request_value
from .models import GeneratedReviewPackImport, MediaAsset


SHA256 = re.compile(r'[0-9a-f]{64}')
CONCEPT_ID = re.compile(r'[a-z0-9][a-z0-9_-]{0,99}')
VARIANTS = ('source', '512', '256')
MAX_PREDECESSORS = 32


def _receipt_entry(entry):
    if not isinstance(entry, dict):
        return None
    identifier, digest = entry.get('id'), entry.get('sha256')
    if not isinstance(identifier, str) or not isinstance(digest, str) or not SHA256.fullmatch(digest):
        return None
    try:
        if str(UUID(identifier)) != identifier:
            return None
    except ValueError:
        return None
    return identifier, digest


def _generated_index(variety_id):
    index = {}
    receipts = GeneratedReviewPackImport.objects.filter(variety_id=variety_id).only('pack_id', 'manifest_digest', 'record')
    for receipt in receipts:
        record = receipt.record
        if not isinstance(record, dict) or not SHA256.fullmatch(receipt.manifest_digest):
            continue
        media, media_ids = record.get('media'), record.get('media_ids')
        if not isinstance(media, dict) or not isinstance(media_ids, list):
            continue
        media_ids = {value for value in media_ids if isinstance(value, str)}
        for concept, variants in media.items():
            if not CONCEPT_ID.fullmatch(concept) or not isinstance(variants, dict):
                continue
            source = _receipt_entry(variants.get('source'))
            if not source or source[0] not in media_ids:
                continue
            for variant in VARIANTS:
                entry = _receipt_entry(variants.get(variant))
                if not entry or entry[0] not in media_ids:
                    continue
                # Ambiguous competing receipts must not assert a generated origin.
                index[entry] = None if entry in index else {'pack_id': receipt.pack_id,
                    'concept_id': concept, 'variant': variant, 'manifest_sha256': receipt.manifest_digest,
                    'source_asset_id': source[0], 'source_sha256': source[1]}
    return index


def image_origin(asset, variety_id):
    if asset.kind != 'image' or not asset.image_predecessor_id:
        return {}
    digest = asset.technical_metadata.get('sha256')
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        return {}
    predecessor_id = asset.image_predecessor_id
    seen = {asset.pk}
    result = {}
    for _ in range(MAX_PREDECESSORS):
        if predecessor_id in seen:
            break
        seen.add(predecessor_id)
        predecessor = request_value('image_predecessors', predecessor_id, lambda:
            MediaAsset.objects.filter(pk=predecessor_id).only('kind', 'technical_metadata', 'image_predecessor').first())
        if not predecessor or predecessor.kind != 'image' or predecessor.technical_metadata.get('sha256') != digest:
            break
        if not result:
            result = {'predecessor_asset_id': str(predecessor_id), 'predecessor_sha256': digest}
        predecessor_id = predecessor.image_predecessor_id
        if not predecessor_id:
            result['original_asset_id'] = str(predecessor.pk)
            index = request_value('generated_image_receipts', variety_id, lambda: _generated_index(variety_id))
            generated = index.get((str(predecessor.pk), digest))
            if generated:
                result['generated'] = generated
            break
    return result
