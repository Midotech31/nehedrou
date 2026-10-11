"""Search normalization only; never rewrite words, transcriptions or clinical targets."""
import re
import unicodedata

def search_key(text):
    text = unicodedata.normalize('NFKC', str(text)).casefold()
    text = re.sub(r'[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]', '', text)
    return ' '.join(text.translate(str.maketrans('أإآٱ', 'اااا')).split())

def activity_search_text(activity):
    values = [activity.title, activity.word_a, activity.word_b, activity.contrast]
    # Index the activity's purpose and vocabulary, not repeated support/limits.
    guides = activity.practice_guide if isinstance(activity.practice_guide, dict) else {}
    metadata = activity.item_metadata if isinstance(activity.item_metadata, dict) else {}
    for guide in guides.values():
        if isinstance(guide, dict) and isinstance(guide.get('objective'), str):
            values.append(guide['objective'])
    for item in metadata.values():
        if not isinstance(item, dict):
            continue
        if isinstance(item.get('meaning'), str):
            values.append(item['meaning'])
        candidates = item.get('family_word_candidates', [])
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if isinstance(candidate, str):
                values.append(candidate)
            elif isinstance(candidate, dict):
                if isinstance(candidate.get('word'), str):
                    values.append(candidate['word'])
                alternatives = candidate.get('family_alternatives', [])
                if isinstance(alternatives, list):
                    values.extend(word for word in alternatives if isinstance(word, str))
    return search_key(' '.join(values))
