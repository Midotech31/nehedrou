"""Real private routes with fictional guides/files; no clinical decisions."""
import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.core import signing
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import translation
from django.utils.html import escape

from catalog import tests_guided_audio as audio_tests
from catalog.authoring import GUIDE_LABELS
from catalog.guide_recovery import SALT
from catalog.media_authoring import RIGHTS_LABELS
from catalog.models import Activity, DraftWorkingCopy, EditorialGrant, Review
from catalog.working import RECOVERY_RECEIPT_KEY
from core.models import AuditEvent
from qualification.models import AvailabilityDecision
from qualification.test_support import evidence_fixture

TEST_SETTINGS = {**audio_tests.SETTINGS, 'DEMO_MODE': False}


class RecoveryFixture(audio_tests.GuidedAudioFixture):
    marker = 'هدف عربي وهمي <script>never execute</script>'

    def setUp(self):
        super().setUp()
        translation.activate('en')
        self.rights = evidence_fixture(self.variety, self.actor, 'rights')
        self.create_source(stale=True)

    def documented_audio(self, side='a'):
        values = {
            'audio_source': 'synthetic',
            'rights': 'Fictional software rights only',
            'rights_status': 'original_documented',
            'rights_validity': 'unlimited',
            'rights_evidence': str(self.rights.pk),
        }
        values.update({'rights_' + name: 'Software fixture, no actual human speaker' for name in RIGHTS_LABELS})
        saved = self.upload(side=side, data=values)
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.context['asset'].documented)
        self.assertEqual(self.associate(saved, side=side).status_code, 302)
        self.activity.refresh_from_db()

    @staticmethod
    def browser_values(form):
        values = {}
        for name, field in form.fields.items():
            if field.disabled:
                continue
            value = form[name].value()
            values[name] = 'on' if value is True else '' if value is False or value is None else str(value)
        return values

    def create_source(self, *, stale):
        if not stale:
            self.documented_audio()
        self.edit_url = reverse('editorial_edit', args=[self.activity.pk])
        page = self.client.get(self.edit_url)
        fields = self.browser_values(page.context['form'])
        fields['word_a'] = 'OLD_SAVED_WORD_NOT_TO_APPLY'
        fields['instructions_fr'] = 'UNSELECTED_SAVED_FRENCH_INSTRUCTION'
        fields['instructions_ar'] = 'تعليمة عربية وهمية للمراجعة فقط.'
        for key in GUIDE_LABELS:
            fields['guide_ar_' + key] = self.marker if key == 'objective' else 'نص وهمي للمراجعة فقط.'
        self.source_id = page.context['working_id']
        payload = {
            'fields': fields,
            'revision': 0,
            'activity': str(self.activity.pk),
            'base_digest': page.context['base_digest'],
        }
        response = self.client.post(reverse('editorial_autosave', args=[self.source_id]),
                                    json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        if stale:
            self.documented_audio()
        self.source = DraftWorkingCopy.objects.get(pk=self.source_id)
        self.url = reverse('editorial_working_reconcile', args=[self.source_id])
        self.selection = ['instructions_ar'] + ['guide_ar_' + key for key in GUIDE_LABELS]

    def comparison(self, client=None):
        response = (client or self.client).get(self.url)
        self.assertEqual(response.status_code, 200)
        return response

    def payload(self, page, selection=None):
        return {'state_token': page.context['form']['state_token'].value(),
                'select_fields': self.selection if selection is None else selection}

    def unchanged(self):
        return (Activity.objects.values().get(pk=self.activity.pk),
                DraftWorkingCopy.objects.values().get(pk=self.source_id))


@override_settings(**TEST_SETTINGS)
class GuideRecoveryTests(RecoveryFixture, TestCase):
    def test_normal_recovery_prepares_only_selected_guide_and_preserves_every_original(self):
        before = self.unchanged()
        page = self.comparison()
        self.assertContains(page, escape(self.marker))
        self.assertNotContains(page, '<script>never execute</script>')
        self.assertNotContains(page, 'OLD_SAVED_WORD_NOT_TO_APPLY')
        response = self.client.post(self.url, self.payload(page))
        self.assertEqual(response.status_code, 302)
        target = DraftWorkingCopy.objects.exclude(pk=self.source_id).get()
        self.assertEqual(target.base_digest, self.activity.fingerprint())
        self.assertEqual(target.data['guide_ar_objective'], self.marker)
        self.assertEqual(target.data['word_a'], self.activity.word_a)
        self.assertEqual(target.data['audio_a'], self.activity.audio_a)
        self.assertEqual(target.data['instructions_fr'], self.activity.instructions['fr'])
        self.assertNotEqual(target.data['instructions_fr'], self.source.data['instructions_fr'])
        self.assertEqual(target.data['variety'], str(self.activity.variety_id))
        self.assertFalse(target.committed)
        self.assertEqual(self.unchanged(), before)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.family_guide_work_recovered').count(), 1)
        self.assertFalse(Review.objects.exists())
        self.assertFalse(AvailabilityDecision.objects.exists())

    def test_recovered_copy_can_be_saved_via_normal_edit_without_losing_current_media(self):
        current_audio = self.activity.audio_a
        recovered = self.client.post(self.url, self.payload(self.comparison()))
        form_page = self.client.get(recovered.url)
        fields = self.browser_values(form_page.context['form'])
        fields.update(working_copy=str(form_page.context['working_id']),
                      content_baseline=form_page.context['base_digest'])
        response = self.client.post(recovered.url, fields)
        self.assertEqual(response.status_code, 302)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.practice_guide['ar']['objective'], self.marker)
        self.assertEqual(self.activity.word_a, 'دار')
        self.assertEqual(self.activity.audio_a, current_audio)
        self.source.refresh_from_db()
        self.assertFalse(self.source.committed)
        self.assertEqual(self.activity.state, 'draft')

    def test_identical_replay_reuses_copy_after_its_autosave_without_duplicate_audit(self):
        page = self.comparison()
        payload = self.payload(page)
        first = self.client.post(self.url, payload)
        target = DraftWorkingCopy.objects.exclude(pk=self.source_id).get()
        marker = copy.deepcopy(target.data[RECOVERY_RECEIPT_KEY])
        recovered_page = self.client.get(first.url)
        fields = self.browser_values(recovered_page.context['form'])
        fields['guide_ar_objective'] = 'Another private edit, not an Activity change'
        updated = self.client.post(reverse('editorial_autosave', args=[target.pk]), json.dumps({
            'fields': fields, 'revision': target.revision, 'activity': str(self.activity.pk),
            'base_digest': target.base_digest,
        }), content_type='application/json')
        self.assertEqual(updated.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.data[RECOVERY_RECEIPT_KEY], marker)
        replay = self.client.post(self.url, payload)
        self.assertEqual((replay.status_code, replay.url), (302, first.url))
        self.assertEqual(DraftWorkingCopy.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.family_guide_work_recovered').count(), 1)

    def test_changed_selection_or_unsupported_field_cannot_reuse_or_corrupt_recovery(self):
        page = self.comparison()
        forged = self.client.post(self.url, self.payload(page, ['word_a']))
        self.assertEqual(forged.status_code, 400)
        self.assertEqual(DraftWorkingCopy.objects.count(), 1)
        first = self.client.post(self.url, self.payload(page))
        self.assertEqual(first.status_code, 302)
        changed = self.client.post(self.url, self.payload(page, ['instructions_ar']))
        self.assertEqual(changed.status_code, 409)
        self.assertContains(changed, 'data-recovery-conflict', status_code=409)
        self.assertEqual(DraftWorkingCopy.objects.count(), 2)

    def test_other_actor_revoked_scope_and_corrupt_signature_are_denied(self):
        page = self.comparison()
        payload = self.payload(page)
        bad = self.client.post(self.url, {**payload, 'state_token': payload['state_token'] + 'tampered'})
        self.assertEqual(bad.status_code, 400)
        EditorialGrant.objects.create(user=self.other, variety=self.variety, edit=True)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, payload).status_code, 404)
        self.client.force_login(self.actor)
        EditorialGrant.objects.filter(user=self.actor, variety=self.variety).update(edit=False)
        self.assertEqual(self.client.post(self.url, payload).status_code, 403)
        self.assertEqual(DraftWorkingCopy.objects.count(), 1)

    def test_current_media_changes_invalidate_signed_comparison_without_overwrite(self):
        page = self.comparison()
        self.documented_audio(side='b')
        before = self.unchanged()
        response = self.client.post(self.url, self.payload(page))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.unchanged(), before)
        self.assertEqual(DraftWorkingCopy.objects.count(), 1)

    def test_source_revision_change_via_normal_autosave_requires_fresh_comparison(self):
        self.source.delete()
        self.create_source(stale=False)
        page = self.comparison()
        values = copy.deepcopy(self.source.data)
        values['guide_ar_objective'] = 'Changed source work after comparison'
        response = self.client.post(reverse('editorial_autosave', args=[self.source_id]), json.dumps({
            'fields': values, 'revision': self.source.revision, 'activity': str(self.activity.pk),
            'base_digest': self.source.base_digest,
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        stale = self.client.post(self.url, self.payload(page))
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(DraftWorkingCopy.objects.count(), 1)

    def test_capacity_and_set_aside_policy_stay_authoritative(self):
        extras = [DraftWorkingCopy.objects.create(owner=self.actor, data={}) for _ in range(29)]
        page = self.comparison()
        payload = self.payload(page)
        denied = self.client.post(self.url, payload)
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(DraftWorkingCopy.objects.count(), 30)
        self.client.post(reverse('editorial_working_status', args=[extras[0].pk]), {'action': 'dismiss'})
        accepted = self.client.post(self.url, payload)
        self.assertEqual(accepted.status_code, 302)
        self.assertEqual(DraftWorkingCopy.objects.filter(committed=False, dismissed=False).count(), 30)

    def test_csrf_is_required_for_new_private_copy(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        page = self.comparison(client)
        payload = self.payload(page)
        self.assertEqual(client.post(self.url, payload).status_code, 403)
        payload['csrfmiddlewaretoken'] = client.cookies['csrftoken'].value
        self.assertEqual(client.post(self.url, payload).status_code, 302)

    def test_review_transition_requires_reloading_without_creating_any_copy(self):
        page = self.comparison()
        response = self.client.post(reverse('editorial_transition', args=[self.activity.pk]), {'state': 'review'})
        self.assertEqual(response.status_code, 302)
        denied = self.client.post(self.url, self.payload(page))
        self.assertEqual(denied.status_code, 409)
        self.assertContains(denied, 'data-recovery-conflict', status_code=409)
        self.assertEqual(DraftWorkingCopy.objects.count(), 1)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.state, 'review')

    def test_private_saved_guide_never_appears_in_public_or_anonymous_responses(self):
        created = self.client.post(self.url, self.payload(self.comparison()))
        self.assertEqual(created.status_code, 302)
        anonymous = Client()
        for demo_mode in (False, True):
            with override_settings(DEMO_MODE=demo_mode):
                for language in ('en', 'fr', 'ar'):
                    with self.subTest(language=language, demo_mode=demo_mode):
                        endpoints = [(f'/{language}/', 200), (f'/{language}/try/', 200 if demo_mode else 404)]
                        for url, expected_status in endpoints:
                            response = anonymous.get(url)
                            self.assertEqual(response.status_code, expected_status)
                            self.assertNotContains(response, self.marker, status_code=expected_status)
                            self.assertNotContains(response, escape(self.marker), status_code=expected_status)
                            self.assertNotContains(response, 'OLD_SAVED_WORD_NOT_TO_APPLY', status_code=expected_status)
        for url in (self.url, created.url):
            response = anonymous.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertNotContains(response, self.marker, status_code=302)
            self.assertNotContains(response, escape(self.marker), status_code=302)

    def test_recovery_link_on_normal_resume_does_not_hash_media_and_labels_are_localized(self):
        with patch('catalog.models.Activity.fingerprint', side_effect=AssertionError('Unexpected ordinary GET hash')):
            response = self.client.get(self.edit_url + '?resume=' + str(self.source_id))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.url)
        expected = {'en': 'Recover saved family-guide fields',
                    'fr': 'Récupérer les champs du guide familial enregistré',
                    'ar': 'استرجاع حقول الدليل الأسري المحفوظ'}
        for language, title in expected.items():
            with self.subTest(language=language), translation.override(language):
                response = self.client.get(reverse('editorial_working_reconcile', args=[self.source_id]))
                self.assertContains(response, title)
                self.assertContains(response, f'<title>{title} · Nehedrou</title>')
                if language != 'en':
                    self.assertNotContains(response, expected['en'])
                self.assertContains(response, 'lang="ar" dir="rtl"')


@override_settings(**TEST_SETTINGS)
class GuideRecoveryConcurrencyTests(RecoveryFixture, TransactionTestCase):
    @staticmethod
    def worker_pid():
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '8s'")
            cursor.execute("SET statement_timeout = '12s'")
            cursor.execute('SELECT pg_backend_pid()')
            return cursor.fetchone()[0]

    def cookies(self):
        client = Client()
        client.force_login(self.actor)
        return client.cookies

    @skipUnlessDBFeature('has_select_for_update')
    def test_same_recovery_posts_create_one_private_copy(self):
        payload = self.payload(self.comparison())
        cookies = self.cookies()
        barrier = threading.Barrier(2)
        def submit():
            connections.close_all()
            try:
                self.worker_pid()
                client = Client()
                client.cookies = cookies
                barrier.wait(5)
                response = client.post(self.url, payload)
                return response.status_code, response.get('Location')
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual([row[0] for row in results], [302, 302])
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(DraftWorkingCopy.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.family_guide_work_recovered').count(), 1)

    @skipUnlessDBFeature('has_select_for_update')
    def test_normal_edit_can_finish_before_waiting_recovery_without_copy_lock_inversion(self):
        self.source.delete()
        self.create_source(stale=False)
        page = self.comparison()
        recovery_payload = self.payload(page)
        edit_page = self.client.get(self.edit_url + '?resume=' + str(self.source_id))
        fields = self.browser_values(edit_page.context['form'])
        fields['word_a'] = self.activity.word_a
        fields.update(working_copy=str(self.source_id), content_baseline=edit_page.context['base_digest'])
        cookies = self.cookies()
        locked, release, recovery_started = threading.Event(), threading.Event(), threading.Event()
        editor_threads, editor_pids, recovery_pids = [], [], []
        original = Activity.objects.select_for_update
        def pause_after_activity_lock(*args, **kwargs):
            queryset = original(*args, **kwargs)
            original_get = queryset.get
            def get(*get_args, **get_kwargs):
                activity = original_get(*get_args, **get_kwargs)
                if editor_threads and threading.get_ident() == editor_threads[0]:
                    locked.set()
                    if not release.wait(6):
                        raise AssertionError('Normal editor was not released.')
                return activity
            queryset.get = get
            return queryset
        def edit():
            connections.close_all()
            try:
                editor_pids.append(self.worker_pid())
                editor_threads.append(threading.get_ident())
                client = Client()
                client.cookies = cookies
                return client.post(self.edit_url, fields).status_code
            finally:
                connections.close_all()
        def recover():
            connections.close_all()
            try:
                recovery_pids.append(self.worker_pid())
                client = Client()
                client.cookies = cookies
                recovery_started.set()
                return client.post(self.url, recovery_payload).status_code
            finally:
                connections.close_all()
        with patch.object(Activity.objects, 'select_for_update', side_effect=pause_after_activity_lock), ThreadPoolExecutor(max_workers=2) as pool:
            editing = pool.submit(edit)
            try:
                self.assertTrue(locked.wait(4))
                recovery = pool.submit(recover)
                self.assertTrue(recovery_started.wait(3))
                deadline = time.monotonic() + 4
                blocked = False
                while time.monotonic() < deadline and not recovery.done():
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT %s = ANY(pg_blocking_pids(%s))', [editor_pids[0], recovery_pids[0]])
                        blocked = cursor.fetchone()[0]
                    if blocked:
                        break
                    time.sleep(.01)
                self.assertTrue(blocked, 'Recovery must wait for Activity without holding the working-copy lock.')
            finally:
                release.set()
            self.assertEqual(editing.result(14), 302)
            self.assertEqual(recovery.result(14), 409)
        self.assertEqual(DraftWorkingCopy.objects.count(), 1)
        self.source.refresh_from_db()
        self.assertTrue(self.source.committed)
