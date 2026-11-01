"""UI transition choices preserve scoped permissions and human publication gates."""
import uuid
from html.parser import HTMLParser

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from care.models import Child
from core.models import AuditEvent, Membership, Organization, User
from followup.models import ProbeDefinition, ProbeReview
from followup.tests import item
from qualification.models import LexicalPack, PackReview
from .models import Activity, EditorialGrant, Review, Variety


class TransitionFormParser(HTMLParser):
    def __init__(self, action):
        super().__init__()
        self.action = action
        self.form_count = 0
        self.in_form = False
        self.in_state = False
        self.targets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.in_form = attrs.get('action') == self.action
            self.form_count += int(self.in_form)
        elif tag == 'select' and self.in_form:
            self.in_state = attrs.get('name') == 'state'
        elif tag == 'option' and self.in_form and self.in_state:
            self.targets.append(attrs.get('value'))

    def handle_endtag(self, tag):
        if tag == 'form':
            self.in_form = False
            self.in_state = False
        elif tag == 'select':
            self.in_state = False


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class EditorialTransitionVisibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.variety = Variety.objects.create(
            code='fr-transition-fixture', language='fr', label='Synthetic transition variety')
        cls.foreign_variety = Variety.objects.create(
            code='ar-transition-foreign', language='ar', label='Other synthetic variety')
        cls.actors = {}
        for name, capabilities in [
                ('editor', {'edit': True}),
                ('publisher', {'publish': True}),
                ('full', {'edit': True, 'publish': True}),
                ('clinical', {'clinical_review': True}),
                ('linguistic', {'linguistic_review': True})]:
            actor = User.objects.create_user(name + '-transition', name + '@transition.example.test')
            EditorialGrant.objects.create(user=actor, variety=cls.variety, **capabilities)
            cls.actors[name] = actor
        cls.foreign = User.objects.create_user('foreign-transition', 'foreign@transition.example.test')
        EditorialGrant.objects.create(user=cls.foreign, variety=cls.foreign_variety, edit=True, publish=True)
        cls.activity = Activity.objects.create(
            variety=cls.variety, series=uuid.uuid4(), title='Synthetic unapproved activity',
            contrast='p/b', word_a='pa', word_b='ba',
            instructions={'fr': 'Fictif', 'en': 'Fictional', 'ar': 'مثال وهمي'}, is_demo=False)
        cls.definition = ProbeDefinition.objects.create(
            variety=cls.variety, authored_by=cls.actors['editor'],
            title='Synthetic unapproved protocol', protocol='Synthetic protocol only',
            task='picture_naming', target_phoneme='p', target_position='initial',
            target_scope={'position': 'initial', 'context': 'isolated_word'},
            items=[item(0)], is_demo=False)
        cls.pack = LexicalPack.objects.create(
            series=uuid.uuid4(), variety=cls.variety, created_by=cls.actors['editor'],
            title='Synthetic unapproved pack', region='Fictional region',
            scope='Synthetic scope', population='Fictional population',
            indications='Synthetic design only', limits='No clinical approval')

    def contents(self):
        return [
            ('activity', self.activity, 'editorial_detail', 'editorial_transition'),
            ('definition', self.definition, 'followup:definition_detail', 'followup:definition_transition'),
            ('pack', self.pack, 'qualification:pack_detail', 'qualification:pack_transition'),
        ]

    def state_fixture(self, obj, state):
        # A persisted-state fixture exercises GET rendering without creating reviews,
        # approving content, or relaxing the actual transition/publication services.
        type(obj).objects.filter(pk=obj.pk).update(state=state)
        obj.state = state

    def snapshot(self):
        return (
            list(Activity.objects.order_by('pk').values()),
            list(ProbeDefinition.objects.order_by('pk').values()),
            list(LexicalPack.objects.order_by('pk').values()),
            list(EditorialGrant.objects.order_by('pk').values()),
            AuditEvent.objects.count(), Review.objects.count(),
            ProbeReview.objects.count(), PackReview.objects.count(),
        )

    def assert_choices(self, response, transition_route, obj, expected):
        self.assertEqual(response.status_code, 200)
        self.assertEqual([target for target, _label in response.context['transition_choices']], expected)
        parser = TransitionFormParser(reverse(transition_route, args=[obj.pk]))
        parser.feed(response.content.decode())
        self.assertEqual(parser.targets, expected)
        self.assertEqual(parser.form_count, int(bool(expected)))

    def test_choices_use_current_state_and_actor_capability_for_each_content_type(self):
        # Explicit product expectations catch stale, same-state and terminal options.
        standard = {
            'editor': {'draft': ['review'], 'review': ['draft'], 'approved': ['draft'],
                       'published': [], 'withdrawn': []},
            'publisher': {'draft': [], 'review': ['approved'], 'approved': ['published'],
                          'published': ['withdrawn'], 'withdrawn': []},
            'full': {'draft': ['review'], 'review': ['draft', 'approved'],
                     'approved': ['draft', 'published'], 'published': ['withdrawn'], 'withdrawn': []},
            'clinical': dict.fromkeys(['draft', 'review', 'approved', 'published', 'withdrawn'], []),
            'linguistic': dict.fromkeys(['draft', 'review', 'approved', 'published', 'withdrawn'], []),
        }
        packs = {
            'editor': {'draft': ['review'], 'review': ['draft'], 'published': [], 'withdrawn': []},
            'publisher': {'draft': [], 'review': ['published'], 'published': ['withdrawn'], 'withdrawn': []},
            'full': {'draft': ['review'], 'review': ['draft', 'published'],
                     'published': ['withdrawn'], 'withdrawn': []},
            'clinical': dict.fromkeys(['draft', 'review', 'published', 'withdrawn'], []),
            'linguistic': dict.fromkeys(['draft', 'review', 'published', 'withdrawn'], []),
        }
        for name, obj, detail_route, transition_route in self.contents():
            expectations = packs if name == 'pack' else standard
            for actor_name, states in expectations.items():
                self.client.force_login(self.actors[actor_name])
                for state, expected in states.items():
                    with self.subTest(content=name, actor=actor_name, state=state):
                        self.state_fixture(obj, state)
                        before = self.snapshot()
                        response = self.client.get(reverse(detail_route, args=[obj.pk]))
                        self.assert_choices(response, transition_route, obj, expected)
                        self.assertEqual(self.snapshot(), before)

    def test_reviewers_are_told_to_wait_for_submission_in_three_languages(self):
        notices = {
            'en': 'This draft must be submitted by an editor before the review form becomes available.',
            'fr': 'Un éditeur doit soumettre ce brouillon avant l’ouverture du formulaire de relecture.',
            'ar': 'يجب أن يقدّم محرّر هذه المسودة للمراجعة قبل إتاحة نموذج المراجعة.',
        }
        for actor_name in ['clinical', 'linguistic']:
            self.client.force_login(self.actors[actor_name])
            for language, notice in notices.items():
                with translation.override(language):
                    for name, obj, detail_route, transition_route in self.contents():
                        with self.subTest(actor=actor_name, language=language, content=name):
                            self.state_fixture(obj, 'draft')
                            before = self.snapshot()
                            response = self.client.get(reverse(detail_route, args=[obj.pk]))
                            self.assert_choices(response, transition_route, obj, [])
                            self.assertTrue(response.context['review_waiting_for_submission'])
                            self.assertFalse(response.context['can_review'])
                            self.assertContains(response, notice)
                            self.assertContains(response, 'class="review-waiting-for-submission"')
                            self.assertEqual(self.snapshot(), before)
                            self.state_fixture(obj, 'review')
                            response = self.client.get(reverse(detail_route, args=[obj.pk]))
                            self.assertFalse(response.context['review_waiting_for_submission'])
                            self.assertTrue(response.context['can_review'])
                            self.assertNotContains(response, 'class="review-waiting-for-submission"')

    def test_demo_protocol_never_offers_approval_or_publication(self):
        ProbeDefinition.objects.filter(pk=self.definition.pk).update(is_demo=True)
        for actor_name in ['publisher', 'full']:
            self.client.force_login(self.actors[actor_name])
            expected = [] if actor_name == 'publisher' else ['draft']
            for state in ['review', 'approved']:
                with self.subTest(actor=actor_name, state=state):
                    self.state_fixture(self.definition, state)
                    response = self.client.get(reverse('followup:definition_detail', args=[self.definition.pk]))
                    self.assert_choices(response, 'followup:definition_transition', self.definition, expected)

    def test_other_variety_does_not_grant_access_or_transition(self):
        self.client.force_login(self.foreign)
        for name, obj, detail_route, transition_route in self.contents():
            with self.subTest(content=name):
                before = self.snapshot()
                self.assertEqual(self.client.get(reverse(detail_route, args=[obj.pk])).status_code, 404)
                self.assertEqual(self.client.post(reverse(transition_route, args=[obj.pk]),
                    {'state': 'review'}).status_code, 404)
                self.assertEqual(self.snapshot(), before)

    def test_forged_transitions_preserve_permission_denials_and_content(self):
        for name, obj, _detail_route, transition_route in self.contents():
            cases = [('clinical', 'draft', 'review'), ('linguistic', 'draft', 'review'),
                     ('publisher', 'draft', 'review'),
                     ('editor', 'review', 'published' if name == 'pack' else 'approved')]
            for actor_name, state, target in cases:
                with self.subTest(content=name, actor=actor_name, state=state, target=target):
                    self.state_fixture(obj, state)
                    self.client.force_login(self.actors[actor_name])
                    before = self.snapshot()
                    response = self.client.post(reverse(transition_route, args=[obj.pk]), {'state': target})
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(self.snapshot(), before)

    def test_terminal_and_skipped_state_posts_remain_rejected(self):
        self.client.force_login(self.actors['full'])
        for name, obj, _detail_route, transition_route in self.contents():
            for state, target in [('draft', 'published'), ('withdrawn', 'draft')]:
                with self.subTest(content=name, state=state, target=target):
                    self.state_fixture(obj, state)
                    before = self.snapshot()
                    response = self.client.post(reverse(transition_route, args=[obj.pk]), {'state': target})
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(self.snapshot(), before)

    def test_real_approval_options_do_not_bypass_human_publication_gates(self):
        self.client.force_login(self.actors['publisher'])
        for name, obj, detail_route, transition_route in self.contents():
            with self.subTest(content=name):
                self.state_fixture(obj, 'review')
                target = 'published' if name == 'pack' else 'approved'
                response = self.client.get(reverse(detail_route, args=[obj.pk]))
                self.assert_choices(response, transition_route, obj, [target])
                before = self.snapshot()
                response = self.client.post(reverse(transition_route, args=[obj.pk]), {'state': target})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.snapshot(), before)

    def test_practice_protocol_author_keeps_submission_without_editorial_permission(self):
        author = User.objects.create_user('practice-transition', 'practice@transition.example.test')
        organization = Organization.objects.create(name='Synthetic transition practice')
        Membership.objects.create(user=author, organization=organization, role='clinician')
        child = Child.objects.create(
            organization=organization, responsible=author, code='Synthetic transition child', age_years=5)
        child.varieties.add(self.variety)
        ProbeDefinition.objects.filter(pk=self.definition.pk).update(
            organization=organization, authored_by=author, state='draft')
        self.client.force_login(author)
        before = self.snapshot()
        response = self.client.get(reverse('followup:definition_detail', args=[self.definition.pk]))
        self.assert_choices(response, 'followup:definition_transition', self.definition, ['review'])
        self.assertEqual(self.snapshot(), before)