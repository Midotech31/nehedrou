"""Fresh write gates and real row locks, with fictional qualification fixtures.

The nested integrity scopes model separate requests: a revocation in one request
must defeat an earlier request's cached approval after it acquires its write lock.
No fixture is deployed, and no real clinical approval or speech model is created.
"""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import uuid

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature

from care.models import Program, ProgramItem, PracticeRun, PracticeRunTask, PracticeSession
from catalog.integrity import integrity_scope
from catalog.models import Activity
from catalog.services import transition
from core.models import AuditEvent, User
from core.practice_runs import start_run, task_ticket
from core.services import create_program, record_practice
from followup.models import ProbeAdministration
from followup.services import create_definition, review_definition, start_administration, transition_definition
from followup.tests import install_fixture, item as followup_item, goal as followup_goal
from qualification.models import AvailabilityDecision, EvidenceDocument
from qualification.opening import revoke_decision
from qualification.services import availability_for
from qualification.test_support import (
    availability_fixture, competence_fixture, evidence_fixture, media_fixture, prepare_activity_fixture,
)


TEST_SETTINGS = dict(
    DEMO_MODE=False, MFA_REQUIRED=False, PUBLIC_ORIGIN='https://demo.example',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}},
)


class LiveIntegrityFixture:
    def install(self):
        # Reuse the existing cabinet/child/family and exact media/review fixtures.
        install_fixture(self)
        self.activity = Activity.objects.create(
            variety=self.variety, series=uuid.uuid4(), title='Fictional live-write regression',
            contrast='p/b', word_a='pa', word_b='ba',
            instructions={'fr': 'Fictif', 'en': 'Fictional', 'ar': 'مثال وهمي'},
            population='Fictional software fixture only', rights='Fictional test only', is_demo=False,
        )
        prepare_activity_fixture(self.activity, self.pro, self.foreign)
        self.activity = transition(self.pro, self.activity.pk, 'approved')
        self.activity = transition(self.pro, self.activity.pk, 'published')
        self.decision = availability_fixture('practice', self.variety, self.activity.fingerprint(), self.pro)
        self.assertTrue(self.activity.usable)
        self.program = create_program(self.pro, self.child, self.program_data('Fictional initial attribution'))
        self.item = self.program.items.select_related('program__child', 'activity').get()

    def program_data(self, title='Fictional later attribution'):
        return dict(title=title, variety=self.variety, activities=[self.activity], guidance='', schedule='')

    def payload(self, target='a'):
        return dict(answer=target, completion='completed', parent_report='help', comment='')

    def warm_practice_and_revoke_elsewhere(self):
        self.assertTrue(self.activity.usable)
        digest = self.activity.fingerprint()
        self.assertTrue(availability_for('practice', self.variety, digest)['available'])
        with integrity_scope():
            revoked = revoke_decision(self.pro, self.decision.pk, 'Fictional concurrent revocation')
            self.assertFalse(availability_for('practice', self.variety, digest)['available'])
        # Proves that the write service must discard the original request cache;
        # calling revoke_decision in the same cache would mask this regression.
        self.assertTrue(availability_for('practice', self.variety, digest)['available'])
        return revoked

    def published_probe(self):
        # Same qualified fictional protocol construction as followup.tests;
        # all bytes, declarations and approvals exist solely in the test database.
        competence_fixture(self.pro, self.variety, 'clinical')
        competence_fixture(self.foreign, self.variety, 'linguistic')
        proofs = {category: evidence_fixture(self.variety, self.pro, category)
                  for category in ['rights', 'familiarity', 'linguistic']}
        image = media_fixture(self.variety, self.pro, 'image', proofs['rights'])
        audio = media_fixture(self.variety, self.pro, 'audio', proofs['rights'], word='mot-0')
        probe_item = followup_item(0)
        probe_item.update(
            meaning='Synthetic meaning', segments=['p'],
            target_occurrences=[{'index': 0, 'phoneme': 'p', 'position': 'initial'}],
            familiarity_verified=True, reviewed=True, image_asset=str(image.pk), audio_asset=str(audio.pk),
        )
        probe = create_definition(self.editor, dict(
            variety=self.variety, title='Fictional complete live-write protocol',
            protocol='Fictional software regression only', task='naming', target_phoneme='p',
            target_position='initial', target_scope={'position': 'initial', 'context': 'isolated_word'},
            items=[probe_item], is_demo=False, rights='Fictional test only', rights_status='original_documented',
            evidence={category + '_evidence': {'id': str(doc.pk), 'sha256': doc.sha256}
                      for category, doc in proofs.items()},
        ))
        probe = transition_definition(self.editor, probe, 'review')
        review_definition(self.pro, probe, 'clinical', True, 'Fictional regression review', 'Fictional competence',
                          expected_digest=probe.fingerprint())
        review_definition(self.foreign, probe, 'linguistic', True, 'Fictional regression review', 'Fictional competence',
                          expected_digest=probe.fingerprint())
        probe = transition_definition(self.editor, probe, 'approved')
        probe = transition_definition(self.editor, probe, 'published')
        objective = followup_goal(self, probe)
        objective.external_assessment_status = 'confirmed'
        objective.save()
        decision = availability_fixture('production_followup', self.variety, probe.fingerprint(), self.pro)
        self.assertTrue(probe.ready)
        return probe, objective, decision

    @staticmethod
    def probe_conditions():
        return {'attempt_rule': 'Predetermined first fictional attempt'}

    @staticmethod
    def probe_familiarity():
        return {'fixture-0': {'familiar': True, 'note': 'Synthetic regression fixture'}}


