"""Fictional test fixtures only. Never imported by deployment or seed commands."""
import io
import uuid
import wave
from datetime import date
from PIL import Image
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from catalog.models import MediaAsset, EditorialGrant, Review
from catalog.readiness import snapshot_media
from core.models import User
from .models import EvidenceDocument, ReviewerCompetence, AvailabilityDecision
from .services import evidence_snapshot, REQUIRED_EVIDENCE, record_competence_decision

def evidence_fixture(variety,user,category):
    return EvidenceDocument.objects.create(variety=variety,uploaded_by=user,title='Fictional '+category,category=category,provenance='Fictional regression fixture, no real authorisation',validity='unlimited',file=SimpleUploadedFile(uuid.uuid4().hex+'.txt',b'Fictional test evidence only'))

def competence_fixture(user,variety,discipline):
    EditorialGrant.objects.update_or_create(user=user,variety=variety,defaults={'edit':True,'clinical_review':True,'linguistic_review':True,'publish':True})
    competence, _ = ReviewerCompetence.objects.update_or_create(user=user,variety=variety,discipline=discipline,defaults={'professional_role':'Fictional reviewer','experience':'Fictional test declaration','active':True})
    verifier_name='qualification-checker-'+str(variety.pk)[:8]
    verifier, _ = User.objects.get_or_create(username=verifier_name,defaults={'email':verifier_name+'@fictional.example'})
    EditorialGrant.objects.update_or_create(user=verifier,variety=variety,defaults={'publish':True})
    current=competence.current_verification
    if not current or current.status!='verified':
        record_competence_decision(verifier,competence.pk,'verified','Fictional test fixture: identity and variety scope independently checked.',date(2026,1,1))
    return competence

def media_fixture(variety,user,kind,rights=None,word='دار'):
    rights = rights or evidence_fixture(variety,user,'rights')
    stream=io.BytesIO()
    if kind=='image':
        Image.new('RGB',(20,20),'teal').save(stream,format='PNG'); extension='png'
    else:
        with wave.open(stream,'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(8000);audio.writeframes(__import__('core.testing',fromlist=['pcm_fixture']).pcm_fixture()[44:])
        extension='wav'
    provenance={key:'Fictional test only' for key in ['holder','licence','permitted_use','territory','duration','attribution','adult_speaker_permission']}
    if kind == 'audio': provenance['audio'] = {'text': word, 'variety': variety.code, 'source': 'synthetic'}
    return MediaAsset.objects.create(rights_validity='unlimited',uploaded_by=user,kind=kind,file=SimpleUploadedFile(uuid.uuid4().hex+'.'+extension,stream.getvalue()),rights='Fictional test rights only',rights_status='original_documented',rights_evidence=rights,provenance=provenance)

def prepare_activity_fixture(activity,clinical,linguistic=None):
    if linguistic is None:
        linguistic=User.objects.create_user(username='linguistic-'+uuid.uuid4().hex[:8],email=uuid.uuid4().hex+'@fictional.example',password='Fictional-Test-2026!')
    variety=activity.variety
    competence_fixture(clinical,variety,'clinical');competence_fixture(linguistic,variety,'linguistic')
    rights=evidence_fixture(variety,clinical,'rights')
    familiar=evidence_fixture(variety,clinical,'familiarity')
    for key,kind in [('image_a','image'),('image_b','image'),('audio_a','audio'),('audio_b','audio')]:
        asset=media_fixture(variety,clinical,kind,rights,word=getattr(activity, 'word_' + key[-1]))
        ref='editorial/asset-'+str(asset.pk) if kind=='image' else settings.PUBLIC_ORIGIN+'/fr/media/'+str(asset.pk)+'/'
        setattr(activity,key,ref)
    activity.item_metadata={key:{'meaning':'Fictional word definition','segments':['p','a'],'target_occurrences':[{'index':0,'phoneme':'p','position':'initial'}],'accepted_variants':[],'familiarity':{'evidence':str(familiar.pk),'sha256':familiar.sha256}} for key in ['a','b']}
    activity.media_manifest=snapshot_media(activity)
    activity.transcription_a=activity.transcription_a or '/pa/'
    activity.transcription_b=activity.transcription_b or '/ba/'
    activity.state='review';activity.save()
    Review.objects.create(activity=activity,reviewer=clinical,kind='clinical',approved=True,note='Fictional regression approval')
    Review.objects.create(activity=activity,reviewer=linguistic,kind='linguistic',approved=True,note='Fictional regression approval')
    return linguistic

def availability_fixture(module,variety,version,actor):
    competence_fixture(actor,variety,'clinical')
    docs=[evidence_fixture(variety,actor,category) for category in REQUIRED_EVIDENCE]
    from .opening import target_queryset, target_snapshot
    target = next((row for row in target_queryset(actor, module).filter(variety=variety) if row.fingerprint() == version), None)
    assert target is not None, 'Fictional availability fixtures require an actual content target'
    return AvailabilityDecision.objects.create(module=module,variety=variety,version=version,status='available',scope='Fictional test only, no authorised clinical use',reason='Fictional regression fixture',decided_by=actor,evidence=evidence_snapshot(docs),target_snapshot=target_snapshot(module, target))
