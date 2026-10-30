# Media qualification and current permission

Implemented for A05/A08/A09, 30 October 2026. These checks document a boundary;
they do not approve a licence, a speaker, a clinical stimulus or a use of the software.

Audio for real use requires an exact nonblank spoken text, a spoken variety code
and a declared human/synthetic origin in `provenance.audio`. The text and variety
must match each clinical item exactly. Silent audio, absent or empty profiles and
an unspecified voice source cannot qualify. An incomplete file can remain an
archive or demonstration; the advanced upload/import paths retain that distinction.
The guided clinical selector, activity and regional-pack approval/publication gates,
and probe checks all use the same binding check. Historical source metadata is
never completed with guessed provenance.

Media have `rights_validity`, `rights_valid_from`, `rights_valid_until`, `revoked`
and `revocation_reason`. Evidence has `validity`, `valid_from`, `valid_until` and
its existing irreversible revocation fields. `unknown`, `limited` and `unlimited`
are explicit declarations. Limited permission needs an expiry date. An optional
start and the expiry are inclusive dates, evaluated using the configured Django
local date (UTC in the current configuration). Contract prose is retained as
source material; the application does not search it for dates or legal meaning.

Migration defaults are unknown with no dates. Existing records therefore remain
incomplete until a responsible person documents the applicable permission in a
new evidence record. Evidence files and validity declarations are immutable;
renewal needs a new document. Revocation retains records and exact historical
snapshots. Media rights changes alter the exact manifest and invalidate prior
approvals. Expiry/revocation blocks current qualification and new publication or
assignment without rewriting an old activity, programme or administration.
Authorised editors can still inspect retained media and contract files. A media
revocation requires a reason and uploader or scoped publishing authority.

`catalog.integrity.IntegrityMiddleware` creates a ContextVar scope for each HTTP
request and clears it even when the view raises. `prepare_activities` batches the
assets, evidence, review authors, grants, competence declarations and latest
availability decisions for a page. No result is kept on a model instance, in a
process cache, in Redis or in the database. Identical private-file digests are
shared by storage object and filename only inside that request. Each later request
reloads its current permissions and reads its file bytes again. GET/HEAD/Range media
delivery independently hashes the actual bounded response bytes; a memoized
digest never substitutes for delivery verification.

The isolated regression page contains four complete fictional real-mode
activities: sixteen media, four rights documents, four familiarity documents and
twenty availability documents. Three repeated `usable` traversals after one batch
perform 44 distinct file digest computations and at most seven SQL queries,
including the activity query. An actual authenticated four-activity programme page
also stays within 40 SQL queries and 44 file digests (31 SQL in the isolated
SQLite measurement). Tests also alter stored bytes between requests,
revoke rights evidence, expire permissions under a controlled date and verify
delivery after a same-request byte replacement. These are I/O/query budgets on
small local fixtures, **not a measurement of S3 or production latency**. Remote
storage, network, SQL and cold-start durations still need separate operational
measurements on the deployed infrastructure with appropriate authorisation.
