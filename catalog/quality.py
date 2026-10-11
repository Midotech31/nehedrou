"""Editorial completeness and exact-version review packs, never clinical scoring."""
import csv
import hashlib
import io
import json
import zipfile
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET
from .content_validation import validate_minimal_pair
from .models import Variety


def completeness(activity):
    native = activity.variety.language
    guide = activity.practice_guide.get(native, {})
    checks = [
        ('words', _('Two words or prompts and their meanings'), bool(activity.word_a and activity.word_b and all(activity.item_metadata.get(side, {}).get('meaning') for side in ['a', 'b']))),
        ('guide', _('Objective, audience, steps, help and limits in the content language'), bool(guide and all(guide.get(key) for key in ['objective','audience','discover','listen','exchange','support','limits','review_notes']))),
        ('instructions', _('Family instructions in the three interface languages'), all(activity.instructions.get(code, '').strip() for code in ['fr','en','ar'])),
        ('population', _('Intended population and precautions'), bool(activity.population.strip() and activity.limitations.strip())),
        ('images', _('Two available illustrations'), all(activity.image_available(getattr(activity, 'image_' + side)) for side in ['a','b'])),
        ('audio', _('Two available adult audio files'), all(activity.audio_available(getattr(activity, 'audio_' + side)) for side in ['a','b'])),
        ('transcriptions', _('Transcriptions to be checked against the recordings'), bool(activity.transcription_a.strip() and activity.transcription_b.strip())),
        ('sources', _('Documented sources and their scope'), bool(activity.evidence_sources)),
        ('rights', _('Recorded usage rights'), bool(activity.rights.strip())),
    ]
    if activity.kind == 'phonological_contrast':
        try:
            validate_minimal_pair(activity.item_metadata, activity.response_mode)
            contrast_ok = True
        except ValidationError:
            contrast_ok = False
        checks.append(('contrast', _('One structurally aligned phoneme contrast'), contrast_ok))
    return {'checks': [{'key':key, 'label':label, 'complete':bool(ok)} for key,label,ok in checks],
            'completed': sum(bool(ok) for key,label,ok in checks), 'total': len(checks),
            'missing': [label for key,label,ok in checks if not ok]}


def scoped_catalogue(request):
    from .views import editor, editorial_activities
    editor(request.user)
    qs = editorial_activities(request.user).select_related('variety')
    if request.GET.get('variety'):
        qs = qs.filter(variety__code=request.GET['variety'])
    if request.GET.get('kind'):
        qs = qs.filter(kind=request.GET['kind'])
    # Old withdrawn versions remain accessible in history, not in the default queue.
    if request.GET.get('state'):
        qs = qs.filter(state=request.GET['state'])
    else:
        qs = qs.exclude(state='withdrawn')
    return qs.order_by('variety__code', 'title', '-version')


