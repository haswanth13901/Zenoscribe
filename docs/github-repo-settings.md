# GitHub repository settings

These can't be applied via `git` - they're repository configuration, not
tracked files. Apply them once after the `dev`/`main` branch split lands and
CI has run at least once on both branches (see the note on required-check
names below).

## 1. Default branch: `dev`

Day-to-day clone/checkout/PR-target should be `dev`, not `main`.

**UI:** Settings -> General -> Default branch -> switch button next to
`main` -> select `dev` -> Update.

**CLI:**
```bash
gh repo edit --default-branch dev
```

## 2. Confirm CI's Actions Variables/Secrets exist

`_backend-tests.yml` (used by both `ci.yml` and `release-gate.yml`) reads
these at the repo level - without them, `backend-fast`/`backend-integration`
fail immediately with an empty Postgres user/password.

**UI:** Settings -> Secrets and variables -> Actions.
- Variables tab: `CI_POSTGRES_USER`, `CI_POSTGRES_DB`
- Secrets tab: `CI_POSTGRES_PASSWORD`

**CLI:**
```bash
gh variable list
gh secret list
# If missing:
gh variable set CI_POSTGRES_USER --body "zenoscribe_ci"
gh variable set CI_POSTGRES_DB --body "zenoscribe_ci"
gh secret set CI_POSTGRES_PASSWORD   # prompts for the value
```
These are CI-only, ephemeral, destroyed with the container at the end of
every run - not production credentials.

## 3. Branch protection on `dev`

**UI:** Settings -> Branches -> Add branch protection rule -> Branch name
pattern: `dev`.
- ✅ Require a pull request before merging
- ✅ Require status checks to pass before merging -> search for and add
  **only**: `Dev checks passed` (the `ci.yml` aggregator job - see §5 below
  for why nothing else is listed here)
- ✅ Require branches to be up to date before merging

**CLI:**
```bash
gh api repos/{owner}/{repo}/branches/dev/protection \
  --method PUT \
  --field required_pull_request_reviews=null \
  --field required_status_checks='{"strict":true,"contexts":["Dev checks passed"]}' \
  --field enforce_admins=false \
  --field restrictions=null
```

`required_pull_request_reviews` must be `null`, not `{}` - an empty object
still enables the reviews requirement with its default of 1 approving
review, which blocks every PR on a solo-maintainer repo (nobody else can
approve, and GitHub doesn't let you approve your own PR). Only `null`
actually means "no review requirement."

## 4. Branch protection on `main`

**UI:** same page, Branch name pattern: `main`.
- ✅ Require a pull request before merging
- ✅ Require status checks to pass before merging -> add **only**:
  `Production gate passed` (the `release-gate.yml` aggregator)
- ✅ Require branches to be up to date before merging
- ✅ Require linear history (matches the release flow's "merge, no squash"
  - this still forbids merge commits with multiple parents; if that
  conflicts with the intended non-squash merge, use "Require merge queue"
  off and a fast-forward-only merge instead, and revisit this checkbox)
- ✅ Do not allow force pushes (may be on by default once protection exists)
- ✅ Do not allow deletions

**CLI:**
```bash
gh api repos/{owner}/{repo}/branches/main/protection \
  --method PUT \
  --field required_pull_request_reviews=null \
  --field required_status_checks='{"strict":true,"contexts":["Production gate passed"]}' \
  --field enforce_admins=false \
  --field required_linear_history=true \
  --field allow_force_pushes=false \
  --field allow_deletions=false \
  --field restrictions=null
```

Same caveat as §3: `required_pull_request_reviews` must be `null`, not
`{}`, or it silently requires 1 approval that a solo maintainer can never
supply.

## 5. The required-check trap - why only the two aggregators are listed above

GitHub treats a required status check that **never reports** as *pending
forever*, permanently blocking the PR. Two things now in this repo can cause
that:

- A job gated by `if:` that evaluates false reports **`skipped`**, not
  `success` (e.g. `ci.yml`'s `dev-image-build` on a `main` push).
- A job filtered by a workflow-level `paths:` when the triggering
  push/PR touches no matching file never queues **at all**.

Both apply here, so **do not** add individual jobs like `backend-lint`,
`backend-fast`, `dev-image-build`, `docker-build`, or
`prod-config-guardrails` as required checks directly - only the two
aggregator jobs (`gate` in each workflow, named `Dev checks passed` and
`Production gate passed`) are required. Each aggregator runs with
`if: always()` and explicitly treats `skipped` as acceptable but
`failure`/`cancelled` as fatal - see the `gate` job in `ci.yml`/
`release-gate.yml` for the exact logic.

**Before applying §3/§4 above:** push once to each branch (or open one PR
into each) so both workflows actually run, then open that run in the
Actions tab and copy the exact rendered job name for the `gate` job in each
workflow. It must match the `name:` field character-for-character
(`Dev checks passed` / `Production gate passed` as currently named in
`ci.yml`/`release-gate.yml`) - if either job's `name:` is ever edited later,
the required-check string in branch protection has to be updated to match,
or protection silently stops enforcing anything for that check.
