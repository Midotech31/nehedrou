"""A13/A14 regressions: real server forms and the shipped JavaScript controller."""
import io
import json
import shutil
import subprocess
import uuid
from html.parser import HTMLParser
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from care.models import PracticeSession, Program, ProgramItem
from catalog.models import Activity, Variety
from . import tests as original_tests


class DOMTree(HTMLParser):
    void={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self,response):
        super().__init__(convert_charrefs=True)
        self.root={'tag':'document','attrs':{},'children':[]}
        self.stack=[self.root]
        self.nodes=[]
        self.feed(response.content.decode('utf-8'))
    def handle_starttag(self,tag,attributes):
        node={'tag':tag,'attrs':dict(attributes),'children':[]}
        self.stack[-1]['children'].append(node)
        self.nodes.append(node)
        if tag not in self.void:self.stack.append(node)
    def handle_endtag(self,tag):
        for index in range(len(self.stack)-1,0,-1):
            if self.stack[index]['tag']==tag:
                del self.stack[index:]
                break
    def handle_data(self,text):self.stack[-1]['children'].append(text)
    def find(self,attribute,value=None):
        return next(node for node in self.nodes if attribute in node['attrs'] and (value is None or node['attrs'][attribute]==value))
    @classmethod
    def text(cls,node):
        return ''.join(child if isinstance(child,str) else cls.text(child) for child in node['children'])


def execute_controller(case,response,scenario,expected=None):
    if not shutil.which('node'):
        case.skipTest('Node is required for the guided activity runtime regression')
    payload={'tree':DOMTree(response).root,'scenario':scenario,'expected':expected or {}}
    result=subprocess.run([shutil.which('node'),str(Path(settings.BASE_DIR)/'core/tests_helpers/guided_activity_runtime.js')],cwd=settings.BASE_DIR,input=json.dumps(payload),text=True,capture_output=True,timeout=20)
    case.assertEqual(result.returncode,0,result.stderr)
    output=json.loads(result.stdout)
    case.assertEqual(output['status'],'passed')
    return output


def assert_controls(case,response):
    tree=DOMTree(response)
    for attribute in ['data-step-back','data-step-next','data-step-pause','data-step-resume','data-stop-activity']:
        case.assertEqual(tree.find(attribute)['attrs'].get('type'),'button')
    error=tree.find('data-answer-error')
    group=tree.find('id','id_answer')
    case.assertEqual(error['attrs']['role'],'alert')
    case.assertEqual(group['attrs']['aria-describedby'],error['attrs']['id'])
    case.assertIn('hidden',error['attrs'])
    case.assertEqual(group['attrs']['tabindex'],'-1')
    return tree


@override_settings(DEMO_MODE=True,MFA_REQUIRED=False)
class PublicPracticeGuidanceTests(SimpleTestCase):
    # A public preview still cannot touch child records or save a report.
    def test_missing_choice_stays_at_step_two_with_inline_error_and_focus(self):
        response=self.client.get('/en/try/')
        assert_controls(self,response)
        execute_controller(self,response,'missing-choice')

    def test_stop_without_a_picture_choice_is_accepted_client_and_server(self):
        response=self.client.get('/en/try/')
        execute_controller(self,response,'stop-without-choice')
        result=self.client.post('/en/try/',{'completion':'stopped','parent_report':'help'})
        self.assertContains(result,'Stopped · no answer counted')
        self.assertNotContains(result,'data-guided-activity')

    def test_pause_resume_and_navigation_keep_previous_choices_and_feedback(self):
        for language in ['fr','en','ar']:
            with self.subTest(language=language):
                execute_controller(self,self.client.get(f'/{language}/try/'),'pause-resume')

    def test_server_error_preserves_public_feedback_and_reveals_missing_choice(self):
        response=self.client.post('/en/try/',{'completion':'completed','parent_report':'difficult'})
        self.assertIn('answer',response.context['form'].errors)
        self.assertEqual(response.context['form']['parent_report'].value(),'difficult')
        execute_controller(self,response,'server-answer-error',{'completion':'completed','parent_report':'difficult'})


