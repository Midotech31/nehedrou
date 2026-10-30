"""Local language declarations and real selected device-voice behavior."""
import io
import json
import os
import shutil
import subprocess
import uuid
from html.parser import HTMLParser
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from care.models import Child, Program, ProgramItem
from catalog.authoring import ActivityAuthoringForm
from catalog.content_validation import validate_content_guide
from catalog.models import Activity, EditorialGrant, Variety
from catalog.templatetags.content_guide import guide_language
from catalog.templatetags.content_language import source_scope_language, source_title_language
from core.models import User


class LanguageDOM(HTMLParser):
    void={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self,html):
        super().__init__()
        self.stack=[]
        self.words=[]
        self.images=[]
        self.feed(html)
    def handle_starttag(self,tag,attributes):
        attrs=dict(attributes)
        parent=self.stack[-1][1] if self.stack else {}
        inherited={'lang':attrs.get('lang',parent.get('lang','')),'dir':attrs.get('dir',parent.get('dir',''))}
        if tag=='img': self.images.append((attrs,inherited))
        if tag not in self.void: self.stack.append((tag,inherited))
    def handle_endtag(self,tag):
        for index in range(len(self.stack)-1,-1,-1):
            if self.stack[index][0]==tag:
                del self.stack[index:]
                break
    def handle_data(self,text):
        if text.strip() and self.stack:
            self.words.append((text.strip(),self.stack[-1][1]))


class LocalLanguageFilterTests(SimpleTestCase):
    def test_guide_marker_is_presentational_without_language_fallback(self):
        original={'fr':{'objective':'Français'}}
        selected=guide_language(original,'fr')
        self.assertEqual(selected['language'],'fr')
        self.assertNotIn('language',original['fr'])
        self.assertEqual(guide_language(original,'ar'),{})

    def test_bibliography_languages_use_explicit_or_exact_inspected_metadata(self):
        registry=json.loads((Path(settings.BASE_DIR)/'docs/source-language-declarations-20261030.json').read_text(encoding='utf-8'))
        known=registry['entries'][0]
        legacy={key:known[key] for key in ('url','scope')}
        self.assertEqual(source_scope_language(legacy),'fr')
        self.assertEqual(source_scope_language(dict(legacy,scope='An unrelated new statement.')),'und')
        self.assertEqual(source_scope_language(dict(legacy,scope_language='en')),'en')
        self.assertEqual(source_title_language({'title':'Unknown bibliography title'}),'und')
        self.assertEqual(source_title_language({'title_language':'ar'}),'ar')
        explicit={'title':'Source','url':'https://example.test/source','scope':'Known scope','title_language':'en','scope_language':'fr'}
        validate_content_guide({},[explicit])
        with self.assertRaises(ValidationError):
            validate_content_guide({},[dict(explicit,scope_language='untrusted value')])


