# Pilot privacy and data handling

Private price uploads are available only to the authenticated owner. The API
stores normalized OHLCV rows, source metadata and a content hash; it does not
retain the original CSV bytes. Every read and delete includes an owner predicate.

Phase 8 enforces per-user and per-asset upload limits, a total row budget, and
opportunistic expiry cleanup using `STOCK_UPLOAD_RETENTION_DAYS`. A scheduled
retention job belongs with later background-job work; until then, operators must
run a documented periodic cleanup or keep the pilot invite-only.

Upload creation and deletion produce append-only audit records without storing
CSV contents. Database backups contain user accounts, audits and private uploads,
so they must be encrypted, access-controlled, retained for a declared period,
and included in deletion/incident procedures.

Arbitrary PDF and Excel uploads are not supported. Before adding them, implement
file-signature validation, macro/external-link rejection, malware scanning,
sandboxed extraction, per-tenant object keys, page/cell citations, size/page
limits, prompt-injection controls and deletion of derived chunks/embeddings.

Before public launch, publish a user-facing privacy notice covering purpose,
retention, deletion requests, subprocessors, backup retention, contact details
and jurisdiction. This engineering document is not a substitute for legal review.
