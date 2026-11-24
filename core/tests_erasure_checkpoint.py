"""Fictional SQLite archives/references only; no inherited database or network."""
from contextlib import closing, contextmanager
from datetime import timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from core.backups import create_backup, restore_backup
from core.erasure_checkpoint import capture, check, cipher, selected_database, MAX_CIPHERTEXT


class ErasureCheckpointTests(SimpleTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='erasure-checkpoint-fictional-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source.sqlite3'
        self.target = self.root / 'restored.sqlite3'
        self.media = self.root / 'active-media'
        self.media.mkdir()
        self.archive = self.root / 'old.encrypted'
        self.checkpoint = self.root / 'references.encrypted'
        self.org, self.other_org = uuid.uuid4(), uuid.uuid4()
        self.child, self.other_child = uuid.uuid4(), uuid.uuid4()
        with closing(sqlite3.connect(self.source)) as db, db:
            db.executescript('CREATE TABLE django_migrations (app TEXT);'
                "INSERT INTO django_migrations VALUES ('core'),('care');"
                'CREATE TABLE core_auditevent (organization_id TEXT,object_id TEXT,action TEXT,actor_ref TEXT);'
                'CREATE TABLE care_child (id TEXT PRIMARY KEY,organization_id TEXT,code TEXT);')
            db.executemany('INSERT INTO care_child VALUES (?,?,?)', [
                (self.child.hex, self.org.hex, 'Fictional erased child'),
                (self.other_child.hex, self.other_org.hex, 'Fictional unrelated child')])
        self.environment = patch.dict(os.environ, {'NEHEDROU_BACKUP_KEY': Fernet.generate_key().decode('ascii')})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.cutoff = (timezone.now() - timedelta(minutes=1)).isoformat()
        with self.selected(self.source):
            create_backup(self.archive)
            restore_backup(self.archive, self.root / 'restored-media', sqlite_destination=self.target)
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute('INSERT INTO core_auditevent VALUES (?,?,?,?)',
                (self.org.hex, str(self.child), 'child.erased', 'FICTITIOUS_ACTOR_NOT_EXPORTED'))
            db.execute('DELETE FROM care_child WHERE id=?', (self.child.hex,))

    @contextmanager
    def selected(self, path):
        with override_settings(MEDIA_ROOT=self.media, DATABASES={'default':
                {'ENGINE': 'django.db.backends.sqlite3', 'NAME': path}}):
            yield

    def captured(self):
        with self.selected(self.source):
            return capture(self.archive, self.checkpoint, self.cutoff, str(self.source))

    def checked(self, capture_report=None, **overrides):
        report = capture_report or self.captured()
        values = dict(archive=self.archive, checkpoint=self.checkpoint,
            expected_sha256=report['checkpoint_sha256'], cutoff=self.cutoff,
            expected_database=str(self.target))
        values.update(overrides)
        with self.selected(self.target):
            return check(**values)

    def payload(self):
        return json.loads(cipher().decrypt(self.checkpoint.read_bytes()))

    def forged(self, payload):
        self.checkpoint.write_bytes(cipher().encrypt(json.dumps(payload).encode('utf-8')))
        return hashlib.sha256(self.checkpoint.read_bytes()).hexdigest()

    def test_old_archive_resurrection_blocks_without_changing_restored_database(self):
        original = self.target.read_bytes()
        report = self.checked()
        self.assertEqual(report['status'], 'recorded_erased_pairs_present')
        self.assertEqual((report['matching_restored_pairs'], report['ambiguous_scope_pairs']), (1, 0))
        self.assertTrue(report['blocking'])
        self.assertFalse(report['return_to_service_authorized'])
        self.assertFalse(report['history_completeness_verified'])
        self.assertEqual(self.target.read_bytes(), original)

    def test_capture_is_encrypted_minimal_and_exclusive_and_deduplicates_uuid_spellings(self):
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute('INSERT INTO core_auditevent VALUES (?,?,?,?)',
                (self.org.hex, str(self.child).upper(), 'child.erased', 'NOT_EXPORTED'))
            db.execute('INSERT INTO core_auditevent VALUES (?,?,?,?)',
                (None, 'bad-private-value', 'child.updated', 'NOT_EXPORTED'))
        report = self.captured()
        self.assertEqual(report['reference_pairs'], 1)
        token = self.checkpoint.read_bytes()
        self.assertNotIn(str(self.child).encode(), token)
        payload = self.payload()
        self.assertEqual(set(payload), {'schema', 'archive_sha256', 'capture_database_sha256',
            'captured_at', 'operator_cutoff', 'pairs'})
        self.assertEqual(payload['pairs'], [[str(self.org), str(self.child)]])
        self.assertNotIn('FICTITIOUS_ACTOR_NOT_EXPORTED', json.dumps(payload))
        self.assertNotIn(str(self.source), json.dumps(payload))
        with self.selected(self.source), self.assertRaisesMessage(CommandError, 'NEW_PRIVATE_PATH_REQUIRED'):
            capture(self.archive, self.checkpoint, self.cutoff, str(self.source))
        self.assertEqual(self.checkpoint.read_bytes(), token)

    def test_different_cabinet_and_conflicting_pairs_are_not_treated_as_clear(self):
        report = self.captured()
        payload = self.payload()
        payload['pairs'].append([str(self.other_org), str(self.child)])
        report['checkpoint_sha256'] = self.forged(payload)
        result = self.checked(report)
        self.assertEqual(result['status'], 'ambiguous_scope_in_checkpoint')
        self.assertEqual((result['matching_restored_pairs'], result['ambiguous_scope_pairs']), (1, 1))
        self.assertTrue(result['blocking'])

    def test_wrong_cabinet_only_is_ambiguous(self):
        report = self.captured()
        with closing(sqlite3.connect(self.target)) as db, db:
            db.execute('UPDATE care_child SET organization_id=? WHERE id=?', (self.other_org.hex, self.child.hex))
        result = self.checked(report)
        self.assertEqual((result['matching_restored_pairs'], result['ambiguous_scope_pairs']), (0, 1))
        self.assertTrue(result['blocking'])

    def test_absent_known_reference_is_limited_comparison_and_remains_read_only(self):
        report = self.captured()
        with closing(sqlite3.connect(self.target)) as db, db:
            db.execute('DELETE FROM care_child WHERE id=?', (self.child.hex,))
        original = self.target.read_bytes()
        result = self.checked(report)
        self.assertEqual(result['status'], 'no_matches_in_checkpoint')
        self.assertFalse(result['blocking'])
        self.assertFalse(result['selected_database_lineage_verified'])
        self.assertFalse(result['return_to_service_authorized'])
        self.assertEqual(self.target.read_bytes(), original)

    def test_capture_database_identity_is_refused_even_after_normal_erasure(self):
        report = self.captured()
        with self.selected(self.source), self.assertRaisesMessage(CommandError, 'CAPTURE_DATABASE_REFUSED'):
            check(self.archive, self.checkpoint, report['checkpoint_sha256'], self.cutoff, str(self.source))

    def test_wrong_expected_database_missing_file_empty_and_uninitialized_targets_fail(self):
        report = self.captured()
        with self.assertRaisesMessage(CommandError, 'DATABASE_IDENTITY_MISMATCH'):
            self.checked(report, expected_database=str(self.source))
        missing = self.root / 'never-created.sqlite3'
        with self.selected(missing), self.assertRaisesMessage(CommandError, 'DATABASE_IDENTITY_MISMATCH'):
            check(self.archive, self.checkpoint, report['checkpoint_sha256'], self.cutoff, str(missing))
        self.assertFalse(missing.exists())
        with closing(sqlite3.connect(self.target)) as db, db:
            db.execute('DELETE FROM care_child')
        with self.assertRaisesMessage(CommandError, 'NONEMPTY_REFERENCES_EMPTY_TARGET'):
            self.checked(report)
        blank = self.root / 'blank.sqlite3'
        with closing(sqlite3.connect(blank)):
            pass
        with self.selected(blank), self.assertRaisesMessage(CommandError, 'DATABASE_READ_FAILED'):
            check(self.archive, self.checkpoint, report['checkpoint_sha256'], self.cutoff, str(blank))

    def test_null_or_malformed_selected_audit_row_fails_without_identifier_output(self):
        for organization, subject in ((None, str(self.child)), (self.org.hex, 'PRIVATE_INVALID_REFERENCE')):
            with self.subTest(organization_is_null=organization is None):
                with closing(sqlite3.connect(self.source)) as db, db:
                    db.execute('DELETE FROM core_auditevent')
                    db.execute('INSERT INTO core_auditevent VALUES (?,?,?,?)',
                        (organization, subject, 'child.erased', 'NOT_EXPORTED'))
                with self.selected(self.source), self.assertRaises(CommandError) as error:
                    capture(self.archive, self.checkpoint, self.cutoff, str(self.source))
                self.assertNotIn(subject, str(error.exception))
                self.assertFalse(self.checkpoint.exists())

    def test_wrong_archive_expected_digest_tampering_and_missing_checkpoint_fail(self):
        report = self.captured()
        with self.assertRaisesMessage(CommandError, 'SHA256_MISMATCH'):
            self.checked(report, expected_sha256='0' * 64)
        token = self.checkpoint.read_bytes()
        self.checkpoint.write_bytes(token[:-1] + bytes([token[-1] ^ 1]))
        with self.assertRaisesMessage(CommandError, 'INVALID_ENCRYPTED_INPUT'):
            self.checked(report, expected_sha256=hashlib.sha256(self.checkpoint.read_bytes()).hexdigest())
        self.checkpoint.write_bytes(token)
        other = self.root / 'other.encrypted'
        with self.selected(self.source):
            create_backup(other)
        with self.assertRaisesMessage(CommandError, 'ARCHIVE_MISMATCH'):
            self.checked(report, archive=other)
        with self.assertRaisesMessage(CommandError, 'INVALID_ENCRYPTED_INPUT'):
            self.checked(report, checkpoint=self.root / 'missing.encrypted')

    def test_invalid_authenticated_payload_time_and_bounds_fail_closed(self):
        report = self.captured()
        baseline = self.payload()
        invalid = [
            {**baseline, 'actor': 'NOT_ALLOWED'},
            {**baseline, 'pairs': [[str(self.org), 'PRIVATE_INVALID_UUID']]},
            {**baseline, 'pairs': [[None, str(self.child)]]},
            {**baseline, 'operator_cutoff': (timezone.now() + timedelta(days=1)).isoformat()},
            {**baseline, 'captured_at': '2026-01-01T00:00:00'},
        ]
        for payload in invalid:
            with self.subTest(keys=tuple(payload)):
                report['checkpoint_sha256'] = self.forged(payload)
                with self.assertRaises(CommandError):
                    self.checked(report)
        self.checkpoint.write_bytes(b'x' * (MAX_CIPHERTEXT + 1))
        with self.assertRaisesMessage(CommandError, 'CIPHERTEXT_LIMIT'):
            self.checked(report)

    def test_cutoff_future_and_stale_declared_history_fail(self):
        future = (timezone.now() + timedelta(days=1)).isoformat()
        with self.selected(self.source), self.assertRaisesMessage(CommandError, 'CUTOFF_AFTER_CAPTURE'):
            capture(self.archive, self.checkpoint, future, str(self.source))
        report = self.captured()
        with self.assertRaisesMessage(CommandError, 'INVALID_TIME_RANGE'):
            self.checked(report, cutoff=future)
        with self.assertRaisesMessage(CommandError, 'STALE_HISTORY'):
            self.checked(report, cutoff=(timezone.now() - timedelta(seconds=1)).isoformat())

    def test_pair_count_bound_and_empty_checkpoint_require_valid_migrated_selection(self):
        with patch('core.erasure_checkpoint.MAX_PAIRS', 0), self.selected(self.source), \
                self.assertRaisesMessage(CommandError, 'REFERENCE_LIMIT'):
            capture(self.archive, self.checkpoint, self.cutoff, str(self.source))
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute('DELETE FROM core_auditevent')
        report = self.captured()
        self.assertEqual(report['reference_pairs'], 0)
        result = self.checked(report)
        self.assertEqual(result['status'], 'no_matches_in_checkpoint')
        self.assertFalse(result['history_completeness_verified'])

    def test_command_emits_only_counts_and_digests_and_blocks_with_nonzero_error(self):
        report = self.captured()
        output = io.StringIO()
        with self.selected(self.target), self.assertRaisesMessage(CommandError, 'RECONCILIATION_BLOCKED'):
            call_command('audit_restored_erasures', archive=str(self.archive), check=str(self.checkpoint),
                checkpoint_sha256=report['checkpoint_sha256'], cutoff=self.cutoff,
                expected_database=str(self.target), stdout=output)
        parsed = json.loads(output.getvalue())
        self.assertTrue(parsed['blocking'])
        for value in (str(self.child), str(self.org), str(self.source), str(self.target), 'FICTITIOUS_ACTOR_NOT_EXPORTED'):
            self.assertNotIn(value, output.getvalue())
        with self.selected(self.target), self.assertRaisesMessage(CommandError, 'EXPECTED_DIGEST_REQUIRED'):
            call_command('audit_restored_erasures', archive=str(self.archive), check=str(self.checkpoint),
                cutoff=self.cutoff, expected_database=str(self.target), stdout=io.StringIO())

    def test_independent_sqlite_reader_actually_rejects_mutation(self):
        original = self.target.read_bytes()
        with self.selected(self.target), selected_database(str(self.target)) as reader:
            with self.assertRaises(sqlite3.OperationalError):
                reader.conn.execute('DELETE FROM care_child')
        self.assertEqual(self.target.read_bytes(), original)

    def test_command_cannot_capture_and_check_together(self):
        with self.selected(self.source), self.assertRaises(CommandError):
            call_command('audit_restored_erasures', archive=str(self.archive),
                capture=str(self.checkpoint), check=str(self.checkpoint), cutoff=self.cutoff,
                expected_database=str(self.source), stdout=io.StringIO())
        self.assertFalse(self.checkpoint.exists())