@override_settings(DEMO_MODE=True,MFA_REQUIRED=False)
class CrossLocaleLanguageDOMTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with patch.dict(os.environ,{'DEMO_PASSWORD':'Fictional-Language-2026!'}):
            call_command('seed_demo',stdout=io.StringIO())
        cls.user=User.objects.get(username='praticien')
        cls.child=Child.objects.get(code='Lina · fictif')
        source=cls.child.programs.get().items.get().activity
        values={field.attname:getattr(source,field.attname) for field in source._meta.concrete_fields if field.name not in ['id','created_at','series','variety','title']}
        registry=json.loads((Path(settings.BASE_DIR)/'docs/source-language-declarations-20261030.json').read_text(encoding='utf-8'))
        scope=registry['entries'][0]
        cls.legacy_scope=scope['scope']
        for suffix,code,words,ipa in [('english','en-us-general-pilot',('coat','goat'),('/koʊt/','/goʊt/')),('darja','ar-dz-pilot',('دار','نار'),('',''))]:
            variety=Variety.objects.get(code=code)
            cls.child.varieties.add(variety)
            guide={language:{'objective':'Objectif français' if language=='fr' else 'هدف عربي','audience':'Public fictif' if language=='fr' else 'جمهور خيالي','review_notes':'À relire' if language=='fr' else 'للمراجعة',**{key:['Texte français' if language=='fr' else 'نص عربي'] for key in ['discover','listen','exchange','support','limits']}} for language in ('fr','ar')}
            activity=Activity.objects.create(**dict(values,series=uuid.uuid4(),variety=variety,title='Fictional '+suffix,kind='vocabulary',word_a=words[0],word_b=words[1],transcription_a=ipa[0],transcription_b=ipa[1],instructions={'fr':'Consigne française unique','ar':'تعليمة عربية مميزة','en':'Fictional instruction'},practice_guide=guide,evidence_sources=[{'title':'Unspecified source title','url':scope['url'],'scope':scope['scope']}]))
            program=Program.objects.create(organization=cls.child.organization,child=cls.child,variety=variety,created_by=cls.user,title='Fictional '+suffix+' program')
            item=ProgramItem.objects.create(program=program,activity=activity)
            setattr(cls,suffix,(activity,program,item))

    def setUp(self):
        self.client.force_login(self.user)

    def assert_local_language(self,response,word,instruction,word_language,instruction_language):
        self.assertEqual(response.status_code,200)
        dom=LanguageDOM(response.content.decode())
        self.assertTrue(any(text==word and attrs['lang']==word_language for text,attrs in dom.words),(word,word_language))
        self.assertTrue(any(text==instruction and attrs['lang']==instruction_language for text,attrs in dom.words),(instruction,instruction_language))
        self.assertTrue(any(attrs.get('alt')==word and language['lang']==word_language for attrs,language in dom.images))
        return dom

    def test_ar_interface_french_instructions_english_words_and_ipa(self):
        activity,program,item=self.english
        for route,pk in [('activity_detail',activity.pk),('print_program',program.pk),('practice',item.pk)]:
            with self.subTest(route=route),translation.override('ar'):
                response=self.client.get(reverse(route,args=[pk]))
                dom=self.assert_local_language(response,'coat','Texte français' if route=='practice' else 'Consigne française unique','en-US','fr')
                if route=='activity_detail':
                    self.assertTrue(any(text=='/koʊt/' and attrs=={'lang':'und-fonipa','dir':'ltr'} for text,attrs in dom.words))
                    self.assertTrue(any(text==self.legacy_scope and attrs['lang']=='fr' for text,attrs in dom.words))
                    heading=translation.gettext('Caregiver instructions')
                    self.assertTrue(any(text==heading and attrs['lang']=='ar' for text,attrs in dom.words))

    def test_fr_interface_arabic_instructions_darja_words(self):
        self.user.instruction_language='ar'
        self.user.save(update_fields=['instruction_language'])
        activity,program,item=self.darja
        for route,pk in [('activity_detail',activity.pk),('print_program',program.pk),('practice',item.pk)]:
            with self.subTest(route=route),translation.override('fr'):
                response=self.client.get(reverse(route,args=[pk]))
                dom=self.assert_local_language(response,'دار','نص عربي' if route=='practice' else 'تعليمة عربية مميزة','ar-DZ','ar')
                self.assertTrue(any(text=='دار' and attrs['dir']=='rtl' for text,attrs in dom.words))
                self.assertNotContains(response,'data-device-voice')

    def test_existing_source_language_metadata_survives_unchanged_draft_fields(self):
        activity,_,_=self.english
        activity=Activity.objects.get(pk=activity.pk)
        activity.state='draft'
        activity.evidence_sources=[{'title':'English title','url':'https://example.test/source','scope':'Portée française','title_language':'en','scope_language':'fr'}]
        # Use an editable draft, preserving the previous published source version.
        values={field.attname:getattr(activity,field.attname) for field in activity._meta.concrete_fields if field.name not in ['id','created_at','series']}
        draft=Activity.objects.create(**values,series=uuid.uuid4())
        EditorialGrant.objects.create(user=self.user,variety=draft.variety,edit=True)
        data={'variety':str(draft.variety_id),'title':draft.title,'kind':'vocabulary','response_mode':'matching','contrast':draft.contrast,'word_a':draft.word_a,'word_b':draft.word_b,'is_demo':'on','source_0_title':'English title','source_0_url':'https://example.test/source','source_0_scope':'Portée française'}
        form=ActivityAuthoringForm(data,actor=self.user,instance=draft)
        self.assertTrue(form.is_valid(),form.errors)
        saved=form.save()
        self.assertEqual(saved.evidence_sources[0]['title_language'],'en')
        self.assertEqual(saved.evidence_sources[0]['scope_language'],'fr')


