"""Editorial completeness and exact-version review packs, never clinical scoring."""
import csv
import hashlib
import io
import json
import re
import zipfile
from urllib.parse import urlencode
from uuid import UUID
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.db.models import Q
from core.storage_health import file_exists
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET
from .content_validation import validate_minimal_pair
from .models import Activity, Variety
from .integrity import prepare_activities
from .review_dossier import review_dossier
from .readiness import referenced_asset
from .recording_queue import RECORDING_CONTEXT_COLUMNS, recording_context_by_side


REVIEW_PAGE_SIZE = 16
QUALITY_FILTERS = ('activity', 'variety', 'kind', 'gap', 'state', 'versions', 'content')


def guide_complete(activity):
    guide = activity.practice_guide.get(activity.variety.language, {})
    return bool(guide and all(guide.get(key) for key in ['objective','audience','discover','listen','exchange','support','limits','review_notes']))


def media_available(activity, reference, kind):
    # Same presence semantics as Activity, using the page's batched asset graph.
    asset = referenced_asset(reference, kind)
    if asset:
        formats = ['PNG','JPEG','WEBP'] if kind == 'image' else ['WAV','MP3']
        return bool(asset.technical_metadata.get('format') in formats and asset.rights.strip() and file_exists(asset.file))
    return activity.image_available(reference) if kind == 'image' and not reference.startswith('editorial/asset-') else False