@override_settings(**TEST_SETTINGS)
class LiveIntegrityWriteTests(LiveIntegrityFixture, TestCase):
    def setUp(self):
        self.install()

    def test_cached_availability_cannot_authorise_a_new_program_after_revocation(self):
        counts = (Program.objects.count(), ProgramItem.objects.count(),
                  AuditEvent.objects.filter(action='program.created').count())
        with integrity_scope():
            self.warm_practice_and_revoke_elsewhere()
            with self.assertRaises(ValidationError):
                create_program(self.pro, self.child, self.program_data())
            self.assertFalse(self.activity.usable)
        self.assertEqual((Program.objects.count(), ProgramItem.objects.count(),
                          AuditEvent.objects.filter(action='program.created').count()), counts)

    def test_cached_availability_cannot_authorise_a_new_practice_report_after_revocation(self):
        with integrity_scope():
            self.warm_practice_and_revoke_elsewhere()
            with self.assertRaises(ValidationError):
                record_practice(self.family, self.item, self.payload(), {'key': str(uuid.uuid4()), 'target': 'a'})
            self.assertFalse(self.activity.usable)
        self.assertFalse(PracticeSession.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action='practice.recorded').exists())

    def test_cached_availability_cannot_authorise_a_new_run_or_tasks_after_revocation(self):
        with integrity_scope():
            self.warm_practice_and_revoke_elsewhere()
            with self.assertRaises(ValidationError):
                start_run(self.family, self.program)
            self.assertFalse(self.activity.usable)
        self.assertFalse(PracticeRun.objects.exists())
        self.assertFalse(PracticeRunTask.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action='practice_run.started').exists())

    def replace_cached_familiarity_bytes(self):
        self.assertTrue(self.activity.usable)
        proof_id = self.activity.item_metadata['a']['familiarity']['evidence']
        document = EvidenceDocument.objects.get(pk=proof_id)
        storage, name = document.file.storage, document.file.name
        # Simulate bytes changing in storage after a request checked this proof;
        # no evidence record or approval is edited to disguise the change.
        storage.delete(name)
        self.assertEqual(storage.save(name, ContentFile(b'Changed fictional evidence bytes')), name)
        self.assertTrue(self.activity.usable, 'The earlier request still has its cached file digest.')

    def test_program_rechecks_cached_evidence_bytes_after_acquiring_its_write_locks(self):
        count = Program.objects.count()
        with integrity_scope():
            self.replace_cached_familiarity_bytes()
            with self.assertRaises(ValidationError):
                create_program(self.pro, self.child, self.program_data())
            self.assertFalse(self.activity.usable)
        self.assertEqual(Program.objects.count(), count)

    def test_run_rechecks_cached_evidence_bytes_before_creating_any_tasks(self):
        with integrity_scope():
            self.replace_cached_familiarity_bytes()
            with self.assertRaises(ValidationError):
                start_run(self.family, self.program)
            self.assertFalse(self.activity.usable)
        self.assertFalse(PracticeRun.objects.exists())
        self.assertFalse(PracticeRunTask.objects.exists())

    def test_current_program_run_and_report_work_and_saved_replay_survives_revocation(self):
        with integrity_scope():
            program = create_program(self.pro, self.child, self.program_data())
            run = start_run(self.family, program)
            self.assertEqual(start_run(self.family, program).pk, run.pk)
            task = run.tasks.select_related('run', 'item__program__child', 'item__activity').get()
            ticket = task_ticket(task)
            payload = self.payload(task.target)
            report = record_practice(self.family, task.item, payload, ticket)
            self.assertEqual(record_practice(self.family, task.item, payload, ticket).pk, report.pk)
            self.warm_practice_and_revoke_elsewhere()
            self.assertEqual(record_practice(self.family, task.item, payload, ticket).pk, report.pk)
        self.assertEqual(PracticeRun.objects.count(), 1)
        self.assertEqual(PracticeRunTask.objects.count(), 1)
        self.assertEqual(PracticeSession.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action='practice.recorded').count(), 1)

    def test_cached_probe_availability_cannot_authorise_a_new_administration_after_revocation(self):
        probe, objective, decision = self.published_probe()
        with integrity_scope():
            digest = probe.fingerprint()
            self.assertTrue(availability_for('production_followup', self.variety, digest)['available'])
            with integrity_scope():
                revoke_decision(self.pro, decision.pk, 'Fictional concurrent protocol revocation')
                self.assertFalse(availability_for('production_followup', self.variety, digest)['available'])
            self.assertTrue(availability_for('production_followup', self.variety, digest)['available'])
            with self.assertRaises(ValidationError):
                start_administration(self.pro, objective, probe, self.probe_conditions(), self.probe_familiarity())
            self.assertFalse(availability_for('production_followup', self.variety, digest)['available'])
        self.assertFalse(ProbeAdministration.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action='followup.observation_started').exists())

    def test_current_probe_administration_and_saved_replay_are_not_broken(self):
        probe, objective, decision = self.published_probe()
        key = uuid.uuid4()
        with integrity_scope():
            administration = start_administration(self.pro, objective, probe,
                self.probe_conditions(), self.probe_familiarity(), key)
            with integrity_scope():
                revoke_decision(self.pro, decision.pk, 'Fictional protocol revocation after saved observation')
            replay = start_administration(self.pro, objective, probe,
                self.probe_conditions(), self.probe_familiarity(), key)
            self.assertEqual(replay.pk, administration.pk)
        self.assertEqual(ProbeAdministration.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action='followup.observation_started').count(), 1)