@login_required
@require_GET
def dashboard(request):
    from .models import Activity
    from django.core.paginator import Paginator
    activities = list(scoped_catalogue(request))
    rows = [{'activity': activity, **completeness(activity)} for activity in activities]
    missing_audio = sum(any(check['key'] == 'audio' and not check['complete'] for check in row['checks']) for row in rows)
    if request.GET.get('gap') == 'audio':
        rows = [row for row in rows if any(check['key'] == 'audio' and not check['complete'] for check in row['checks'])]
    elif request.GET.get('gap') == 'guide':
        rows = [row for row in rows if any(check['key'] == 'guide' and not check['complete'] for check in row['checks'])]
    page = Paginator(rows, 16).get_page(request.GET.get('page'))
    varieties = Variety.objects.filter(pk__in=[activity.variety_id for activity in activities]).distinct()
    response = render(request, 'editorial/quality.html', {'page':page, 'total_content':len(activities), 'missing_audio':missing_audio,
        'varieties':varieties, 'kinds':Activity.KIND_CHOICES, 'selected_variety':request.GET.get('variety',''),
        'selected_kind':request.GET.get('kind',''), 'selected_gap':request.GET.get('gap','')})
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_GET
def review_pack(request):
    catalogue = list(scoped_catalogue(request))
    # Export contains editorial text only: no patients, accounts, recordings or private evidence files.
    records = []
    recordings = io.StringIO(newline='')
    audio_writer = csv.writer(recordings)
    audio_writer.writerow(['activity_id','version','content_sha256','spoken_variety','side','word','intended_meaning','proposed_transcription','adult_speaker_reference','regional_usage','recording_filename','consent_evidence_reference','linguistic_decision','clinical_decision'])
    table = io.StringIO(newline='')
    writer = csv.writer(table)
    writer.writerow(['activity_id','version','content_sha256','variety','kind','word_a','word_b','missing_editorial_items','clinical_decision','linguistic_decision','reviewer_note'])
    for activity in catalogue:
        quality = completeness(activity)
        record = {'id':str(activity.pk), 'version':activity.version, 'content_sha256':activity.fingerprint(),
            'title':activity.title, 'variety':activity.variety.code, 'kind':activity.kind, 'theme':activity.theme,
            'response_mode':activity.response_mode, 'contrast':activity.contrast,
            'words':{'a':activity.word_a,'b':activity.word_b}, 'transcriptions':{'a':activity.transcription_a,'b':activity.transcription_b},
            'instructions':activity.instructions, 'practice_guide':activity.practice_guide, 'evidence_sources':activity.evidence_sources,
            'item_metadata':activity.item_metadata, 'population':activity.population, 'limitations':activity.limitations,
            'rights_description':activity.rights, 'is_demo':activity.is_demo, 'state':activity.state,
            'editorial_completeness':quality, 'clinical_validation': 'not_inferred_from_completeness'}
        for side in ['a', 'b']:
            audio_row = [str(activity.pk), activity.version, activity.fingerprint(), activity.variety.code, side,
                getattr(activity, 'word_' + side), activity.item_metadata.get(side, {}).get('meaning', ''),
                getattr(activity, 'transcription_' + side), '', '', '', '', '', '']
            audio_writer.writerow(["'" + str(value) if str(value).lstrip().startswith(('=','+','-','@','\t','\r')) else value for value in audio_row])
        records.append(record)
        row = [str(activity.pk), activity.version, activity.fingerprint(), activity.variety.code, activity.kind, activity.word_a, activity.word_b,
               ' / '.join(str(value) for value in quality['missing']), '', '', '']
        # Spreadsheet formula injection must not turn authored text into executable cells.
        writer.writerow(["'" + str(value) if str(value).lstrip().startswith(('=','+','-','@','\t','\r')) else value for value in row])
    payload = json.dumps({'schema':'nehedrou-review-pack-v1','scope':'Editorial review only. No imported approval is accepted.', 'activities':records}, ensure_ascii=False, default=str, indent=2).encode('utf-8')
    checklist = (_('Review each exact version: indication, intended meaning, local familiarity, image recognition, recording and transcription, allowable variants, instructions, rights and limits.') + '\n\n' +
        _('Darja: document the region and family usage. Do not assume a Standard Arabic word or synthetic voice represents the child’s variety.') + '\n\n' +
        _('Minimal pairs: check phonemic contrast, aligned position and structure, meaningful words and the child’s actual error profile. A spelling difference alone is insufficient.') + '\n\n' +
        _('Enter decisions through the existing review workflow. This exported sheet cannot approve or publish an activity.') + '\n\n' + _('Recording prompts are proposals: an adult native speaker and the reviewers must confirm meaning, regional usage, phonemes, consent and rights before recording and release. Blank decisions are not approvals.')).encode('utf-8')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('activities.json',payload)
        archive.writestr('review.csv',table.getvalue().encode('utf-8-sig'))
        archive.writestr('recording_prompts.csv',recordings.getvalue().encode('utf-8-sig'))
        archive.writestr('REVIEW.txt',checklist)
        archive.writestr('activities.sha256',hashlib.sha256(payload).hexdigest())
    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = 'attachment; filename="Nehedrou_editorial_review.zip"'
    response['Cache-Control'] = 'private, no-store'
    return response
