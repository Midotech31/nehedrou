import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.db import connection, connections
from django.test import Client, TransactionTestCase, override_settings
from catalog.models import DraftWorkingCopy, EditorialGrant, Variety
from core.models import User


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL row locks.')
@override_settings(DEMO_MODE=True,MFA_REQUIRED=False)
class WorkingCopyConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.author=User.objects.create_user(username='concurrent-author',email='concurrent@example.test')
        variety=Variety.objects.create(code='ar-dz-pilot',language='ar',label='Darja')
        EditorialGrant.objects.create(user=self.author,variety=variety,edit=True)
        client=Client();client.force_login(self.author)
        self.cookies=client.cookies

    def parallel(self,identifier,revision):
        barrier=Barrier(2)
        def save(index):
            connections.close_all()
            try:
                client=Client();client.cookies=self.cookies
                barrier.wait(timeout=5)
                return client.post(f'/fr/editorial/work/{identifier}/',json.dumps({'fields':{'title':'Concurrent change '+str(index)},'revision':revision}),content_type='application/json').status_code
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return sorted(pool.map(save,[0,1]))

    def test_simultaneous_first_save_creates_one_copy(self):
        identifier=uuid.uuid4()
        self.assertEqual(self.parallel(identifier,0),[200,409])
        self.assertEqual(DraftWorkingCopy.objects.filter(pk=identifier).count(),1)
        self.assertEqual(DraftWorkingCopy.objects.get(pk=identifier).revision,1)

    def test_simultaneous_update_preserves_revision_and_rejects_stale_session(self):
        copy=DraftWorkingCopy.objects.create(owner=self.author,data={'title':'Initial'},revision=1)
        self.assertEqual(self.parallel(copy.pk,1),[200,409])
        copy.refresh_from_db()
        self.assertEqual(copy.revision,2)
        self.assertIn(copy.data['title'],['Concurrent change 0','Concurrent change 1'])
