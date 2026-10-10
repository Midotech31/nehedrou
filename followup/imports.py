from django.utils.translation import gettext as _
"""Reproducible draft-only importer for the original conception-1 contract."""
import copy
import hashlib
import json
import uuid
from django.core.exceptions import ValidationError
from django.db import transaction
from catalog.models import Variety
from .models import ProbeDefinition

@transaction.atomic
def import_definitions(data):
    if not isinstance(data, dict) or data.get('schema_version') != 'conception-1' or data.get('clinical_validation') is not False:
        raise ValidationError(_('Expected the original, unapproved conception-1 protocol contract.'))
    examples = data.get('examples')
    if not isinstance(examples, list) or not examples:
        raise ValidationError(_('The contract needs explicit draft examples.'))
    results = []
    seen = set()
    for row in examples:
        if row.get('state') != 'draft' or row.get('publication_allowed') is not False or row.get('approvals_supplied') is not False or row.get('audio_supplied') is not False or row.get('normed') is not False:
            raise ValidationError(_('Only unapproved, non-normed drafts without supplied media can be imported.'))
        series = uuid.uuid5(uuid.NAMESPACE_URL, 'nehdrou-original-probe:' + row['id'])
        version = row['version']
        if (series, version) in seen:
            raise ValidationError(_('A protocol version cannot be repeated in the source file.'))
        seen.add((series, version))
        variety = Variety.objects.get(code=row['variety'])
        items = []
        for proposed in row['items']:
            item = copy.deepcopy(proposed)
            item['ipa'] = item.pop('ipa_proposed')
            item['exposure_plan'] = {'trained_candidate': 'trained', 'reserved_candidate': 'reserved'}[item['exposure_plan']]
            item['reviewed'] = False
            item['selected_attempt'] = 1
            # Source IPA is provisional and supplies no validated segmentation.
            item.setdefault('segments', [])
            item.setdefault('meaning', '')
            item.setdefault('target_occurrences', [])
            items.append(item)
        values = dict(variety=variety, title=row['id'], protocol=row['indication'] + '\n' + row['limitations'],
            task=row['task'], target_phoneme=row['target_phoneme_proposed'], target_position=row['target_position'],
            items=items, rights='Original Nehedrou conception specification; stimulus, media and commercial rights remain to be documented.',
            rights_status='unknown', evidence={'source': 'Paquet_Clinique_Nehedrou_20261010/donnees/12_Sondes_exemples_DRAFT.json',
                'source_id': row['id'], 'source_digest': hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                'clinical_validation': False}, is_demo=False)
        existing = ProbeDefinition.objects.filter(series=series, version=version).first()
        if existing:
            if any(getattr(existing, k) != v for k, v in values.items()):
                raise ValidationError(_('The existing protocol version differs; import an explicit new version instead of overwriting history.'))
            results.append((existing, False))
        else:
            results.append((ProbeDefinition.objects.create(series=series, version=version, state='draft', **values), True))
    return results
