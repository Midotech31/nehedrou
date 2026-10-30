"""Install one requested six-concept proposal; never approve or publish content."""
import copy
import hashlib
import json
import uuid
from pathlib import Path
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.urls import reverse
from catalog.models import Activity, Variety, MediaAsset, GeneratedReviewPackImport
from catalog.services import allowed, clone_version
from catalog.media_validation import validate_media, MAX_BYTES
from core.services import audit
from core.storage_health import STORAGE_ERRORS

PACK_ID = 'fr-p-b-initial-review-20261030'
MANIFEST_PATH = Path(settings.BASE_DIR) / 'content' / 'review_packs' / PACK_ID / 'manifest.json'
CONCEPTS = {'bread-v1', 'bath-v1', 'hen-v1', 'sphere-v1', 'pear-v1', 'drinking-v1'}
EXPECTED_PAIRS = [
    ('079c2cd4-9f70-5831-8455-50d96ba157be', ['pain', 'bain'], ['bread-v1', 'bath-v1']),
    ('0abbb85f-d015-57da-b6e1-39e6d5f8e680', ['poule', 'boule'], ['hen-v1', 'sphere-v1']),
    ('7da14770-15cc-5c14-9ed6-bcf5cac73bf4', ['poire', 'boire'], ['pear-v1', 'drinking-v1']),
]


def _read_verified(directory, record):
    path = (directory / record['file']).resolve()
    if not path.is_relative_to(directory.resolve()) or path.name != record['file']:
        raise ValidationError('Review-pack files must remain within their named source directory.')
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
        raise ValidationError('A review-pack file does not match its exact manifest: ' + path.name)
    metadata = validate_media(ContentFile(data, name=path.name), 'image')
    if any(metadata[key] != record[key] for key in ['format', 'width', 'height']):
        raise ValidationError('Review-pack dimensions or format differ from the manifest.')
    return data


def load_pack(source_dir):
    raw = MANIFEST_PATH.read_bytes()
    manifest = json.loads(raw)
    if (manifest.get('pack_id') != PACK_ID or {row['id'] for row in manifest.get('concepts', [])} != CONCEPTS
            or len(manifest['concepts']) != 6 or len(manifest.get('pairs', [])) != 3
            or [(row.get('source_series'), row.get('words'), row.get('concepts')) for row in manifest.get('pairs', [])] != EXPECTED_PAIRS
            or manifest.get('clinical_approval') is not False or manifest.get('linguistic_approval') is not False
            or manifest.get('familiarity_trial_performed') is not False or manifest.get('rights_status') != 'unknown'
            or manifest.get('rights_validity') != 'unknown' or manifest.get('external_references') != []):
        raise ValidationError('This importer accepts only the requested six pending concepts.')
    payloads = {}
    for concept in manifest['concepts']:
        if concept.get('reviews') != {'clinical': 'pending', 'linguistic': 'pending', 'familiarity': 'pending', 'rights': 'pending', 'child_naming_trial': 'not_performed'}:
            raise ValidationError('Generated proposals cannot import a claimed human approval.')
        source = concept['source']
        if source['format'] != 'PNG' or source['width'] != source['height'] or source['width'] < 512:
            raise ValidationError('Retain a full-resolution whole square PNG source for every concept.')
        payloads[(concept['id'], 'source')] = _read_verified(Path(source_dir), concept['source'])
        for size in ['512', '256']:
            variant = concept['display_variants'][size]
            if variant['format'] != 'WEBP' or variant['width'] != int(size) or variant['height'] != int(size):
                raise ValidationError('The pack needs whole-frame 512 and 256 WebP variants.')
            payloads[(concept['id'], size)] = _read_verified(MANIFEST_PATH.parent, variant)
    return manifest, hashlib.sha256(raw).hexdigest(), payloads


def asset_id(concept_id, variant):
    return uuid.uuid5(uuid.NAMESPACE_URL, 'nehedrou:generated-review-pack:' + PACK_ID + ':' + concept_id + ':' + variant)


def _sources(actor, manifest):
    result = []
    for pair in manifest['pairs']:
        source = Activity.objects.filter(series=pair['source_series'], is_demo=False, variety__code='fr-fr-pilot').select_related('variety').order_by('-version').first()
        if not source or [source.word_a, source.word_b] != pair['words']:
            raise ValidationError('The existing real candidate series and exact words are required: ' + '/'.join(pair['words']))
        if not actor.is_active or not allowed(actor, source.variety, 'edit'):
            raise PermissionDenied('Editing authority for the exact French variety is required.')
        result.append(source)
    return result


def _existing_receipt(receipt, digest):
    if receipt.manifest_digest != digest:
        raise ValidationError('This named pack already has another manifest. Create a new pack version.')
    for key in receipt.record['media_ids']:
        asset = MediaAsset.objects.filter(pk=key).first()
        if not asset or not asset.intact:
            raise ValidationError('A previously imported pack file is missing or changed; no silent replacement is allowed.')
    if Activity.objects.filter(pk__in=receipt.record['activity_ids']).count() != 3:
        raise ValidationError('A recorded draft version is missing; do not recreate history silently.')
    return {'status': 'already_imported', 'pack_id': PACK_ID, 'record': receipt.record}


