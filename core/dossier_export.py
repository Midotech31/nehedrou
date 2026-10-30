"""Versioned dossier serialization; all entry points retain current access checks."""
import copy
import re

from django.http import Http404
from django.utils import timezone

from core.access import professional_children, visible_children
from followup.models import (ClinicalGoal, ProbeDefinition, ProbeAdministration, ProbeExposure,
                             ParentCoaching, HomePracticeFeedback)
from followup.services import professional_report, reserved_words_for
from followup.validation import reserve_word_key


def record(obj, fields=None, exclude=()):
    """Only domain models are passed here; FK values are stable local identifiers."""
    names = fields or [field.attname for field in obj._meta.concrete_fields]
    return {name: copy.deepcopy(getattr(obj, name)) for name in names if name not in exclude}


def professional_program_details(program, row):
    """Complete domain records from relations already prefetched by export_child."""
    row.update(record(program))
    item_rows = {str(item['id']): item for item in row['items']}
    for item in program.items.all():
        exported = item_rows[str(item.pk)]
        exported.update(record(item))
        sessions = {str(session['id']): session for session in exported['sessions']}
        for session in item.sessions.all():
            sessions[str(session.pk)].update(record(session, exclude=('idempotency_key', 'payload_digest')))
    run_rows = {str(run['id']): run for run in row['practice_runs']}
    for run in program.export_runs:
        exported = run_rows[str(run.pk)]
        exported.update(record(run))
        tasks = {str(task['id']): task for task in exported['tasks']}
        for task in run.tasks.all():
            tasks[str(task.pk)].update(record(task, exclude=('nonce',)))
    feedback_rows = {str(feedback['id']): feedback for feedback in row['family_feedback']}
    for feedback in program.export_feedback:
        feedback_rows[str(feedback.pk)].update(record(feedback))


def followup_dossier(actor, child, professional):
    if not visible_children(actor).filter(pk=child.pk).exists():
        raise Http404
    if professional and not professional_children(actor).filter(pk=child.pk).exists():
        raise Http404
    exclusions = [
        {'category': 'binary_files', 'reason': 'JSON contains exact historical references and digests; binary media and evidence documents require separately authorized delivery.'},
        {'category': 'authentication_and_submission_secrets', 'reason': 'Credentials, session tokens, idempotency keys and request payload digests are excluded.'},
    ]
    if professional:
        goals = list(ClinicalGoal.objects.filter(child=child).order_by('created_at', 'pk'))
        administrations = list(ProbeAdministration.objects.filter(child=child).select_related('child', 'goal', 'definition', 'definition__variety').order_by('started_at', 'pk'))
        protocol_ids = {obj.definition_id for obj in administrations} | {obj.probe_definition_id for obj in goals if obj.probe_definition_id}
        protocols = ProbeDefinition.objects.filter(pk__in=protocol_ids).prefetch_related('reviews').order_by('series', 'version')
        observations = []
        for administration in administrations:
            report = professional_report(actor, administration)
            row = record(administration, exclude=('idempotency_key', 'payload_digest'))
            row['current_groups'] = report['groups']
            row['comparable_to_previous'] = report['comparable']
            row['later_reserved_word_exposure'] = report['contamination']
            row['ratings'] = []
            for rating in administration.ratings.prefetch_related('revisions').order_by('item_key', 'occurrence_index'):
                rating_row = record(rating)
                rating_row['current_data'] = rating.current_data()
                rating_row['revisions'] = [record(revision) for revision in sorted(rating.revisions.all(), key=lambda r: (r.created_at, str(r.pk)))]
                row['ratings'].append(rating_row)
            observations.append(row)
        data = {
            'goals': [record(goal) for goal in goals],
            'protocols': [{**record(protocol), 'variety_code': protocol.variety.code,
                'reviews': [record(review) for review in protocol.reviews.all()]} for protocol in protocols],
            'observations': observations,
            'exposures': [record(obj) for obj in ProbeExposure.objects.filter(child=child).order_by('occurred_at', 'pk')],
            'coaching': [record(obj) for obj in ParentCoaching.objects.filter(child=child).order_by('created_at', 'pk')],
            'home_practice_feedback': [record(obj, exclude=('idempotency_key', 'payload_digest')) for obj in HomePracticeFeedback.objects.filter(child=child).order_by('occurred_at', 'pk')],
        }
        # The access-continuity migration may be installed independently.
        from django.apps import apps
        if apps.is_installed('core'):
            try:
                transfer_model = apps.get_model('core', 'ChildResponsibilityTransfer')
            except LookupError:
                transfer_model = None
            if transfer_model:
                data['responsibility_transfers'] = [record(obj) for obj in transfer_model.objects.filter(child=child).order_by('created_at', 'pk')]
    else:
        shares = ProbeAdministration.objects.filter(child=child, status='finalized', shared_at__isnull=False).exclude(shared_text='').order_by('shared_at', 'pk')
        data = {
            'shared_observations': [{'id': str(obj.pk), 'shared_text': obj.shared_text, 'shared_at': obj.shared_at,
                'variety': obj.snapshot.get('variety'), 'is_demo': obj.snapshot.get('is_demo')} for obj in shares],
            'coaching': [record(obj, fields=['id', 'variety_id', 'instruction_language', 'instructions', 'example', 'accompanied_trial',
                'understanding_checked', 'next_review', 'created_at']) for obj in ParentCoaching.objects.filter(child=child).order_by('created_at', 'pk')],
            'home_practice_feedback': [record(obj, fields=['id', 'coaching_id', 'variety_id', 'participation', 'support_used',
                'difficulty', 'stop_reason', 'comment', 'occurred_at', 'created_at']) for obj in HomePracticeFeedback.objects.filter(child=child, author=actor).order_by('occurred_at', 'pk')],
        }
        exclusions.extend([
            {'category': 'professional_clinical_records', 'reason': 'Goals, protocols, raw observations, ratings, revisions, conditions, exposure records, clinician notes and responsibility history are private.',
             'record_counts': {'goals': ClinicalGoal.objects.filter(child=child).count(), 'observations': ProbeAdministration.objects.filter(child=child).count()}},
            {'category': 'unshared_or_revoked_summaries', 'reason': 'Only a currently and expressly shared finalized summary is included.'},
            {'category': 'other_caregiver_returns', 'reason': 'Only returns authored by the requesting caregiver are included.'},
            {'category': 'reserved_items', 'reason': 'Reserved program items and any remaining text containing a reserved word are withheld.'},
        ])
    return data, exclusions


