# Audits & design docs

**These are point-in-time snapshots, not living documentation.** Each one was
written against the repo as it stood on a particular day and is kept for the
reasoning it records, not as a description of current behavior. Where an audit
and the code disagree, the code is right and the audit is history.

For documentation that's maintained against `dev`, see
[CONTRIBUTING.md](../../CONTRIBUTING.md), [DEPLOYMENT.md](../../DEPLOYMENT.md),
[docs/architecture.md](../architecture.md) and [docs/frontend.md](../frontend.md).

| Document | What it covers |
|---|---|
| [DEPLOYMENT_READINESS_AUDIT.md](DEPLOYMENT_READINESS_AUDIT.md) | Pre-go-live review: findings by priority (P1/P2), what was fixed, what was accepted |
| [SCALABILITY_AUDIT.md](SCALABILITY_AUDIT.md) | Findings F1–F11 — what blocked running more than one `web` replica |
| [SCALABILITY_DESIGN.md](SCALABILITY_DESIGN.md) | The design chosen to resolve those findings (Redis counters, MinIO storage, boot ID) |
| [HORIZONTAL_SCALABILITY_READINESS.md](HORIZONTAL_SCALABILITY_READINESS.md) | Verification status of that work, and the multi-replica validation still to run on a real VM |
| [E2E_Review.md](E2E_Review.md) | End-to-end review notes and open items |

The findings are referenced by name from source comments (e.g. "see
SCALABILITY_AUDIT finding F4" in `config.py`, `db.py`, `auth.py`), which is why
the filenames are worth keeping stable.
