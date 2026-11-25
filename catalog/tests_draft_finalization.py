"""Fictional normal-form saves and real PG races; no human approval or voice."""
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from django.db import connection, connections, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from catalog.authoring import GUIDE_LABELS
from catalog.finalization import RECEIPT_KEY
from catalog.models import Activity, DraftWorkingCopy, EditorialGrant, Review, Variety
from catalog.services import clone_version
from core.models import AuditEvent, User
from qualification.test_support import evidence_fixture, media_fixture
TEST_SETTINGS = dict(
    DEMO_MODE=False,
    MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)

class FinalizationFixture:

    def install(self):
        self.actor = User.objects.create_user('finalization-author', 'finalization@example.test')
        self.other = User.objects.create_user('finalization-other', 'finalization-other@example.test')
        self.variety = Variety.objects.create(code='ar-msa-pilot', language='ar', label='Fictional Arabic scope')
        for actor in [self.actor, self.other]:
            EditorialGrant.objects.create(user=actor, variety=self.variety, edit=True)
        self.url = reverse('editorial_create')
        self.client.force_login(self.actor)

    def body(self, identifier, *, complete=False, actor=None):
        actor = actor or self.actor
        data = {
            'working_copy': str(identifier),
            'content_baseline': '',
            'variety': str(self.variety.pk),
            'title': 'One fictional original draft',
            'kind': 'vocabulary',
            'response_mode': 'matching',
            'requested_target': 'a',
            'contrast': 'Fictional objects',
            'word_a': 'دار',
            'word_b': 'باب',
        }
        if complete:
            rights = evidence_fixture(self.variety, actor, 'rights')
            familiar = evidence_fixture(self.variety, actor, 'familiarity')
            for side, word, segments in [('a', 'دار', 'd a r'), ('b', 'باب', 'b a b')]:
                image = media_fixture(self.variety, actor, 'image', rights)
                audio = media_fixture(self.variety, actor, 'audio', rights, word=word)
                self.assertTrue(image.documented and audio.documented)
                data.update({
                    'choose_image_' + side: str(image.pk),
                    'choose_audio_' + side: str(audio.pk),
                    'familiarity_evidence_' + side: str(familiar.pk),
                    'segments_' + side: segments,
                    'meaning_' + side: 'Fictional meaning',
                    'transcription_' + side: '/fictional/',
                })
            data.update(population='Software fixture only', limitations='Never real clinical use', rights='Fictional rights only')
            for code in ['fr', 'en', 'ar']:
                data['instructions_' + code] = 'Fictional software instructions.'
                for key in GUIDE_LABELS:
                    data['guide_' + code + '_' + key] = 'Fictional software guide.'
        return data

    def autosave(self, client, identifier):
        return client.post(reverse('editorial_autosave', args=[identifier]), json.dumps({
            'fields': {'title': 'Incomplete private work', 'variety': str(self.variety.pk)},
            'revision': 0,
            'activity': '',
            'base_digest': '',
        }), content_type='application/json')