def completeness(activity):
    checks = [
        ('words', _('Two words or prompts and their meanings'), bool(activity.word_a and activity.word_b and all(activity.item_metadata.get(side, {}).get('meaning') for side in ['a', 'b']))),
        ('guide', _('Objective, audience, steps, help and limits in the content language'), guide_complete(activity)),
        ('instructions', _('Family instructions in the three interface languages'), all(activity.instructions.get(code, '').strip() for code in ['fr','en','ar'])),
        ('population', _('Intended population and precautions'), bool(activity.population.strip() and activity.limitations.strip())),
        ('images', _('Two available illustrations'), all(media_available(activity, getattr(activity, 'image_' + side), 'image') for side in ['a','b'])),
        ('audio', _('Two available adult audio files'), all(media_available(activity, getattr(activity, 'audio_' + side), 'audio') for side in ['a','b'])),
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
    from .content_catalog import editorial_versions
    editor(request.user)
    target = request.GET.get('activity')
    qs = editorial_versions(editorial_activities(request.user).select_related('variety'),
        include_history=bool(target) or request.GET.get('versions') == 'all', content=request.GET.get('content', ''))
    if request.GET.get('variety'):
        qs = qs.filter(variety__code=request.GET['variety'])
    if request.GET.get('kind'):
        qs = qs.filter(kind=request.GET['kind'])
    if target:
        try:
            qs = qs.filter(pk=UUID(target))
        except (ValueError, TypeError, AttributeError):
            raise Http404 from None
        if not qs.exists():
            raise Http404
    # An explicitly selected historical version stays inspectable in its scope.
    if request.GET.get('state'):
        qs = qs.filter(state=request.GET['state'])
    elif not target:
        qs = qs.exclude(state='withdrawn')
    return qs.order_by('variety__code', 'title', '-version', 'pk')


def filter_gaps(catalogue, gap):
    if gap == 'audio':
        # Reference completeness only; no whole-catalogue storage scan.
        return catalogue.filter(Q(audio_a='') | Q(audio_b=''))
    if gap == 'guide':
        identifiers = [activity.pk for activity in catalogue.only('id','practice_guide','variety_id','variety__language') if not guide_complete(activity)]
        return catalogue.filter(pk__in=identifiers)
    return catalogue


def selection_notice(request, body, status):
    filters = {key: request.GET[key] for key in (*QUALITY_FILTERS, 'page') if request.GET.get(key)}
    url = reverse('editorial_quality')
    response = render(request, 'editorial/review_selection_notice.html', {
        'body': body,
        'return_url': f'{url}?{urlencode(filters)}' if filters else url,
    }, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


def review_selection(items):
    if not 1 <= len(items) <= REVIEW_PAGE_SIZE:
        raise ValueError
    states = dict(Activity._meta.get_field('state').choices)
    selected = {}
    for item in items:
        pk, state, digest = item.split(':')
        identifier = UUID(pk)
        if identifier in selected or state not in states or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError
        selected[identifier] = (state, digest)
    return selected


@login_required
@require_GET
def dashboard(request):
    from django.core.paginator import Paginator
    catalogue = scoped_catalogue(request)
    total_content = catalogue.count()
    varieties = Variety.objects.filter(pk__in=catalogue.values('variety_id')).distinct()
    catalogue = filter_gaps(catalogue, request.GET.get('gap'))
    page = Paginator(catalogue, REVIEW_PAGE_SIZE).get_page(request.GET.get('page'))
    activities = prepare_activities(list(page.object_list))
    page.object_list = [{'activity': activity, **completeness(activity), 'dossier': review_dossier(activity)} for activity in activities]
    missing_audio = sum(any(check['key'] == 'audio' and not check['complete'] for check in row['checks']) for row in page)
    response = render(request, 'editorial/quality.html', {'page':page, 'total_content':total_content, 'missing_audio':missing_audio,
        'varieties':varieties, 'kinds':Activity.KIND_CHOICES, 'selected_variety':request.GET.get('variety',''),
        'selected_kind':request.GET.get('kind',''), 'selected_gap':request.GET.get('gap',''),
        'selected_activity':request.GET.get('activity',''), 'selected_state':request.GET.get('state',''),
        'selected_versions':request.GET.get('versions',''), 'selected_content':request.GET.get('content',''),
        'batch_filters': {key: request.GET[key] for key in QUALITY_FILTERS if request.GET.get(key)}})
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_GET
def review_pack(request):
    catalogue = scoped_catalogue(request)
    selection_items = request.GET.getlist('selection_item')
    selected_mode = request.GET.get('export') == 'selected'
    selected = {}
    if selected_mode or selection_items:
        try:
            if not selected_mode:
                raise ValueError
            selected = review_selection(selection_items)
        except ValueError:
            return selection_notice(request, _('Choose one or more versions from the same page and try again.'), 400)
        catalogue = catalogue.filter(pk__in=selected)
    rows = list(filter_gaps(catalogue, request.GET.get('gap')))
    if selected_mode and len(rows) != len(selected):
        raise Http404
    catalogue = prepare_activities(rows)
    if selected_mode and any((activity.state, activity.fingerprint()) != selected[activity.pk] for activity in catalogue):
        return selection_notice(request, _('A selected version has changed. Review its current state and select it again.'), 409)
    # Export contains editorial text only: no patients, accounts, recordings or private evidence files.
    records = []
    tasks, media_rows = io.StringIO(newline=''), io.StringIO(newline='')
    task_writer, media_writer = csv.writer(tasks), csv.writer(media_rows)
    task_writer.writerow(['activity_id','version','content_sha256','spoken_variety','requirement','category','side','responsible_role','reason_codes','current_gaps','required_action','assigned_person','actual_evidence_reference','human_decision','decision_date'])
    media_writer.writerow(['activity_id','version','content_sha256','spoken_variety','field','word','kind','asset_id','sha256','rights_status','rights_validity','rights_valid_from','rights_valid_until','revoked','voice_source','missing_rights_fields','rights_evidence_id','rights_evidence_sha256','reason_codes','current_gaps',
        'predecessor_asset_id','predecessor_sha256','original_asset_id','generation_pack_id','generation_concept_id',
        'generation_variant','generation_manifest_sha256','generation_source_asset_id','generation_source_sha256'])
    recordings = io.StringIO(newline='')
    audio_writer = csv.writer(recordings)
    audio_writer.writerow(['activity_id','version','content_sha256','spoken_variety','side','word','intended_meaning','proposed_transcription','adult_speaker_reference','regional_usage','recording_filename','consent_evidence_reference','linguistic_decision','clinical_decision', *RECORDING_CONTEXT_COLUMNS])
    table = io.StringIO(newline='')
    writer = csv.writer(table)
    writer.writerow(['activity_id','version','content_sha256','variety','kind','word_a','word_b','missing_editorial_items','clinical_decision','linguistic_decision','reviewer_note','series_uuid'])
    for activity in catalogue:
        quality = completeness(activity)
        dossier = review_dossier(activity)
        for task in dossier['tasks']:
            write_csv(task_writer, [str(activity.pk), activity.version, dossier['content_sha256'], activity.variety.code,
                task['key'], task['category'], task['side'], task['responsible_role'], ' / '.join(task['reason_codes']),
                ' / '.join(task['reasons']), task['action'], '', '', '', ''])
        for media in dossier['media']:
            origin = media.get('image_origin') or media.get('audio_origin', {})
            generated = origin.get('generated', {})
            write_csv(media_writer, [str(activity.pk), activity.version, dossier['content_sha256'], activity.variety.code,
                media['field'], media['word'], media['kind'], media.get('asset_id',''), media.get('sha256',''),
                media.get('rights_status',''), media.get('rights_validity',''), media.get('rights_valid_from',''),
                media.get('rights_valid_until',''), media.get('revoked',''), media.get('voice_source',''),
                ' / '.join(media.get('missing_rights_fields',[])), media['evidence'].get('id',''),
                media['evidence'].get('sha256',''), ' / '.join(media['reason_codes']), ' / '.join(media['reasons']),
                origin.get('predecessor_asset_id',''), origin.get('predecessor_sha256',''), origin.get('original_asset_id',''),
                *(generated.get(key,'') for key in ('pack_id','concept_id','variant','manifest_sha256','source_asset_id','source_sha256'))])
        digest = dossier['content_sha256']
        audio_context = recording_context_by_side(activity, dossier, request.user)
        record = {'id':str(activity.pk), 'series':str(activity.series), 'version':activity.version, 'content_sha256':digest,
            'title':activity.title, 'variety':activity.variety.code, 'kind':activity.kind, 'theme':activity.theme,
            'response_mode':activity.response_mode, 'contrast':activity.contrast,
            'words':{'a':activity.word_a,'b':activity.word_b}, 'transcriptions':{'a':activity.transcription_a,'b':activity.transcription_b},
            'instructions':activity.instructions, 'practice_guide':activity.practice_guide, 'evidence_sources':activity.evidence_sources,
            'item_metadata':activity.item_metadata, 'population':activity.population, 'limitations':activity.limitations,
            'rights_description':activity.rights, 'is_demo':activity.is_demo, 'state':activity.state,
            'editorial_completeness':quality, 'evidence_dossier':dossier, 'clinical_validation': 'not_inferred_from_completeness'}
        for side in ['a', 'b']:
            write_csv(audio_writer, [str(activity.pk), activity.version, digest, activity.variety.code, side,
                getattr(activity, 'word_' + side), activity.item_metadata.get(side, {}).get('meaning', ''),
                getattr(activity, 'transcription_' + side), '', '', '', '', '', '', *audio_context[side]])
        records.append(record)
        row = [str(activity.pk), activity.version, digest, activity.variety.code, activity.kind, activity.word_a, activity.word_b,
               ' / '.join(str(value) for value in quality['missing']), '', '', '', str(activity.series)]
        # Spreadsheet formula injection must not turn authored text into executable cells.
        write_csv(writer, row)
    dossier_payload = json.dumps({'schema':'nehedrou-evidence-dossiers-v1',
        'scope':'Read-only documentary gaps for exact editorial versions; no clinical validation or imported approval.',
        'activities':[record['evidence_dossier'] for record in records]}, ensure_ascii=False, default=str, indent=2).encode('utf-8')
    selection = {'versions': 'exact' if request.GET.get('activity') else 'all' if request.GET.get('versions') == 'all' else 'latest',
        'content':request.GET.get('content') if request.GET.get('content') in ('candidate', 'demo') else 'all',
        'gap':request.GET.get('gap') if request.GET.get('gap') in ('audio', 'guide') else ''}
    if selected_mode:
        selection['batch'] = True
    payload = json.dumps({'schema':'nehedrou-review-pack-v1','scope':'Editorial review only. No imported approval is accepted.',
        'selection':selection, 'activities':records}, ensure_ascii=False, default=str, indent=2).encode('utf-8')
    checklist = (_('Review each exact version: indication, intended meaning, local familiarity, image recognition, recording and transcription, allowable variants, instructions, rights and limits.') + '\n\n' +
        _('Darja: document the region and family usage. Do not assume a Standard Arabic word or synthetic voice represents the child’s variety.') + '\n\n' +
        _('Minimal pairs: check phonemic contrast, aligned position and structure, meaningful words and the child’s actual error profile. A spelling difference alone is insufficient.') + '\n\n' +
        _('Enter decisions through the existing review workflow. This exported sheet cannot approve or publish an activity.') + '\n\n' + _('Recording prompts are proposals: an adult native speaker and the reviewers must confirm meaning, regional usage, phonemes, consent and rights before recording and release. Blank decisions are not approvals.')).encode('utf-8')
    checklist += ('\n\n' + _('evidence_tasks.csv lists current unmet requirements with responsible roles and actions. Assignment, evidence and human decisions remain blank. media_requirements.csv identifies the exact media and documentary gaps without exporting contracts or account identities. Recheck the live CMS before recording any decision: this download is a dated snapshot.')).encode('utf-8')
    checklist += ('\n\n' + _('The recording prompts include the current audio status for each word and a link to the exact version. When available, the collection link opens the draft for that word. Check the version fingerprint again before changing any media.')).encode('utf-8')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('activities.json',payload)
        archive.writestr('evidence_dossiers.json',dossier_payload)
        archive.writestr('evidence_dossiers.sha256',hashlib.sha256(dossier_payload).hexdigest())
        archive.writestr('evidence_tasks.csv',tasks.getvalue().encode('utf-8-sig'))
        archive.writestr('media_requirements.csv',media_rows.getvalue().encode('utf-8-sig'))
        archive.writestr('review.csv',table.getvalue().encode('utf-8-sig'))
        archive.writestr('recording_prompts.csv',recordings.getvalue().encode('utf-8-sig'))
        archive.writestr('REVIEW.txt',checklist)
        archive.writestr('activities.sha256',hashlib.sha256(payload).hexdigest())
    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = 'attachment; filename="Nehedrou_editorial_review.zip"'
    response['Cache-Control'] = 'private, no-store'
    return response


def write_csv(writer, row):
    # Apply the same formula guard to every newly exported user-controlled cell.
    writer.writerow(["'" + str(value) if str(value).lstrip().startswith(('=','+','-','@','\t','\r')) else value for value in row])
