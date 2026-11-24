"""Read-only application checks against the runner's fictional restored database.

Explicit checks remain active under Python -O/PYTHONOPTIMIZE. Failure diagnostics
contain fixed codes only; subprocess exceptions and connection details stay out.
"""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True


class ReadcheckFailure(RuntimeError):
    pass


def require(ok, code):
    if not ok:
        raise ReadcheckFailure(code)


def main():
    require(os.environ.get('POSTGRES_HOST') == os.environ.get('POSTGRES_MIGRATION_HOST') ==
            '127.0.0.1', 'LOOPBACK_ONLY')
    database = os.environ.get('POSTGRES_DB', '')
    require(database.startswith('restore_reg_target_'), 'RESTORED_DATABASE_REQUIRED')
    require(os.environ.get('NEHEDROU_MEDIA_BACKEND') == 'filesystem', 'LOCAL_MEDIA_REQUIRED')
    require(os.environ.get('PGOPTIONS') == '-c default_transaction_read_only=on',
            'READ_ONLY_PROCESS_REQUIRED')
    require(not any(name.startswith('PG') and name != 'PGOPTIONS' for name in os.environ),
            'INHERITED_LIBPQ_ENVIRONMENT_REFUSED')
    import django
    django.setup()
    from django.conf import settings
    from django.db import connection, transaction
    from django.http import Http404
    from django.test import RequestFactory
    from core.models import User, Invitation, OperatorAcceptanceObservation
    from catalog.models import EditorialAccessInvitation, MediaAsset
    from care.models import Child
    from qualification.models import EvidenceDocument
    from core.views import export_child

    root = Path(os.environ['NEHEDROU_RESTORE_REGRESSION_ROOT']).resolve(strict=True)
    cluster = Path(os.environ['NEHEDROU_RESTORE_REGRESSION_CLUSTER']).resolve(strict=True)
    media = Path(settings.MEDIA_ROOT).resolve(strict=True)
    require(cluster.parent == root and media.parent == root and
            not root.is_relative_to(Path(settings.BASE_DIR).resolve()), 'ISOLATED_PATHS_REQUIRED')
    require(settings.DATABASES['default']['HOST'] == '127.0.0.1' and
            settings.DATABASES['default']['NAME'] == database, 'RESTORED_CONFIGURATION_REQUIRED')
    identities = json.loads(os.environ['NEHEDROU_RESTORE_REGRESSION_IDENTITIES'])
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
            cursor.execute('SHOW data_directory')
            require(Path(cursor.fetchone()[0]).resolve() == cluster, 'CLUSTER_IDENTITY_MISMATCH')
            cursor.execute('SELECT current_database()')
            require(cursor.fetchone()[0] == database, 'DATABASE_IDENTITY_MISMATCH')
        child = Child.objects.get(pk=identities['child'])
        factory = RequestFactory()

        def exported(user_id):
            request = factory.get('/fictional-restore-readcheck')
            request.user = User.objects.get(pk=user_id)
            with patch('core.views.audit'):
                response = export_child(request, child.pk)
            require(response.status_code == 200, 'EXPORT_FAILED')
            return json.loads(response.content)

        professional = exported(identities['professional'])
        family = exported(identities['family'])
        require(professional.get('schema_version') == family.get('schema_version') == 3,
                'EXPORT_SCHEMA_MISMATCH')
        require(professional.get('export_scope') == 'professional', 'PROFESSIONAL_SCOPE_MISMATCH')
        require(family.get('export_scope') == 'family', 'FAMILY_SCOPE_MISMATCH')
        require('FICTIONAL_PRIVATE_OBSERVATION' in json.dumps(professional),
                'PROFESSIONAL_OBSERVATION_MISSING')
        require('FICTIONAL_PRIVATE_OBSERVATION' not in json.dumps(family),
                'PRIVATE_OBSERVATION_DISCLOSED')
        require('FICTIONAL_SHARED_FEEDBACK' in json.dumps(family), 'SHARED_FEEDBACK_MISSING')
        try:
            exported(identities['outsider'])
        except Http404:
            pass
        else:
            raise ReadcheckFailure('UNRELATED_ACCOUNT_NOT_DENIED')
        expected_practice = identities['invitation_delivery']
        expected_editorial = identities['editorial_delivery']
        require(expected_practice in ('manual', 'pending') and expected_editorial in ('manual', 'pending'),
                'INVALID_EXPECTED_DELIVERY')
        require(Invitation.objects.get(pk=identities['invitation']).delivery == expected_practice,
                'PRACTICE_INVITATION_DELIVERY_CHANGED')
        require(EditorialAccessInvitation.objects.get(pk=identities['editorial']).delivery == expected_editorial,
                'EDITORIAL_INVITATION_DELIVERY_CHANGED')
        proof = EvidenceDocument.objects.get(pk=identities['document'])
        original = MediaAsset.objects.get(pk=identities['asset'])
        require(proof.intact, 'RESTORED_EVIDENCE_CHANGED')
        require(original.intact, 'RESTORED_IMAGE_CHANGED')
        derived = MediaAsset.objects.get(pk=identities['derived_asset'])
        require(derived.image_predecessor_id == original.pk and derived.file.name != original.file.name and
                derived.intact and derived.technical_metadata['sha256'] == original.technical_metadata['sha256'],
                'RESTORED_ILLUSTRATION_ORIGIN_CHANGED')
        observation = OperatorAcceptanceObservation.objects.get(pk=identities['operator_observation'])
        require(observation.recorded_by_id == identities['professional'] and
                observation.check_code == 'recent_restore_and_dossier_access' and observation.scope == 'local_fictional' and
                observation.outcome == 'gap_found' and observation.observed_on.isoformat() == identities['operator_observed_on'] and
                observation.evidence_sha256 == proof.sha256, 'RESTORED_OPERATOR_EVIDENCE_CHANGED')
    print(json.dumps({'professional_export': True, 'family_private_observation_excluded': True,
        'family_shared_feedback_preserved': True, 'unrelated_account_denied': True,
        'practice_invitation_delivery_preserved': True, 'editorial_invitation_delivery_preserved': True,
        'referenced_evidence_intact': True, 'referenced_image_intact': True,
        'operator_evidence_reference_preserved': True, 'illustration_predecessor_preserved': True}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        code = str(error) if isinstance(error, ReadcheckFailure) else 'READCHECK_FAILED'
        print(json.dumps({'status': 'failed', 'code': code}))
        sys.exit(1)