@override_settings(**TEST_SETTINGS)
class LiveIntegrityPostgreSQLTests(LiveIntegrityFixture, TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_revocation_waits_for_exact_activity_row_lock_before_recording_a_decision(self):
        self.install()
        started = threading.Event()
        finished = threading.Event()
        worker_pid = []

        def revoke_in_other_connection():
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                    cursor.execute("SET statement_timeout = '12s'")
                    cursor.execute('SELECT pg_backend_pid()')
                    worker_pid.append(cursor.fetchone()[0])
                actor = User.objects.get(pk=self.pro.pk)
                started.set()
                result = revoke_decision(actor, self.decision.pk, 'Fictional row-lock revocation')
                finished.set()
                return result.pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Activity.objects.select_for_update().get(pk=self.activity.pk)
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    holder_pid = cursor.fetchone()[0]
                future = pool.submit(revoke_in_other_connection)
                self.assertTrue(started.wait(3), 'Revocation worker did not start.')
                deadline = time.monotonic() + 4
                blocked = False
                while time.monotonic() < deadline and not future.done():
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT %s = ANY(pg_blocking_pids(%s))', [holder_pid, worker_pid[0]])
                        blocked = cursor.fetchone()[0]
                    if blocked:
                        break
                    finished.wait(0.01)
                self.assertTrue(blocked, 'PostgreSQL must report revocation waiting for the exact Activity lock.')
                self.assertFalse(finished.is_set())
                self.assertEqual(AvailabilityDecision.objects.filter(status='revoked').count(), 0)
            revoked_id = future.result(timeout=10)
        self.assertTrue(finished.is_set())
        self.assertEqual(AvailabilityDecision.objects.get(pk=revoked_id).status, 'revoked')
        self.assertEqual(AuditEvent.objects.filter(action='qualification.availability_revoked').count(), 1)
