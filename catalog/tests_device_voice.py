"""Unreviewed device synthesis never becomes a real or Darja model."""
import uuid
import re
from html import unescape
from django.test import TestCase, override_settings
from django.urls import reverse
from care.models import Program, ProgramItem
from catalog.models import Activity, Variety
from core import tests as workflow
from core.practice_runs import start_run, task_url

@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class DeviceVoiceGatingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        workflow.WorkflowTests.setUpTestData.__func__(cls)
        cls.msa=Variety.objects.create(code='ar-msa-pilot',language='ar',label='Fictional MSA')
        values={field.attname:getattr(cls.item.activity,field.attname) for field in Activity._meta.concrete_fields if field.name not in ['id','created_at','series','variety','title']}
        cls.lexical=Activity.objects.create(**dict(values,series=uuid.uuid4(),variety=cls.msa,title='Fictional word',kind='vocabulary'))
    def test_only_fictional_msa_lexical_activities_allow_device_voice(self):
        self.assertTrue(self.lexical.device_voice_allowed)
        self.assertFalse(self.item.activity.device_voice_allowed)
        with override_settings(DEMO_MODE=False):
            self.assertFalse(self.lexical.device_voice_allowed)
        self.lexical.is_demo=False
        self.assertFalse(self.lexical.device_voice_allowed)
        self.lexical.is_demo=True
        for kind in ['word_pair','phonological_contrast']:
            self.lexical.kind=kind
            self.assertFalse(self.lexical.device_voice_allowed)
        self.lexical.kind='vocabulary'
        self.lexical.variety=Variety(code='ar-dz-pilot',language='ar',label='Fictional Darja')
        self.assertFalse(self.lexical.device_voice_allowed)
    def test_detail_marks_synthesis_unreviewed_and_never_claims_a_model_file(self):
        self.client.force_login(self.pro)
        response=self.client.get(reverse('activity_detail',args=[self.lexical.pk]))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'data-device-voice',count=2)
        self.assertContains(response,'device-voice.js')
        self.assertFalse(self.lexical.audio_a)
        self.assertFalse(self.lexical.audio_b)
        self.child.varieties.add(self.msa)
        program = Program.objects.create(organization=self.org, child=self.child,
            variety=self.msa, created_by=self.pro, title='Fictional MSA voice practice')
        item = ProgramItem.objects.create(program=program, activity=self.lexical, position=1)
        run = start_run(self.pro, program)
        for url in [reverse('practice', args=[item.pk]), task_url(run.tasks.get())]:
            with self.subTest(url=url):
                practice = self.client.get(url)
                self.assertEqual(practice.status_code, 200)
                html = practice.content.decode()
                title = re.search(r'<title>(.*?)</title>', html, re.DOTALL).group(1)
                self.assertTrue(unescape(title).endswith(self.lexical.title + ' · Nehedrou'))
                self.assertNotIn('<', title)
                self.assertNotIn('>', title)
                self.assertEqual(html.count('device-voice.js'), 1)
                self.assertContains(practice, 'data-device-voice', count=2)
