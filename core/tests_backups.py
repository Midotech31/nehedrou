import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from unittest.mock import patch
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from core.backups import create_backup, inspect_backup, restore_backup, cipher


class EncryptedOperatorBackupTests(SimpleTestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.media=self.root/'source-media';self.media.mkdir()
        (self.media/'editorial').mkdir();(self.media/'editorial/model.wav').write_bytes(b'Fictional private fixture')
        self.database=self.root/'source.sqlite3'
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('CREATE TABLE fictional(value TEXT)')
            connection.execute('INSERT INTO fictional VALUES (?)',('Fictional saved activity',))
        self.key=Fernet.generate_key()
        self.environment=patch.dict(os.environ,{'NEHEDROU_BACKUP_KEY':self.key.decode()})
        self.environment.start();self.addCleanup(self.environment.stop)
        self.settings=override_settings(MEDIA_ROOT=self.media,DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':self.database}})
        self.settings.enable();self.addCleanup(self.settings.disable)
        self.archive=self.root/'backup.nehedrou'

    def test_encrypted_round_trip_restores_database_and_exact_private_media(self):
        created=create_backup(self.archive)
        self.assertTrue(created['encrypted'])
        self.assertNotIn(b'Fictional saved activity',self.archive.read_bytes())
        restored=restore_backup(self.archive,self.root/'new-media',self.root/'restored.sqlite3')
        self.assertTrue(restored['target_was_fresh'])
        with closing(sqlite3.connect(self.root/'restored.sqlite3')) as connection:
            self.assertEqual(connection.execute('SELECT value FROM fictional').fetchone()[0],'Fictional saved activity')
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertEqual((self.root/'new-media/editorial/model.wav').read_bytes(),(self.media/'editorial/model.wav').read_bytes())

    def test_tampering_wrong_key_and_missing_key_are_rejected_before_restore(self):
        create_backup(self.archive)
        with patch.dict(os.environ,{'NEHEDROU_BACKUP_KEY':Fernet.generate_key().decode()}):
            with self.assertRaises(CommandError):inspect_backup(self.archive)
        data=bytearray(self.archive.read_bytes());data[len(data)//2]^=1;self.archive.write_bytes(data)
        with self.assertRaises(CommandError):restore_backup(self.archive,self.root/'new-media',self.root/'restored.sqlite3')
        self.assertFalse((self.root/'restored.sqlite3').exists())
        self.assertFalse((self.root/'new-media').exists())
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(CommandError):create_backup(self.root/'missing-key.nehedrou')

    def test_existing_backup_database_and_media_cannot_be_overwritten(self):
        create_backup(self.archive)
        original=self.archive.read_bytes()
        with self.assertRaises(CommandError):create_backup(self.archive)
        self.assertEqual(self.archive.read_bytes(),original)
        with self.assertRaises(CommandError):restore_backup(self.archive,self.root/'new-media',self.database)
        with self.assertRaises(CommandError):restore_backup(self.archive,self.media,self.root/'new.sqlite3')
        self.assertFalse((self.root/'new.sqlite3').exists())

    def malicious(self,entry,data=b'bad'):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            archive.writestr(entry,data)
            archive.writestr('database.bin',b'not-a-database')
            archive.writestr('manifest.json',json.dumps({'schema':'nehedrou-encrypted-backup-v1','database_engine':'sqlite','files':{entry:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()},'database.bin':{'bytes':14,'sha256':hashlib.sha256(b'not-a-database').hexdigest()}}}))
        self.archive.write_bytes(cipher().encrypt(buffer.getvalue()))

    def test_authenticated_path_traversal_and_absolute_paths_are_rejected(self):
        for entry in ['media/../../escaped','/media/absolute','media/C:/drive','media\\windows','media//double','media/']:
            self.malicious(entry)
            with self.assertRaises(CommandError):inspect_backup(self.archive)
        self.assertFalse((self.root/'escaped').exists())

    def test_manifest_mismatch_and_invalid_sqlite_are_rejected(self):
        self.malicious('media/normal')
        with self.assertRaises(CommandError):restore_backup(self.archive,self.root/'new-media',self.root/'restored.sqlite3')
        self.assertFalse((self.root/'restored.sqlite3').exists())
        create_backup(self.root/'valid.nehedrou')
        manifest,entries=inspect_backup(self.root/'valid.nehedrou')
        manifest['files']['database.bin']['sha256']='0'*64
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            for name,data in entries.items():archive.writestr(name,data)
            archive.writestr('manifest.json',json.dumps(manifest))
        self.archive.write_bytes(cipher().encrypt(buffer.getvalue()))
        with self.assertRaises(CommandError):inspect_backup(self.archive)

    def test_limits_and_private_destinations_are_enforced(self):
        from django.conf import settings
        with self.assertRaises(CommandError):create_backup(Path(settings.BASE_DIR)/'unsafe-backup.nehedrou')
        with self.assertRaises(CommandError):create_backup(self.media/'unsafe-backup.nehedrou')
        with patch('core.backups.LIMIT',8):
            with self.assertRaises(CommandError):create_backup(self.archive)
        self.assertFalse(self.archive.exists())

    def test_management_command_requires_quiescent_confirmation_and_verifies_without_writes(self):
        with self.assertRaises(CommandError):call_command('backup_nehedrou',destination=str(self.archive),stdout=io.StringIO())
        output=io.StringIO()
        call_command('backup_nehedrou',destination=str(self.archive),quiescent=True,stdout=output)
        self.assertTrue(json.loads(output.getvalue())['encrypted'])
        output=io.StringIO()
        call_command('restore_nehedrou',source=str(self.archive),verify_only=True,stdout=output)
        self.assertTrue(json.loads(output.getvalue())['verified'])
        self.assertFalse((self.root/'restored.sqlite3').exists())

    def test_remote_storage_files_are_included_and_restore_exactly(self):
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage
        with override_settings(MEDIA_STORAGE_BACKEND='s3', STORAGES={'default':{'BACKEND':'django.core.files.storage.InMemoryStorage'}}):
            default_storage.save('editorial/model.wav',ContentFile(b'Exact remote fixture'))
            default_storage.save('private_evidence/review.txt',ContentFile(b'Private fictional evidence'))
            create_backup(self.archive)
        restore_backup(self.archive,self.root/'restored-media',self.root/'restored.sqlite3')
        self.assertEqual((self.root/'restored-media/editorial/model.wav').read_bytes(),b'Exact remote fixture')
        self.assertEqual((self.root/'restored-media/private_evidence/review.txt').read_bytes(),b'Private fictional evidence')

    def test_remote_errors_and_unsafe_keys_do_not_create_an_incomplete_archive(self):
        with override_settings(MEDIA_STORAGE_BACKEND='s3'):
            with patch('django.core.files.storage.default_storage.listdir',return_value=([],['../escape'])):
                with self.assertRaises(CommandError):create_backup(self.archive)
            with patch('django.core.files.storage.default_storage.listdir',side_effect=OSError('Fictional unavailable backend')):
                with self.assertRaises(OSError):create_backup(self.archive)
        self.assertFalse(self.archive.exists())