def redact_reserved_family_text(payload, child):
    """Fail closed for free text accidentally mentioning a reserve; never publish the matched word."""
    guards = []
    for variety in child.varieties.all():
        for word in reserved_words_for(child, variety):
            normalized = reserve_word_key(word, variety)
            if normalized:
                guards.append((variety, re.compile(r'(?<!\w)' + re.escape(normalized) + r'(?!\w)', re.UNICODE)))
    count = 0

    def visit(value):
        nonlocal count
        if isinstance(value, str):
            if any(pattern.search(reserve_word_key(value, variety)) for variety, pattern in guards):
                count += 1
                return '[withheld: reserved content]'
        elif isinstance(value, list):
            return [visit(item) for item in value]
        elif isinstance(value, dict):
            return {key: visit(item) for key, item in value.items()}
        return value

    sanitized = copy.deepcopy(payload)
    sanitized['programs'] = visit(sanitized['programs'])
    sanitized['followup'] = visit(sanitized['followup'])
    sanitized['child']['code'] = visit(sanitized['child']['code'])
    return sanitized, count


def dossier_payload(actor, child, professional, programs, *, withheld_program_items=0):
    followup, exclusions = followup_dossier(actor, child, professional)
    payload = {
        'schema_version': 3, 'export_scope': 'professional' if professional else 'family', 'exported_at': timezone.now(),
        'child': {'id': str(child.pk), 'code': child.code, 'age_years': child.age_years, 'active': child.active,
            'varieties': list(child.varieties.values_list('code', flat=True))},
        'programs': programs, 'followup': followup, 'exclusions': exclusions,
    }
    if professional:
        payload['child'].update(record(child))
    if not professional:
        payload, redacted_count = redact_reserved_family_text(payload, child)
        payload['exclusions'].append({'category': 'reserved_content_withheld', 'program_items': withheld_program_items, 'text_fields': redacted_count})
    return payload