@skipUnless(shutil.which('node'),'Node is required for the device-voice runtime regression')
class DeviceVoiceRuntimeTests(SimpleTestCase):
    def test_fallback_discloses_actual_accent_and_never_enables_darja_or_contrasts(self):
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
function block(language,variety,kind='vocabulary',demo='true') {
  const nodes={};
  for(const key of ['button','[data-speech-status]','[data-speech-voice]','[data-speech-language]','[data-speech-accent]']) nodes[key]={hidden:true,textContent:'',dataset:{speechText:'coat'},addEventListener(name,fn){this[name]=fn;}};
  return {dataset:{language,variety,kind,demo,ready:'ready',missing:'missing',playing:'playing',failed:'failed'},nodes,querySelector(key){return nodes[key];}};
}
const lexical=block('en-US','en-us-general-pilot'),darja=block('ar-SA','ar-dz-pilot'),contrast=block('en-US','en-us-general-pilot','phonological_contrast'),real=block('en-US','en-us-general-pilot','vocabulary','false');
const blocks=[lexical,darja,contrast,real],events={};
let installed=[{lang:'en-GB',name:'Fictional UK voice'},{lang:'ar-SA',name:'Fictional MSA voice'}],utterance;
const engine={getVoices:()=>installed,addEventListener(name,fn){events[name]=fn;},cancel(){},speak(value){utterance=value;}};
const document={querySelectorAll:q=>q==='[data-device-voice]'?blocks:[],addEventListener(name,fn){events[name]=fn;},dispatchEvent(event){if(events[event.type])events[event.type]();}};
const window={speechSynthesis:engine,addEventListener(){}};
vm.runInNewContext(fs.readFileSync('static/device-voice.js','utf8'),{document,window,Map,Set,Event:class{constructor(type){this.type=type;}},SpeechSynthesisUtterance:class{constructor(text){this.text=text;}}});
assert.strictEqual(lexical.nodes['button'].disabled,false);
assert.strictEqual(lexical.nodes['[data-speech-language]'].textContent,'en-GB');
assert.strictEqual(lexical.nodes['[data-speech-accent]'].hidden,false);
lexical.nodes['button'].click();
assert.strictEqual(utterance.lang,'en-GB');
for(const blocked of [darja,contrast,real]) {assert.strictEqual(blocked.nodes['button'].disabled,true);assert.strictEqual(blocked.nodes['[data-speech-voice]'].hidden,true);}
installed.push({lang:'en-US',name:'Fictional exact voice'});events.voiceschanged();
assert.strictEqual(lexical.nodes['[data-speech-language]'].textContent,'en-US');
assert.strictEqual(lexical.nodes['[data-speech-accent]'].hidden,true);
installed=[];events.voiceschanged();
assert.strictEqual(lexical.nodes['button'].disabled,true);
assert.strictEqual(lexical.nodes['[data-speech-language]'].textContent,'');
console.log('DEVICE_VOICE_RUNTIME_OK');
'''
        result=subprocess.run([shutil.which('node'),'-e',script],cwd=settings.BASE_DIR,text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('DEVICE_VOICE_RUNTIME_OK',result.stdout)
