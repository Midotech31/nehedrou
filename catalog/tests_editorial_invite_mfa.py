"""Return to the exact editorial invitation after authenticator verification."""
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from catalog.editorial_access import issue_manual_editorial_access_invitation, revoke_editorial_invitation
from catalog.models import EditorialGrant, Variety
from core.access import CURRENT_NOTICE_VERSION, PENDING_NOTICE_INVITATION_DIGEST
from core.invitation_mfa import SESSION_KEY
from core.models import Entitlement, Membership, NoticeAcknowledgement, Organization, User
from core.services import issue_manual_practice_invitation


PASSWORD = 'V9!zq3#X8v2b$P6s'


def otp(device):
    return str(TOTP(device.bin_key, device.step, device.t0, device.digits).token()).zfill(device.digits)


@override_settings(DEMO_MODE=False, MFA_REQUIRED=True, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='core.email_backends.DisabledEmailBackend',
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class EditorialInvitationMFAContinuationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = User.objects.create_user('fictional-editorial-mfa-manager', 'mfa-manager@example.test')
        cls.operator.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        cls.darja = Variety.objects.create(code='ar-dz-pilot', language='ar', label='Fictional Darja')
        cls.other_variety = Variety.objects.create(code='en-us-general-pilot', language='en', label='Fictional English')
        cls.practice = Organization.objects.create(name='Fictional separate practice')
        Membership.objects.create(user=cls.operator, organization=cls.practice, role='owner')
        NoticeAcknowledgement.objects.create(user=cls.operator, organization=cls.practice,
                                              version=CURRENT_NOTICE_VERSION, language='en')
        Entitlement.objects.create(organization=cls.practice, expires_at=timezone.now()+timedelta(days=7),
                                   practitioner_quota=8)

    def recipient(self, suffix, confirmed=True):
        user = User.objects.create_user('editorial-mfa-' + suffix, suffix + '@example.test', password=PASSWORD)
        device = TOTPDevice.objects.create(user=user, name='fixture', confirmed=True) if confirmed else None
        return user, device

    def editorial_invite(self, email, language):
        invite, raw = issue_manual_editorial_access_invitation(
            self.operator, email, self.darja, 'linguistic_review', uuid4(),
        )
        return invite, raw, f'/{language}/editorial/invite/{raw}/'

    def login_through(self, client, user, link, language):
        login = f'/{language}/login/?next={link}'
        self.assertContains(client.get(link), 'href="' + login + '"')
        response = client.post(login, {'username': user.username, 'password': PASSWORD, 'next': link})
        self.assertRedirects(response, link, fetch_redirect_response=False)
        return client.get(link)

    def challenge(self, response, language, kind='verify'):
        self.assertEqual(response.status_code, 302)
        location = urlsplit(response['Location'])
        self.assertEqual(location.path, f'/{language}/security/{kind}/')
        params = parse_qs(location.query)
        self.assertEqual(set(params), {'invitation'})
        marker = params['invitation'][0]
        self.assertRegex(marker, r'^[0-9a-f]{64}$')
        return marker

    def assert_unused(self, invitation, user):
        invitation.refresh_from_db()
        self.assertIsNone(invitation.used_at)
        self.assertFalse(EditorialGrant.objects.filter(user=user, variety=self.darja).exists())
        self.assertFalse(Membership.objects.filter(user=user).exists())

    def assert_exact_grant(self, user):
        grant = EditorialGrant.objects.get(user=user, variety=self.darja)
        self.assertTrue(grant.linguistic_review)
        self.assertFalse(grant.clinical_review or grant.edit or grant.publish)
        self.assertFalse(Membership.objects.filter(user=user).exists())
        self.assertFalse(NoticeAcknowledgement.objects.filter(user=user).exists())

    def test_existing_reviewer_in_three_languages_must_explicitly_accept_the_exact_role(self):
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language):
                user, device = self.recipient('returning-' + language)
                invitation, raw, link = self.editorial_invite(user.email, language)
                client = Client()
                gate = self.login_through(client, user, link, language)
                marker = self.challenge(gate, language)
                state = client.session[SESSION_KEY]
                self.assertEqual((state['actor'], state['digest'], state['kind']),
                                 (str(user.pk), invitation.token_hash, 'editorial'))
                self.assertNotIn(raw, gate['Location'])
                self.assertNotIn(raw, json.dumps(dict(client.session)))
                self.assert_unused(invitation, user)

                resume = f'/{language}/editorial/invitation/resume/?invitation={marker}'
                verified = client.post(gate['Location'], {'token': otp(device)})
                self.assertRedirects(verified, resume, fetch_redirect_response=False)
                wrong_route = f'/{language}/invitation/resume/?invitation={marker}'
                self.assertEqual(client.post(wrong_route).status_code, 410)
                self.assertEqual(client.session[SESSION_KEY], state)
                landing = client.get(resume)
                self.assertContains(landing, 'id="editorial-invitation-accept-form"')
                self.assertContains(landing, str(self.darja.display_label))
                self.assertContains(landing, 'lang="' + language + '"')
                self.assertContains(landing, 'dir="' + ('rtl' if language == 'ar' else 'ltr') + '"')
                self.assertNotContains(landing, raw)
                self.assert_unused(invitation, user)
                self.assertRedirects(client.post(resume), f'/{language}/editorial/', fetch_redirect_response=False)
                self.assert_exact_grant(user)
                invitation.refresh_from_db()
                self.assertEqual(invitation.accepted_by, user)
                self.assertIsNotNone(invitation.used_at)
                self.assertNotIn(SESSION_KEY, client.session)
                self.assertNotIn(PENDING_NOTICE_INVITATION_DIGEST, client.session)
                self.assertEqual(client.post(resume).status_code, 410)

    def test_existing_editor_without_device_receives_recovery_codes_then_can_resume(self):
        user, _device = self.recipient('enrolment', confirmed=False)
        old = EditorialGrant.objects.create(user=user, variety=self.other_variety, edit=True)
        invitation, _raw, link = self.editorial_invite(user.email, 'en')
        client = Client()
        gate = self.login_through(client, user, link, 'en')
        marker = self.challenge(gate, 'en', 'setup')
        self.assertEqual(client.get(gate['Location']).status_code, 200)
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        codes = client.post(gate['Location'], {'password': PASSWORD, 'token': otp(device)})
        resume = f'/en/editorial/invitation/resume/?invitation={marker}'
        self.assertContains(codes, 'class="recovery-list"')
        self.assertContains(codes, f'href="{resume}"')
        self.assert_unused(invitation, user)
        self.assertRedirects(client.post(resume), '/en/editorial/', fetch_redirect_response=False)
        self.assert_exact_grant(user)
        old.refresh_from_db()
        self.assertTrue(old.edit)

    def test_anonymous_signup_acceptance_stays_localized_and_uses_ordinary_mfa_setup(self):
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language):
                name = 'fictional-new-editor-' + language
                invitation, _raw, link = self.editorial_invite(name + '@example.test', language)
                client = Client()
                self.assertContains(client.get(link), 'name="instruction_language"')
                signup = client.post(link, {'username': name, 'instruction_language': language,
                                             'password1': PASSWORD, 'password2': PASSWORD})
                if signup.status_code != 302:
                    self.fail(signup.context['form'].errors.as_text())
                self.assertRedirects(signup, f'/{language}/editorial/', fetch_redirect_response=False)
                user = User.objects.get(username=name)
                self.assert_exact_grant(user)
                self.assertNotIn(SESSION_KEY, client.session)
                self.assertRedirects(client.get(f'/{language}/editorial/'), f'/{language}/security/setup/',
                                     fetch_redirect_response=False)
                invitation.refresh_from_db()
                self.assertEqual(invitation.accepted_by, user)

    def test_revoked_expired_replaced_or_wrong_recipient_never_grant(self):
        for variant in ('revoked', 'expired', 'replaced', 'wrong-recipient'):
            with self.subTest(variant=variant):
                user, device = self.recipient('blocked-' + variant)
                mailbox = user.email
                if variant == 'wrong-recipient':
                    expected_recipient, _device = self.recipient('different-example')
                    mailbox = expected_recipient.email
                invitation, raw, link = self.editorial_invite(mailbox, 'en')
                client = Client()
                gate = self.login_through(client, user, link, 'en')
                if variant == 'wrong-recipient':
                    self.assertRedirects(gate, '/en/security/verify/', fetch_redirect_response=False)
                    self.assertNotIn(SESSION_KEY, client.session)
                    self.assertRedirects(client.post(gate['Location'], {'token': otp(device)}),
                                         '/en/app/', fetch_redirect_response=False)
                    self.assert_unused(invitation, user)
                    continue
                marker = self.challenge(gate, 'en')
                if variant == 'revoked':
                    revoke_editorial_invitation(self.operator, invitation.pk)
                elif variant == 'expired':
                    invitation.expires_at = timezone.now() - timedelta(days=1)
                    invitation.save(update_fields=['expires_at'])
                else:
                    new, _new_raw, new_link = self.editorial_invite(user.email, 'en')
                    gate = client.get(new_link)
                    new_marker = self.challenge(gate, 'en')
                    self.assertNotEqual(marker, new_marker)
                result = client.post(gate['Location'], {'token': otp(device)})
                expected_marker = new_marker if variant == 'replaced' else marker
                expected = f'/en/editorial/invitation/resume/?invitation={expected_marker}'
                self.assertRedirects(result, expected, fetch_redirect_response=False)
                invalid = f'/en/editorial/invitation/resume/?invitation={marker}'
                self.assertNotContains(client.post(invalid), raw, status_code=410)
                self.assert_unused(invitation, user)
                if variant == 'replaced':
                    self.assertEqual(client.session[SESSION_KEY]['digest'], new.token_hash)
                    self.assertContains(client.get(expected), 'id="editorial-invitation-accept-form"')
                else:
                    self.assertNotIn(SESSION_KEY, client.session)

    def test_legacy_practice_challenge_is_deliberately_ineligible_for_editorial_redemption(self):
        user, device = self.recipient('legacy-practice')
        invite, raw = issue_manual_practice_invitation(
            self.operator, self.practice, None, user.email, 'clinician', uuid4(),
        )
        client = Client()
        link = f'/en/invite/{raw}/'
        self.challenge(self.login_through(client, user, link, 'en'), 'en')
        session = client.session
        state = session[SESSION_KEY].copy()
        state.pop('kind')
        session[SESSION_KEY] = state
        session.save()
        raw_value = f'{state["actor"]}:{state["digest"]}:{state["started_at"]}'
        marker = salted_hmac('core.practice-invitation-mfa.v1', raw_value, algorithm='sha256').hexdigest()
        verified = client.post(f'/en/security/verify/?invitation={marker}', {'token': otp(device)})
        self.assertRedirects(verified, f'/en/invitation/resume/?invitation={marker}', fetch_redirect_response=False)
        self.assertEqual(client.post(f'/en/editorial/invitation/resume/?invitation={marker}').status_code, 410)
        self.assertEqual(client.session[SESSION_KEY]['digest'], invite.token_hash)
        self.assertContains(client.get(verified['Location']), self.practice.name)
        self.assertFalse(Membership.objects.filter(user=user).exists())