def install_pack(actor, source_dir, *, apply=False):
    manifest, digest, payloads = load_pack(source_dir)
    sources = _sources(actor, manifest)
    existing = GeneratedReviewPackImport.objects.filter(pack_id=PACK_ID).first()
    if existing:
        return _existing_receipt(existing, digest)
    plan = {'status': 'dry_run', 'pack_id': PACK_ID, 'manifest_sha256': digest,
        'media_to_create': 18, 'new_draft_versions': [{'source': str(source.pk), 'series': str(source.series), 'words': [source.word_a, source.word_b]} for source in sources],
        'rights': 'unknown', 'clinical_approval': False, 'files_verified': len(payloads)}
    if not apply:
        return plan
    created_files = []
    try:
        with transaction.atomic():
            Variety.objects.select_for_update().get(pk=sources[0].variety_id)
            sources = _sources(actor, manifest)
            existing = GeneratedReviewPackImport.objects.filter(pack_id=PACK_ID).first()
            if existing:
                return _existing_receipt(existing, digest)
            media = {}
            for concept in manifest['concepts']:
                media[concept['id']] = {}
                for variant in ['source', '512', '256']:
                    key = asset_id(concept['id'], variant)
                    if MediaAsset.objects.filter(pk=key).exists():
                        raise ValidationError('A deterministic pack asset already exists without its import receipt.')
                    record = concept['source'] if variant == 'source' else concept['display_variants'][variant]
                    suffix = 'png' if variant == 'source' else 'webp'
                    provenance = {'generation': {'pack_id': PACK_ID, 'concept_id': concept['id'], 'variant': variant,
                        'tool': manifest['tool'], 'generated_on': manifest['generated_on'], 'prompt': concept['prompt'],
                        'external_references': [], 'source_sha256': concept['source']['sha256'],
                        'source_asset_id': str(asset_id(concept['id'], 'source')),
                        'status': 'generated_pending_expert_review', 'manifest_sha256': digest},
                        'reviews': copy.deepcopy(concept['reviews']), 'qa': copy.deepcopy(concept['qa']),
                        'usage_terms': manifest['usage_terms']}
                    asset = MediaAsset(id=key, uploaded_by=actor, kind='image',
                        file=ContentFile(payloads[(concept['id'], variant)], name=PACK_ID + '-' + concept['id'] + '-' + variant + '.' + suffix),
                        rights='Generated proposal; usage terms, rights evidence and expert reviews pending. No clinical use granted.',
                        rights_status='unknown', rights_validity='unknown', provenance=provenance)
                    try:
                        asset.save()
                    finally:
                        if asset.file._committed:
                            created_files.append((asset.file.storage, asset.file.name))
                    media[concept['id']][variant] = {'id': str(asset.pk), 'sha256': record['sha256'],
                        'url': settings.PUBLIC_ORIGIN.rstrip('/') + reverse('editorial_media', args=[asset.pk])}
            concepts = {row['id']: row for row in manifest['concepts']}
            versions = []
            for source, pair in zip(sources, manifest['pairs']):
                draft = clone_version(actor, source)
                draft.media_manifest = {}
                draft.item_metadata = copy.deepcopy(draft.item_metadata)
                for side, concept_id in zip(['a', 'b'], pair['concepts']):
                    concept = concepts[concept_id]
                    setattr(draft, 'image_' + side, 'editorial/asset-' + media[concept_id]['512']['id'])
                    item = draft.item_metadata.setdefault(side, {})
                    # Working definitions remain visibly pending; no evidence, accepted
                    # regional variant, native audio or approval is invented here.
                    item.update(meaning=concept['meaning_fr_proposed'], segments=concept['proposed_segments'],
                        target_occurrences=[concept['proposed_target_occurrence']], accepted_variants=[],
                        proposed_ipa=concept['ipa'], variants_status=concept['variants_status'],
                        familiarity={'status': 'pending', 'note': 'Spontaneous recognition and naming not yet tested.'},
                        review_pack={'pack_id': PACK_ID, 'concept_id': concept_id, 'status': 'generated_pending_expert_review',
                            'comparison_group': pair['comparison_group'], 'proposed_target_scope': pair['proposed_target_scope'],
                            'qa_flags': concept['qa']['review_flags'], 'display_variants': media[concept_id]})
                draft.state = 'draft'; draft.is_demo = False
                # The old activity description concerns its earlier illustrations.
                # It cannot license newly generated stimuli in this new version.
                draft.rights = ('Generated image proposals created with ' + manifest['tool'] + ' on ' + manifest['generated_on']
                    + '. Image usage conditions and rights evidence are pending review. '
                    + 'No image licence or clinical authorisation is asserted by this import.')
                draft.save()
                versions.append({'id': str(draft.pk), 'version': draft.version, 'source': str(source.pk),
                    'series': str(draft.series), 'words': [draft.word_a, draft.word_b], 'comparison_group': pair['comparison_group']})
            record = {'media': media, 'media_ids': [value['id'] for variants in media.values() for value in variants.values()],
                'activities': versions, 'activity_ids': [row['id'] for row in versions],
                'status': 'generated_pending_expert_review', 'clinical_approval': False}
            receipt = GeneratedReviewPackImport.objects.create(pack_id=PACK_ID, manifest_digest=digest,
                variety=sources[0].variety, actor=actor, record=record)
            audit(actor, 'catalog.generated_review_pack_imported', receipt)
            return {'status': 'imported_pending_review', 'pack_id': PACK_ID, 'record': record}
    except Exception:
        # Only newly saved, immutable file names from this failed transaction;
        # never a source path, existing MediaAsset or unrelated storage object.
        for storage, name in created_files:
            try:
                storage.delete(name)
            except STORAGE_ERRORS:
                pass
        raise