@override_settings(**TEST_SETTINGS)
class DraftFinalizationTests(FinalizationFixture, TestCase):

    def setUp(self):
        self.install()

    def test_complete_first_form_retry_creates_one_exact_draft_and_one_receipt(self):
        page = self.client.get(self.url)
        identifier = page.context['working_id']
        self.assertFalse(DraftWorkingCopy.objects.exists())
        data = self.body(identifier, complete=True)
        first = self.client.post(self.url, data)
        second = self.client.post(self.url, data)
        self.assertEqual((first.status_code, second.status_code), (302, 302))
        self.assertEqual(first.url, second.url)
        saved = Activity.objects.get()
        copy = DraftWorkingCopy.objects.get()
        self.assertTrue(copy.committed)
        self.assertEqual(copy.activity_id, saved.pk)
        self.assertEqual(set(copy.data), {RECEIPT_KEY})
        self.assertNotIn(data['title'], json.dumps(copy.data))
        self.assertEqual(copy.data[RECEIPT_KEY]['result'], str(saved.pk))
        self.assertEqual(AuditEvent.objects.filter(action='catalog.draft_saved').count(), 1)
        self.assertEqual(saved.state, 'draft')
        self.assertFalse(saved.is_demo)
        self.assertFalse(Review.objects.exists())

    def test_changed_payload_returns_conflict_and_link_without_overwriting_receipt(self):
        identifier = uuid.uuid4()
        data = self.body(identifier)
        first = self.client.post(self.url, data)
        before = DraftWorkingCopy.objects.get().data
        changed = self.client.post(self.url, {**data, 'title': 'Different authored intent'})
        self.assertEqual(changed.status_code, 409)
        self.assertContains(changed, first.url, status_code=409)
        self.assertNotContains(changed, 'author-config', status_code=409)
        self.assertNotContains(changed, '?resume=', status_code=409)
        self.assertNotContains(changed, 'working-save', status_code=409)
        self.assertContains(changed, self.url, status_code=409)
        self.assertEqual(Activity.objects.count(), 1)
        self.assertEqual(DraftWorkingCopy.objects.get().data, before)

    def test_autosaved_copy_is_consumed_and_late_autosave_cannot_reopen_it(self):
        identifier = uuid.uuid4()
        self.assertEqual(self.autosave(self.client, identifier).status_code, 200)
        result = self.client.post(self.url, self.body(identifier))
        self.assertEqual(result.status_code, 302)
        self.assertEqual(self.autosave(self.client, identifier).status_code, 404)
        self.assertEqual(self.client.get(self.url + '?resume=' + str(identifier)).status_code, 404)
        self.assertEqual(Activity.objects.count(), 1)

    def test_restored_form_keys_must_match_and_existing_work_data_is_preserved(self):
        identifier = uuid.uuid4()
        self.assertEqual(self.autosave(self.client, identifier).status_code, 200)
        old = DraftWorkingCopy.objects.get().data.copy()
        url = self.url + '?resume=' + str(identifier)
        data = self.body(identifier, complete=True)
        wrong = self.client.post(url, {**data, 'working_copy': str(uuid.uuid4())})
        self.assertEqual(wrong.status_code, 404)
        self.assertFalse(Activity.objects.exists())
        self.assertEqual(self.client.post(url, data).status_code, 302)
        stored = DraftWorkingCopy.objects.get().data.copy()
        stored.pop(RECEIPT_KEY)
        self.assertEqual(stored, old)

    def test_foreign_actor_cannot_replay_or_reclaim_creation_id(self):
        identifier = uuid.uuid4()
        data = self.body(identifier)
        first = self.client.post(self.url, data)
        self.client.force_login(self.other)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, first.url, status_code=404)
        self.assertEqual(Activity.objects.count(), 1)

    def test_revoked_exact_edit_scope_prevents_replay_even_when_another_scope_remains(self):
        identifier = uuid.uuid4()
        data = self.body(identifier)
        first = self.client.post(self.url, data)
        saved = Activity.objects.get()
        newer = clone_version(self.actor, saved)
        response = self.client.post(self.url, data)
        self.assertEqual(response.url, first.url)
        self.assertNotEqual(response.url, reverse('editorial_detail', args=[newer.pk]))
        other_scope = Variety.objects.create(code='fr-replay-other', language='fr', label='Fictional other scope')
        EditorialGrant.objects.create(user=self.actor, variety=other_scope, edit=True)
        EditorialGrant.objects.filter(user=self.actor, variety=self.variety).update(edit=False)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, first.url, status_code=403)
        self.assertEqual(Activity.objects.count(), 2)

    def test_invalid_first_form_claims_no_id_and_can_be_corrected_with_same_id(self):
        identifier = uuid.uuid4()
        data = self.body(identifier)
        response = self.client.post(self.url, {**data, 'title': ''})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Activity.objects.exists())
        self.assertFalse(DraftWorkingCopy.objects.exists())
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertEqual(Activity.objects.count(), 1)

    def test_old_clients_without_identity_keep_their_existing_save_path(self):
        data = self.body(uuid.uuid4())
        data.pop('working_copy')
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertFalse(DraftWorkingCopy.objects.exists())

    def test_legacy_committed_copy_is_not_invented_into_a_receipt(self):
        identifier = uuid.uuid4()
        DraftWorkingCopy.objects.create(pk=identifier, owner=self.actor, committed=True, data={'title': 'Historical work only'})
        self.assertEqual(self.client.post(self.url, self.body(identifier)).status_code, 404)
        self.assertFalse(Activity.objects.exists())

    def test_autosave_cannot_supply_a_server_receipt(self):
        identifier = uuid.uuid4()
        response = self.client.post(reverse('editorial_autosave', args=[identifier]), json.dumps({'fields': {RECEIPT_KEY: 'forged'}, 'revision': 0}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(DraftWorkingCopy.objects.exists())

@override_settings(**TEST_SETTINGS)
class DraftFinalizationConcurrencyTests(FinalizationFixture, TransactionTestCase):

    @staticmethod
    def pid():
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '8s'")
            cursor.execute("SET statement_timeout = '12s'")
            cursor.execute('SELECT pg_backend_pid()')
            return cursor.fetchone()[0]

    def blocked(self, holder, worker, future):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and (not future.done()):
            with connection.cursor() as cursor:
                cursor.execute('SELECT %s = ANY(pg_blocking_pids(%s))', [holder, worker])
                if cursor.fetchone()[0]:
                    return
            time.sleep(0.01)
        self.fail('The normal form request did not wait for the expected real PostgreSQL lock.')

    def cookies(self, actor):
        client = Client()
        client.force_login(actor)
        return client.cookies

    @skipUnlessDBFeature('has_select_for_update')
    def test_same_actor_simultaneous_first_posts_return_one_result(self):
        self.install()
        identifier = uuid.uuid4()
        data = self.body(identifier, complete=True)
        cookies = self.cookies(self.actor)
        barrier = threading.Barrier(2)

        def post():
            connections.close_all()
            try:
                self.pid()
                client = Client()
                client.cookies = cookies
                barrier.wait(5)
                response = client.post(self.url, data)
                return (response.status_code, response.get('Location'))
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: post(), range(2)))
        self.assertEqual([r[0] for r in results], [302, 302])
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(Activity.objects.count(), 1)
        self.assertEqual(DraftWorkingCopy.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.draft_saved').count(), 1)

    @skipUnlessDBFeature('has_select_for_update')
    def test_distinct_actors_racing_to_claim_absent_uuid_never_share_a_result(self):
        self.install()
        identifier = uuid.uuid4()
        barrier = threading.Barrier(2)
        original = DraftWorkingCopy.objects.create
        second_variety = Variety.objects.create(code='fr-collision-fixture', language='fr', label='Fictional collision scope')
        EditorialGrant.objects.create(user=self.other, variety=second_variety, edit=True)
        bodies = [self.body(identifier, complete=True), self.body(identifier, actor=self.other)]
        bodies[1]['variety'] = str(second_variety.pk)
        cookies = [self.cookies(actor) for actor in [self.actor, self.other]]

        def claim(*args, **kwargs):
            if kwargs.get('pk') == identifier:
                barrier.wait(5)
            return original(*args, **kwargs)

        def post(index):
            connections.close_all()
            try:
                self.pid()
                client = Client()
                client.cookies = cookies[index]
                response = client.post(self.url, bodies[index])
                return (response.status_code, response.get('Location'))
            finally:
                connections.close_all()
        with patch.object(DraftWorkingCopy.objects, 'create', side_effect=claim), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(post, range(2)))
        self.assertEqual(sorted((r[0] for r in results)), [302, 404])
        self.assertIsNone(next((r[1] for r in results if r[0] == 404)))
        saved = Activity.objects.get()
        copy = DraftWorkingCopy.objects.get()
        self.assertEqual(copy.activity_id, saved.pk)
        winner = 0 if results[0][0] == 302 else 1
        self.assertEqual(copy.owner_id, [self.actor, self.other][winner].pk)

    def ordered_autosave(self, first_kind):
        self.install()
        identifier = uuid.uuid4()
        data = self.body(identifier)
        cookies = self.cookies(self.actor)
        paused, release, started = (threading.Event(), threading.Event(), threading.Event())
        first_thread = []
        pids = {}
        original = DraftWorkingCopy.save

        def pause_after_copy_save(instance, *args, **kwargs):
            result = original(instance, *args, **kwargs)
            if first_thread and threading.get_ident() == first_thread[0] and (instance.pk == identifier) and (not instance.committed):
                paused.set()
                if not release.wait(6):
                    raise AssertionError('The first save was not released.')
            return result

        def run(kind, first):
            connections.close_all()
            try:
                pids[kind] = self.pid()
                client = Client()
                client.cookies = cookies
                if first:
                    first_thread.append(threading.get_ident())
                else:
                    started.set()
                response = self.autosave(client, identifier) if kind == 'auto' else client.post(self.url, data)
                return (response.status_code, response.get('Location'))
            finally:
                connections.close_all()
        second_kind = 'final' if first_kind == 'auto' else 'auto'
        with patch.object(DraftWorkingCopy, 'save', pause_after_copy_save), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run, first_kind, True)
            try:
                self.assertTrue(paused.wait(4))
                second = pool.submit(run, second_kind, False)
                self.assertTrue(started.wait(3))
                self.blocked(pids[first_kind], pids[second_kind], second)
            finally:
                release.set()
            outcomes = {first_kind: first.result(14), second_kind: second.result(14)}
        self.assertEqual(outcomes['final'][0], 302)
        self.assertEqual(outcomes['auto'][0], 200 if first_kind == 'auto' else 404)
        self.assertEqual(Activity.objects.count(), 1)
        self.assertTrue(DraftWorkingCopy.objects.get().committed)

    @skipUnlessDBFeature('has_select_for_update')
    def test_autosave_first_is_consumed_by_waiting_normal_save(self):
        self.ordered_autosave('auto')

    @skipUnlessDBFeature('has_select_for_update')
    def test_normal_save_first_prevents_waiting_autosave_from_creating_ghost_work(self):
        self.ordered_autosave('final')

    @skipUnlessDBFeature('has_select_for_update')
    def test_replay_waiting_for_account_lock_rechecks_revoked_edit_grant(self):
        self.install()
        identifier = uuid.uuid4()
        data = self.body(identifier)
        first = self.client.post(self.url, data)
        self.assertEqual(first.status_code, 302)
        cookies = self.cookies(self.actor)
        started = threading.Event()
        worker = []

        def replay_request():
            connections.close_all()
            try:
                worker.append(self.pid())
                started.set()
                client = Client()
                client.cookies = cookies
                response = client.post(self.url, data)
                return (response.status_code, response.get('Location'))
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                User.objects.select_for_update(no_key=True).get(pk=self.actor.pk)
                holder = self.pid()
                future = pool.submit(replay_request)
                self.assertTrue(started.wait(3))
                self.blocked(holder, worker[0], future)
                EditorialGrant.objects.filter(user=self.actor, variety=self.variety).update(edit=False)
            self.assertEqual(future.result(14), (403, None))
        self.assertEqual(Activity.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.draft_saved').count(), 1)

    @skipUnlessDBFeature('has_select_for_update')
    def test_first_creation_and_real_publishing_change_keep_variety_before_account(self):
        self.install()
        from catalog.publishing_access import change_publishing_access
        operator = User.objects.create_user('fictional-finalization-operator', 'operator-finalization@example.test', is_superuser=True)
        EditorialGrant.objects.filter(user=self.actor, variety=self.variety).update(publish=True)
        arguments = {
            'actor_username': operator.username,
            'account_username': self.actor.username,
            'variety_code': self.variety.code,
            'operation': 'revoke',
        }
        plan = change_publishing_access(**arguments)
        identifier = uuid.uuid4()
        data = self.body(identifier)
        cookies = self.cookies(self.actor)
        started = threading.Event()
        worker = []

        def create_request():
            connections.close_all()
            try:
                worker.append(self.pid())
                client = Client()
                client.cookies = cookies
                started.set()
                response = client.post(self.url, data)
                return response.status_code
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Variety.objects.select_for_update().get(pk=self.variety.pk)
                holder = self.pid()
                future = pool.submit(create_request)
                self.assertTrue(started.wait(3))
                self.blocked(holder, worker[0], future)
                changed = change_publishing_access(**arguments, expected_plan=plan['plan_sha256'])
                self.assertTrue(changed['changed'])
            self.assertEqual(future.result(14), 302)
        self.assertFalse(EditorialGrant.objects.get(user=self.actor, variety=self.variety).publish)
        self.assertEqual(Activity.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.draft_saved').count(), 1)
