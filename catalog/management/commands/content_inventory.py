"""Aggregate editorial inventory. No care, goal, administration or patient rows."""
import json
from collections import Counter, defaultdict
from pathlib import Path
from uuid import UUID
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from catalog.models import Activity, MediaAsset, Review, Variety, GeneratedReviewPackImport
from catalog.content_catalog import current_catalog
from catalog.integrity import integrity_scope, prepare_activities
from catalog.readiness import reference_asset_id
from qualification.models import EvidenceDocument, AvailabilityDecision, LexicalPack, LexicalCandidate
from qualification.services import availability_for
from followup.models import ProbeDefinition


def _counts(rows, key):
    return dict(sorted(Counter(row[key] for row in rows).items()))


def _latest(rows):
    result = {}
    for row in rows:
        if row.series not in result or row.version > result[row.series].version:
            result[row.series] = row
    return list(result.values())


def build_inventory(*, verify=True):
    source_files = []
    definitions = Counter()
    for filename in ['catalog-candidates.json', 'arabic-library-v1.json']:
        path = Path(settings.BASE_DIR) / 'docs' / filename
        document = json.loads(path.read_text(encoding='utf-8'))
        entries = document if isinstance(document, list) else document['activities']
        by_variety = Counter(row['variety_code'] for row in entries)
        definitions.update(by_variety)
        source_files.append({'file': 'docs/' + filename, 'definitions': len(entries), 'by_variety': dict(by_variety),
            'meaning': 'Editorial candidates in source files; no approval or database publication implied'})
    varieties = list(Variety.objects.order_by('code'))
    activities = list(Activity.objects.select_related('variety'))
    assets = list(MediaAsset.objects.all())
    assets_by_id = {asset.pk: asset for asset in assets}
    references = defaultdict(set)
    for activity in activities:
        for name, kind in [('image_a', 'image'), ('image_b', 'image'), ('audio_a', 'audio'), ('audio_b', 'audio')]:
            key = reference_asset_id(getattr(activity, name), kind)
            if key:
                references[activity.variety.code].add(key)
    generated_packs = list(GeneratedReviewPackImport.objects.select_related('variety'))
    for receipt in generated_packs:
        references[receipt.variety.code].update(UUID(key) for key in receipt.record.get('media_ids', []))
    # Global editorial definitions only; organisation-specific protocols are excluded.
    probes = list(ProbeDefinition.objects.filter(organization__isnull=True).select_related('variety'))
    for definition in probes:
        for item in definition.items:
            for name in ['image_asset', 'audio_asset']:
                try:
                    references[definition.variety.code].add(UUID(str(item.get(name, ''))))
                except (ValueError, TypeError):
                    pass
    for candidate in LexicalCandidate.objects.values('pack__variety__code', 'image_id', 'audio_id'):
        references[candidate['pack__variety__code']].update(key for key in [candidate['image_id'], candidate['audio_id']] if key)
    proofs = list(EvidenceDocument.objects.values('variety_id', 'category', 'validity', 'revoked'))
    decisions = list(AvailabilityDecision.objects.values('variety_id', 'module', 'status'))
    real_reviews = Counter(Review.objects.filter(approved=True, activity__is_demo=False).values_list('activity__variety_id', flat=True))
    demo_reviews = Counter(Review.objects.filter(approved=True, activity__is_demo=True).values_list('activity__variety_id', flat=True))
    packs = list(LexicalPack.objects.values('variety_id', 'state'))
    ready_activities = Counter()
    ready_probes = Counter()
    if verify:
        with integrity_scope():
            for activity in prepare_activities(current_catalog(Activity.objects.filter(is_demo=False, state='published').select_related('variety'))):
                if activity.usable:
                    ready_activities[activity.variety_id] += 1
            for definition in _latest([row for row in probes if not row.is_demo and row.state == 'published']):
                if definition.ready and availability_for('production_followup', definition.variety, definition.fingerprint())['available']:
                    ready_probes[definition.variety_id] += 1
    rows = []
    by_code = {variety.code: variety for variety in varieties}
    for code in sorted(set(by_code) | set(definitions)):
        variety = by_code.get(code)
        real = [row for row in activities if row.variety.code == code and not row.is_demo]
        demo = [row for row in activities if row.variety.code == code and row.is_demo]
        latest = _latest(real)
        linked = [assets_by_id[key] for key in references[code] if key in assets_by_id]
        local_probes = [row for row in probes if row.variety.code == code]
        proof_rows = [row for row in proofs if variety and row['variety_id'] == variety.pk]
        decision_rows = [row for row in decisions if variety and row['variety_id'] == variety.pk]
        rows.append({'variety': code, 'language': variety.language if variety else code.split('-')[0],
            'source_file_candidate_definitions': definitions[code],
            'database': {'candidate_series': len({row.series for row in real}), 'candidate_versions': len(real),
                'candidate_states_all_versions': dict(Counter(row.state for row in real)),
                'latest_candidate_versions': len(latest), 'latest_candidate_states': dict(Counter(row.state for row in latest)),
                'demo_series': len({row.series for row in demo}), 'demo_versions': len(demo),
                'demo_states_all_versions': dict(Counter(row.state for row in demo)),
                'current_published_demo_versions': current_catalog(Activity.objects.filter(variety=variety, is_demo=True, state='published')).count() if variety else 0,
                'real_positive_review_decisions_all_versions': real_reviews[variety.pk] if variety else 0,
                'demo_positive_review_decisions_all_versions': demo_reviews[variety.pk] if variety else 0},
            'latest_candidate_audio_slots': {'total': 2 * len(latest),
                'empty': sum(not getattr(row, field) for row in latest for field in ['audio_a', 'audio_b']),
                'with_reference': sum(bool(getattr(row, field)) for row in latest for field in ['audio_a', 'audio_b'])},
            'referenced_uploaded_media_all_versions': {'unique': len(linked), 'missing_asset_ids': len(references[code] - set(assets_by_id)),
                'kinds': dict(Counter(asset.kind for asset in linked)), 'rights_status': dict(Counter(asset.rights_status for asset in linked)),
                'structured_validity': dict(Counter(asset.rights_validity for asset in linked)), 'revoked': sum(asset.revoked for asset in linked)},
            'evidence': {'total': len(proof_rows), 'categories': _counts(proof_rows, 'category'),
                'structured_validity': _counts(proof_rows, 'validity'), 'revoked': sum(row['revoked'] for row in proof_rows)},
            'availability_decisions_all_versions': dict(Counter(row['status'] for row in decision_rows)),
            'generated_packs_pending_review': sum(receipt.variety.code == code for receipt in generated_packs),
            'regional_packs': dict(Counter(row['state'] for row in packs if variety and row['variety_id'] == variety.pk)),
            'global_probe_definitions': {'real_versions': sum(not row.is_demo for row in local_probes),
                'demo_versions': sum(row.is_demo for row in local_probes), 'states': dict(Counter(row.state for row in local_probes))},
            'current_real_availability': {'practice': ready_activities[variety.pk] if verify and variety else (0 if verify else None),
                'production_followup': ready_probes[variety.pk] if verify and variety else (0 if verify else None)}})
    referenced = set().union(*references.values()) if references else set()
    return {'schema_version': 1, 'generated_at': timezone.now().isoformat(),
        'database_engine': settings.DATABASES['default']['ENGINE'].rsplit('.', 1)[-1],
        'scope': 'Editorial aggregates only; no patient, care, goal, administration, user or contract text in output',
        'availability_verification': 'Exact published-version files, current rights, current reviews and authorisation checked' if verify else 'Metadata only; availability is unknown',
        'source_definition_files': source_files, 'varieties': rows,
        'uploaded_media_global': {'total': len(assets), 'kinds': dict(Counter(asset.kind for asset in assets)),
            'rights_status': dict(Counter(asset.rights_status for asset in assets)),
            'structured_validity': dict(Counter(asset.rights_validity for asset in assets)),
            'revoked': sum(asset.revoked for asset in assets), 'not_referenced_in_global_editorial_scope': len(set(assets_by_id) - referenced)},
        'limitations': ['A stored file or positive historical decision is not a current clinical approval.',
            'Static editorial paths are not counted as uploaded MediaAssets.',
            'Media outside global editorial references may belong to excluded cabinet-specific protocols; no deletion is implied.',
            'Regional familiarity, competent human reviews, contracts and a use-opening decision remain separate requirements.',
            'Read-only verification is a snapshot, not a clinical validation or production latency benchmark.']}


class Command(BaseCommand):
    help = 'Read-only aggregate inventory of editorial sources, versions, demos, media and current exact-version availability.'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='Emit JSON (the default).')
        parser.add_argument('--metadata-only', action='store_true', help='Skip private byte verification; availability is reported as unknown.')

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(build_inventory(verify=not options['metadata_only']), ensure_ascii=False, indent=2))