@override_settings(DEMO_MODE=True,MFA_REQUIRED=False)
class AssignedPracticeGuidanceTests(TestCase):
    setUpTestData=classmethod(original_tests.WorkflowTests.setUpTestData.__func__)

    def setUp(self):
        translation.activate('en')
        self.client.force_login(self.family)
        self.url=reverse('practice',args=[self.item.pk])

    def payload(self,**changes):
        ticket=self.client.get(self.url).context['form']['ticket'].value()
        return dict({'ticket':ticket,'answer':'b','completion':'completed','parent_report':'difficult','support_used':'gesture','stop_reason':'','comment':'Fictional caregiver feedback to retain.'},**changes)

    def test_assigned_next_choice_and_pause_behavior(self):
        response=self.client.get(self.url)
        assert_controls(self,response)
        execute_controller(self,response,'missing-choice')
        execute_controller(self,response,'pause-resume')
        execute_controller(self,response,'stop-without-choice')
        self.assertEqual(PracticeSession.objects.count(),0)

    def test_stopped_assignment_without_choice_keeps_feedback_and_has_no_score(self):
        data=self.payload(answer='',completion='stopped',stop_reason='fatigue')
        response=self.client.post(self.url,data)
        self.assertEqual(response.status_code,302)
        report=PracticeSession.objects.get()
        self.assertEqual((report.completion,report.answer,report.correct),('stopped','',None))
        self.assertEqual((report.parent_report,report.support_used,report.stop_reason,report.comment),('difficult','gesture','fatigue',data['comment']))

    def test_server_answer_error_preserves_all_return_fields_and_original_ticket(self):
        data=self.payload(answer='')
        response=self.client.post(self.url,data)
        self.assertEqual(response.status_code,200)
        self.assertIn('answer',response.context['form'].errors)
        fields={key:data[key] for key in ['ticket','completion','parent_report','support_used','stop_reason','comment']}
        for name,value in fields.items():self.assertEqual(response.context['form'][name].value(),value)
        execute_controller(self,response,'server-answer-error',fields)
        self.assertEqual(PracticeSession.objects.count(),0)

    def test_other_server_validation_and_service_errors_preserve_chosen_picture_and_feedback(self):
        for service_error in [False,True]:
            with self.subTest(service_error=service_error):
                data=self.payload(stop_reason='' if service_error else 'fatigue')
                if service_error:
                    with patch('core.views.record_practice',side_effect=ValidationError('Fictional retryable service refusal.')):
                        response=self.client.post(self.url,data)
                    self.assertTrue(response.context['form'].non_field_errors())
                else:
                    response=self.client.post(self.url,data)
                    self.assertIn('stop_reason',response.context['form'].errors)
                self.assertEqual(response.status_code,200)
                fields={key:data[key] for key in ['ticket','completion','parent_report','support_used','stop_reason','comment']}
                execute_controller(self,response,'server-feedback-error',fields)
        self.assertEqual(PracticeSession.objects.count(),0)

    def test_observation_mode_advances_without_an_answer_question(self):
        source=self.item.activity
        values={field.attname:getattr(source,field.attname) for field in source._meta.concrete_fields if field.name not in ['id','created_at','series','response_mode','requested_target']}
        activity=Activity.objects.create(**values,series=uuid.uuid4(),response_mode='observation',requested_target='')
        item=ProgramItem.objects.create(program=self.program,activity=activity,position=2)
        response=self.client.get(reverse('practice',args=[item.pk]))
        self.assertNotContains(response,'name="answer"')
        execute_controller(self,response,'observation')

    def test_private_pair_precautions_and_sources_remain_in_collapsed_adult_guide(self):
        document=json.loads((Path(settings.BASE_DIR)/'docs/arabic-library-v1.json').read_text(encoding='utf-8'))
        source=next(row for row in document['activities'] if row['word_a']=='جَمَل' and row['kind']=='phonological_contrast')
        values=dict(source)
        values.pop('variety_code')
        values.update(series=uuid.uuid4(),is_demo=True,state='published')
        variety=Variety.objects.create(code='ar-msa-pilot',language='ar',label='Fictional MSA only')
        activity=Activity.objects.create(variety=variety,**values)
        self.child.varieties.add(variety)
        program=Program.objects.create(organization=self.org,child=self.child,variety=variety,created_by=self.pro,title='Fictional caution-preservation program')
        item=ProgramItem.objects.create(program=program,activity=activity)
        response=self.client.get(reverse('practice',args=[item.pk]))
        tree=DOMTree(response)
        brief=next(node for node in tree.nodes if node['tag']=='details' and 'practice-brief' in node['attrs'].get('class','').split())
        self.assertNotIn('open',brief['attrs'])
        text=tree.text(brief)
        guide=source['practice_guide']['fr']
        for content in [guide['audience'],guide['review_notes'],*guide['limits'],source['evidence_sources'][0]['scope']]:
            self.assertIn(content,text)
        self.assertIn('/ħamal/',text)
        self.assertIn('/ħaml/',text)
        first_step=tree.find('data-activity-step','1')
        self.assertLess(tree.nodes.index(first_step),tree.nodes.index(brief))

    def test_legacy_activity_without_structured_guide_keeps_original_precautions(self):
        self.assertFalse(self.item.activity.practice_guide)
        response=self.client.get(self.url)
        tree=DOMTree(response)
        brief=next(node for node in tree.nodes if node['tag']=='details' and 'practice-brief' in node['attrs'].get('class','').split())
        self.assertNotIn('open',brief['attrs'])
        for content in [self.item.activity.population,self.item.activity.limitations]:
            self.assertIn(content,tree.text(brief))
            self.assertTrue(any(node['tag']=='p' and node['attrs'].get('lang')=='und' and DOMTree.text(node)==content for node in tree.nodes))
        self.assertIn('NOT approved minimal pairs',tree.text(brief))
