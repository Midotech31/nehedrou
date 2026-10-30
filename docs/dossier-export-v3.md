# Dossier export, schema 3 — 30 October 2026

`GET /<interface-language>/children/<uuid>/export/` retains the existing responsible-professional or active-family-link authorization. Membership/link revocation and practice isolation apply at every export. Subscription expiry does not prevent authorized dossier retrieval. `export_scope` explicitly distinguishes `professional` and `family`; the response is a JSON attachment with private/no-store caching.

Top-level keys: `schema_version` (3), `export_scope`, `exported_at` (UTC ISO timestamp), `child`, `programs`, `followup`, `exclusions`. Stable local UUID identifiers link records, foreign keys use their database field names with `_id`, dates/timestamps use ISO formatting, and JSON domain fields retain their original structure. The schema does not confer clinical qualification or psychometric equivalence. There is no destructive import endpoint.

Professional `followup` contains:

| Key | Included records |
| --- | --- |
| `goals` | Every active/closed goal, author, variety, target, position/context scope, variants, rationale, expected realization, functional goal, assessment status/note, linked definition and reserved words. |
| `protocols` | Exact referenced protocol/version identities, series, design content, items, target scope, rights/evidence references, state and append-only review decisions. The current definition state is distinct from each historical administration snapshot. |
| `observations` | Every draft/finalized administration, professional/finalization/sharing attribution and dates, conditions, familiarity, untouched protocol/goal/item/media snapshot, original summary and newly calculated descriptive groups. Alternate-context label and reason remain explicit; `comparable_to_previous` is always false for separate observations or legacy snapshots without structured context. |
| `observations[].ratings` | Original immutable human rating fields and authors/dates, `current_data`, and every ordered correction with author/date/reason/data. Original finalized summaries are retained alongside current descriptive groups. |
| `exposures` | All declared exposures including their variety, status, source session, author, source note and observation/creation dates. Later reserved-word exposure is also identified per administration. |
| `coaching` | Shared instructions, declared instruction language, example, accompanied trial, understanding check, next review, author/date and private clinician note. |
| `home_practice_feedback` | All caregiver returns, participation, support, difficulty, stop reason, comment and dates. These declarations are not speech scores. |
| `responsibility_transfers` | Append-only handover identities and dates when the access-continuity module is installed. Historical authors remain unchanged. |

`programs` retains existing programs, schedule, planning, instructions, immutable activity version references, session reports, practice runs/tasks and shared feedback; professional rows additionally contain authorship and private program observations. It works when no family program exists: follow-up data is independently selected from the child.

Family `followup` contains only currently expressly shared finalized observation summaries, safe coaching fields and the requesting caregiver's own practice returns. It excludes raw goals, protocol items/versions/snapshots, ratings/corrections, professional conditions, familiarity/exposure declarations, clinician notes and responsibility history. Family program items reserved for follow-up remain excluded. Free text accidentally containing a currently or historically reserved word is conservatively replaced by `[withheld: reserved content]`; this lexical guard does not certify clinical suitability or semantic confidentiality. Revoked/empty shares disappear. A multilingual spelling guard uses the existing conservative Arabic-mark normalization.

`exclusions` describes excluded categories and reasons; family output adds withheld program-item and free-text-field counts without disclosing the reserved words. Professional JSON excludes binary media/evidence bytes (references and recorded digests remain), credentials/session tokens, submission idempotency keys and payload digests. Binary retrieval requires its existing separate authorization. The detailed CSV per administration remains available.

## Structured target context

New goal/protocol forms collect `target_scope = {"position": "initial|medial|final", "context": "explicit_context_identifier"}`. The responsible professional chooses the context identifier, for example `isolated_word` or `carrier_phrase`; the application does not infer phonetic/clinical equivalence from free text. A goal observation requires exact variety, normalized phoneme, structured position and context agreement. Compatible protocol choices are filtered, then service/model validation is repeated.

An expressly selected `alternate_context` observation still requires the same phoneme/variety and an explicit label and reason. It remains a separate observation and never becomes an automatically equivalent goal measurement. Nonmatching or undocumented legacy scopes require that separate path, or an explicit new protocol version with documentation. Existing free-text positions, empty structured scopes, reviews and historical snapshots are not backfilled or rewritten. Real protocol readiness requires structured scope plus item occurrence position matching; source imports remain unapproved drafts. Demo simulation contexts explicitly describe fiction and do not assert human review.

Existing administrations receive only the nonclinical sentinel `observation_scope=legacy`; the migration leaves their JSON snapshots structurally unchanged. New service-created observations explicitly select `goal` or `alternate_context`. No historical context, rights provenance or human approval is manufactured. All new goals require explicit structured scope server-side; source protocol drafts may remain incomplete.
