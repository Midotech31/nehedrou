"""Editable caregiver structure; no example words or clinical approvals are invented."""
from django.utils.translation import gettext as _


def starting_structures(language):
    shared = {
        'audience': _('Describe the child’s needs, familiar words and the clinician-selected goal.'),
        'discover': _('Show each picture and agree on what it represents before asking for a response.'),
        'listen': _('Use the clinician-approved adult model. Give the child time to listen and respond.'),
        'support': _('Use a gesture, an object or a shorter instruction when helpful. Accept the child’s usual way of communicating.'),
        'limits': _('Pause if the child is tired or uncomfortable. Do not diagnose or score pronunciation from a picture choice.'),
        'review_notes': _('Check local vocabulary, image recognition, indication, recordings, variants and rights before clinical use.'),
    }
    by_kind = {
        'word_pair': (_('Explore two familiar words and their meanings.'), _('Take turns naming or showing the two words in a meaningful context.')),
        'vocabulary': (_('Understand and use two words selected by the clinician.'), _('Ask for one familiar item, then use the word in a short shared exchange.')),
        'phonological_contrast': (_('Explore the meaning difference in a clinician-selected phonemic contrast.'), _('Begin with listening and picture identification. Add spoken practice only as directed by the clinician.')),
        'requests': (_('Make a meaningful request or choice with a communication partner.'), _('Offer a real choice. Wait, acknowledge any communicative attempt and respond to the request.')),
        'categories': (_('Explore a useful relationship between familiar items.'), _('Discuss how the items relate and look for another example together.')),
        'actions': (_('Understand and use two familiar action words.'), _('Act out an action and invite the child to join or describe what happens.')),
        'relations': (_('Explore a spatial relation using familiar objects.'), _('Move a real object, describe its position and invite the child to show another position.')),
        'routines': (_('Support communication during a familiar daily routine.'), _('Use the words during the real routine. Follow the child’s interest and take turns.')),
        'storytelling': (_('Share a short account with a communication partner.'), _('Ask an open question about the pictures. Follow the child’s contribution without requiring one fixed answer.')),
    }
    structures = {}
    for kind, (objective, exchange) in by_kind.items():
        guide = dict(shared, objective=objective, exchange=exchange)
        structures[kind] = {f'guide_{language}_{key}': str(text) for key, text in guide.items()}
        structures[kind]['instructions_' + language] = str(exchange)
    return structures
