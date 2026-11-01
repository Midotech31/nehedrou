"""Editorial onboarding isolates review roles from practice records."""
import hashlib
from django.contrib.auth.models import Permission
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from catalog.models import EditorialAccessInvitation, EditorialGrant, Variety
from core.models import AuditEvent, Membership, User

@override_settings(DEMO_MODE=False, DEBUG=False, MFA_REQUIRED=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    PUBLIC_ORIGIN='https://editorial.example', DEFAULT_FROM_EMAIL='team@editorial.example',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class EditorialAccessInvitationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('platform-editor-manager', 'manager@example.test', 'Sufficiently-Long-Password-123')
        cls.manager.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        cls.ordinary = User.objects.create_user('ordinary-review-fixture', 'ordinary@example.test', 'Sufficiently-Long-Password-123')
        cls.variety = Variety.objects.create(code='ar-dz-review-fixture', language='ar', label='Fictional regional Arabic')

    def issue(self, *, email='reviewer@example.test', capability='clinical_review'):
        self.client.force_login(self.manager)
        response = self.client.post('/fr/operations/editorial-access/', {
            'email': email, 'variety': str(self.variety.pk), 'capability': capability,
        })
        self.assertRedirects(response, '/fr/operations/editorial-access/')
        invitation = EditorialAccessInvitation.objects.filter(email=email).latest('expires_at')
        self.assertEqual(invitation.delivery, 'sent')
        body = mail.outbox[-1].body
        token = body.split('/editorial/invite/', 1)[1].strip().rstrip('/')
        self.assertEqual(invitation.token_hash, hashlib.sha256(token.encode()).hexdigest(), )
        self.assertNotIn(token, response.content.decode())
        return invitation, token

    def test_management_page_renders_only_for_the_platform_manager(self):
        self.client.force_login(self.manager)
        response = self.client.get('/fr/operations/editorial-access/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Gérer les accès éditoriaux')
        self.assertContains(response, 'ne donne pas accès aux dossiers d’enfants')
        self.assertEqual(response.content.decode().count('aria-current="page"'), 1)
        english = self.client.get('/en/operations/editorial-access/')
        arabic = self.client.get('/ar/operations/editorial-access/')
        self.assertContains(english, 'Manage editorial access')
        self.assertEqual(english.content.decode().count('aria-current="page"'), 1)
        self.assertContains(english, 'No active editorial permissions.')
        self.assertContains(arabic, 'إدارة صلاحيات التحرير')
        self.assertEqual(arabic.content.decode().count('aria-current="page"'), 1)
        self.assertContains(arabic, 'لا توجد صلاحيات تحريرية نشطة.')
        self.assertIn('dir="rtl"', arabic.content.decode())
        self.client.force_login(self.ordinary)
        self.assertEqual(self.client.get('/fr/operations/editorial-access/').status_code, 403)

    def test_manager_cannot_assign_publish_or_broader_platform_permissions(self):
        self.client.force_login(self.manager)
        response = self.client.post('/fr/operations/editorial-access/', {
            'email': 'publisher@example.test', 'variety': str(self.variety.pk), 'capability': 'publish',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(EditorialAccessInvitation.objects.exists())
        self.assertFalse(User.objects.filter(email='publisher@example.test').exists())

    def test_invitation_cannot_be_added_to_existing_publisher_for_same_variety(self):
        publisher = User.objects.create_user('already-publisher', 'already-publisher@example.test', 'Sufficiently-Long-Password-123')
        EditorialGrant.objects.create(user=publisher, variety=self.variety, publish=True)
        self.client.force_login(self.manager)
        response = self.client.post('/fr/operations/editorial-access/', {
            'email': publisher.email, 'variety': str(self.variety.pk), 'capability': 'clinical_review',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(EditorialAccessInvitation.objects.exists())
        self.assertFalse(EditorialGrant.objects.filter(user=publisher, variety=self.variety, clinical_review=True).exists())

    def test_acceptance_refuses_if_publishing_permission_was_added_after_invitation(self):
        invited = User.objects.create_user('became-publisher', 'became-publisher@example.test', 'Sufficiently-Long-Password-123')
        invitation, token = self.issue(email=invited.email)
        EditorialGrant.objects.create(user=invited, variety=self.variety, publish=True)
        self.client.force_login(invited)
        response = self.client.post(reverse('accept_editorial_invite', args=[token]))
        self.assertEqual(response.status_code, 200)
        grant = EditorialGrant.objects.get(user=invited, variety=self.variety)
        self.assertFalse(grant.clinical_review)
        self.assertIsNone(invitation.used_at)

    def test_reviewer_signup_is_token_bound_role_limited_and_has_no_practice_access(self):
        invitation, token = self.issue()
        self.assertFalse(User.objects.filter(email__iexact=invitation.email).exists())
        self.assertFalse(EditorialGrant.objects.exists())
        self.client.logout()
        url = reverse('accept_editorial_invite', args=[token])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(url, {
            'username': 'regional-reviewer', 'instruction_language': 'ar',
            'password1': 'Private-Account-Password-583!x',
            'password2': 'Private-Account-Password-583!x',
        })
        self.assertEqual(response.status_code, 302, response.content.decode()[:1800])
        self.assertEqual(response['Location'], '/fr/editorial/')
        user = User.objects.get(email='reviewer@example.test')
        grant = EditorialGrant.objects.get(user=user, variety=self.variety)
        self.assertTrue(grant.clinical_review)
        self.assertFalse(grant.edit or grant.linguistic_review or grant.publish)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff or user.is_superuser or user.has_perm('core.manage_entitlements'))
        self.assertFalse(Membership.objects.filter(user=user).exists())
        invitation.refresh_from_db()
        self.assertEqual(invitation.accepted_by, user)
        self.assertIsNotNone(invitation.used_at)
        self.assertTrue(AuditEvent.objects.filter(actor=user, action='catalog.editorial_invitation_accepted').exists())
        self.assertEqual(self.client.get(url).status_code, 410)

    def test_existing_account_must_sign_in_with_invited_email_and_token_is_single_use(self):
        invited = User.objects.create_user('known-reviewer', 'known@example.test', 'Sufficiently-Long-Password-123')
        invitation, token = self.issue(email=invited.email, capability='linguistic_review')
        wrong = User.objects.create_user('wrong-reviewer', 'wrong@example.test', 'Sufficiently-Long-Password-123')
        self.client.force_login(wrong)
        url = reverse('accept_editorial_invite', args=[token])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(EditorialGrant.objects.exists())
        self.assertIsNone(invitation.used_at)
        self.client.force_login(invited)
        response = self.client.post(url)
        self.assertRedirects(response, '/fr/editorial/')
        self.assertTrue(EditorialGrant.objects.get(user=invited, variety=self.variety).linguistic_review)
        self.assertEqual(EditorialAccessInvitation.objects.filter(accepted_by=invited).count(), 1)

    def test_manager_permission_required_for_issue_and_revocation_removes_last_grant(self):
        self.client.force_login(self.ordinary)
        response = self.client.post('/fr/operations/editorial-access/', {
            'email': 'blocked@example.test', 'variety': str(self.variety.pk), 'capability': 'edit',
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(EditorialAccessInvitation.objects.exists())
        self.client.force_login(self.manager)
        editor = User.objects.create_user('revocable-editor', 'revocable@example.test')
        grant = EditorialGrant.objects.create(user=editor, variety=self.variety, edit=True)
        response = self.client.post(reverse('editorial_capability_revoke', args=[grant.pk, 'edit']))
        self.assertRedirects(response, '/fr/operations/editorial-access/')
        self.assertFalse(EditorialGrant.objects.filter(pk=grant.pk).exists())
        self.assertTrue(AuditEvent.objects.filter(actor=self.manager, action='catalog.editorial_access_revoked').exists())

    def test_expired_invitation_link_returns_gone_without_creating_account(self):
        from django.utils import timezone
        from datetime import timedelta
        invitation, token = self.issue(email='expired@example.test', capability='edit')
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save(update_fields=['expires_at'])
        self.client.logout()
        response = self.client.get(reverse('accept_editorial_invite', args=[token]))
        self.assertEqual(response.status_code, 410)
        self.assertFalse(User.objects.filter(email='expired@example.test').exists())

    def test_reissuing_link_revokes_every_older_pending_token(self):
        previous, old_token = self.issue(email='replace@example.test', capability='linguistic_review')
        replacement, new_token = self.issue(email='replace@example.test', capability='linguistic_review')
        previous.refresh_from_db()
        self.assertTrue(previous.revoked)
        self.assertNotEqual(old_token, new_token)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('accept_editorial_invite', args=[old_token])).status_code, 410)
        self.assertEqual(self.client.get(reverse('accept_editorial_invite', args=[new_token])).status_code, 200)
        self.assertTrue(replacement.available)

    @override_settings(EMAIL_BACKEND='core.email_backends.DisabledEmailBackend')
    def test_unavailable_email_records_failure_but_never_creates_access(self):
        self.client.force_login(self.manager)
        response = self.client.post('/fr/operations/editorial-access/', {
            'email': 'no-mail@example.test', 'variety': str(self.variety.pk), 'capability': 'clinical_review',
        })
        self.assertRedirects(response, '/fr/operations/editorial-access/')
        invitation = EditorialAccessInvitation.objects.get(email='no-mail@example.test')
        self.assertEqual(invitation.delivery, 'failed')
        self.assertIsNone(invitation.accepted_by)
        self.assertFalse(User.objects.filter(email='no-mail@example.test').exists())
        self.assertFalse(EditorialGrant.objects.exists())

    def test_revoked_invitation_link_stops_working(self):
        invitation, token = self.issue(email='withdrawn@example.test', capability='edit')
        self.client.force_login(self.manager)
        response = self.client.post(reverse('editorial_invitation_revoke', args=[invitation.pk]))
        self.assertRedirects(response, '/fr/operations/editorial-access/')
        self.assertEqual(self.client.get(reverse('accept_editorial_invite', args=[token])).status_code, 410)
        self.assertFalse(User.objects.filter(email='withdrawn@example.test').exists())
