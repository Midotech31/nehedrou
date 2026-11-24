"""Read-only, personal guidance; approval remains an authoritative service check."""
from urllib.parse import urlencode

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from catalog.services import allowed
from .models import DISCIPLINES, ReviewerCompetence
from .services import has_competence


def reviewer_experience_guidance(actor, variety, kinds):
    """Return status and own-declaration links for permitted review disciplines.

    Never expose declarations, verifier identities or supporting documents from
    another person. A current experience check does not qualify any content.
    """
    if not actor.is_authenticated or not actor.is_active:
        return []
    labels = dict(DISCIPLINES)
    permitted = [kind for kind in labels if kind in kinds and allowed(
        actor, variety, 'clinical_review' if kind == 'clinical' else 'linguistic_review')]
    declarations = {row.discipline: row for row in ReviewerCompetence.objects.filter(
        user=actor, variety=variety, discipline__in=permitted)}
    rows = []
    for kind in permitted:
        declaration = declarations.get(kind)
        current = has_competence(actor, variety, kind)
        state = ('missing' if declaration is None else 'inactive' if not declaration.active
                 else 'current' if current else 'check_required')
        state_labels = {
            'missing': _('Experience declaration needed'),
            'inactive': _('Declaration inactive'),
            'current': _('Independent check current'),
            'check_required': _('Independent check required'),
        }
        url = (reverse('qualification:competence_edit', args=[declaration.pk]) if declaration
               else reverse('qualification:competence') + '?' + urlencode(
                   {'variety': variety.code, 'discipline': kind}))
        rows.append({'kind': kind, 'kind_label': labels[kind], 'state': state,
                     'state_label': state_labels[state], 'url': url,
                     'action_label': _('View or update your declaration') if declaration
                     else _('Declare reviewer experience')})
    return rows
