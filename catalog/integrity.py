"""Fresh per-request verification, with no process or persistent result cache.

Only file digests and records fetched during this scope are shared. A new HTTP
request always reloads rights and rereads private bytes. Delivery hashes its own
response bytes independently, including HEAD and Range requests.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

_state = ContextVar('editorial_integrity_state', default=None)


@contextmanager
def integrity_scope():
    token = _state.set({})
    try:
        yield
    finally:
        _state.reset(token)


class IntegrityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with integrity_scope():
            return self.get_response(request)


def request_value(namespace, key, factory):
    state = _state.get()
    if state is None:
        return factory()
    values = state.setdefault(namespace, {})
    if key not in values:
        values[key] = factory()
    return values[key]


def remember(namespace, key, value):
    state = _state.get()
    if state is not None:
        state.setdefault(namespace, {})[key] = value


def evidence_document(reference):
    from qualification.models import EvidenceDocument
    try:
        key = UUID(str(reference))
    except (ValueError, TypeError, AttributeError):
        return None
    return request_value('documents', key, lambda: EvidenceDocument.objects.filter(pk=key).first())


def activity_reviews(activity):
    return request_value('reviews', activity.pk,
        lambda: list(activity.reviews.select_related('reviewer').order_by('-created_at', '-pk')))


def prepare_activities(activities):
    """Batch a page's verification graph; callers retain their existing objects.

    The function deliberately requires a request/scope: outside one it returns
    the materialised list without keeping records on model instances.
    """
    from catalog.models import MediaAsset, Review, EditorialGrant
    from catalog.readiness import reference_asset_id
    from qualification.models import EvidenceDocument, ReviewerCompetence, AvailabilityDecision
    rows = list(activities)
    if _state.get() is None or not rows:
        return rows
    real = [row for row in rows if not row.is_demo]
    asset_keys = set()
    document_ids = set()
    for row in rows:
        for field, kind in [('image_a', 'image'), ('image_b', 'image'), ('audio_a', 'audio'), ('audio_b', 'audio')]:
            key = reference_asset_id(getattr(row, field), kind)
            if key:
                asset_keys.add((key, kind))
        for side in ['a', 'b']:
            proof = (row.item_metadata or {}).get(side, {}).get('familiarity', {})
            if isinstance(proof, dict):
                try:
                    document_ids.add(UUID(str(proof.get('evidence', ''))))
                except (ValueError, TypeError, AttributeError):
                    pass
    assets = {asset.pk: asset for asset in MediaAsset.objects.filter(pk__in={key for key, kind in asset_keys}).select_related('rights_evidence')}
    for key, kind in asset_keys:
        asset = assets.get(key)
        remember('assets', (key, kind), asset if asset and asset.kind == kind else None)
    for asset in assets.values():
        if asset.rights_evidence_id:
            remember('documents', asset.rights_evidence_id, asset.rights_evidence)
    reviews = {row.pk: [] for row in real}
    for review in Review.objects.filter(activity_id__in=reviews).select_related('reviewer').order_by('-created_at', '-pk'):
        reviews[review.activity_id].append(review)
    for key, values in reviews.items():
        remember('reviews', key, values)
    versions = {row.fingerprint() for row in real}
    decisions = list(AvailabilityDecision.objects.filter(module='practice', variety_id__in={row.variety_id for row in real}, version__in=versions).select_related('decided_by', 'variety'))
    # Ordering selects the latest decision for every exact version, even when revoked.
    latest = {}
    for decision in decisions:
        latest.setdefault((decision.module, decision.variety_id, decision.version), decision)
        for entry in decision.evidence.values() if isinstance(decision.evidence, dict) else []:
            try:
                document_ids.add(UUID(str(entry.get('id', ''))))
            except (ValueError, TypeError, AttributeError):
                pass
    for row in real:
        key = ('practice', row.variety_id, row.fingerprint())
        remember('availability', key, latest.get(key))
    users = {review.reviewer_id for values in reviews.values() for review in values} | {decision.decided_by_id for decision in decisions}
    varieties = {row.variety_id for row in real}
    grants = {(grant.user_id, grant.variety_id): grant for grant in EditorialGrant.objects.filter(user_id__in=users, variety_id__in=varieties)}
    competence_rows = ReviewerCompetence.objects.filter(user_id__in=users, variety_id__in=varieties, active=True).select_related('evidence','current_decision__decided_by')
    competences = {(competence.user_id, competence.variety_id, competence.discipline): competence for competence in competence_rows}
    for user in users:
        for variety in varieties:
            remember('grants', (user, variety), grants.get((user, variety)))
            for discipline in ['clinical', 'linguistic']:
                remember('competences', (user, variety, discipline), competences.get((user, variety, discipline)))
    for competence in competences.values():
        if competence.evidence_id:
            remember('documents', competence.evidence_id, competence.evidence)
    documents = {document.pk: document for document in EvidenceDocument.objects.filter(pk__in=document_ids)}
    for key in document_ids:
        remember('documents', key, documents.get(key))
    return rows
