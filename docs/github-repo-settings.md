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

### 2a. Dependabot reads from a second, separate secret store

`gh secret set CI_POSTGRES_PASSWORD` writes to the **Actions** store only.
Workflow runs triggered by Dependabot do not read that store - GitHub hands
them a separate, restricted **Dependabot** secret store instead. The same
secret name has to exist in both, or every Dependabot PR fails:

```bash
gh secret set CI_POSTGRES_PASSWORD --app dependabot   # prompts for the value
gh secret list --app dependabot                       # verify it took
```

**UI:** same page as above (Settings -> Secrets and variables -> Actions),
but the **Dependabot** tab in the left sidebar rather than the Actions tab.

**Variables are unaffected.** There is only one variables store - `gh
variable` has no `--app` flag at all - and Dependabot-triggered runs read
`vars.CI_POSTGRES_USER` / `vars.CI_POSTGRES_DB` normally. Only `secrets.*`
is split in two.

**Failure signature.** Without the Dependabot copy, `secrets.CI_POSTGRES_PASSWORD`
resolves to an empty string in `_backend-tests.yml`, so the Postgres service
container refuses to initialize and the job dies at ~18s, before a single
test runs:

```
Database is uninitialized and superuser password is not specified.
You must specify POSTGRES_PASSWORD to a non-empty value for the
superuser.
```

What makes this one expensive to diagnose is that it surfaces as a service
healthcheck timeout, which reads like a flaky runner. It is not flaky: it
fails 100% of the time on Dependabot PRs and passes 100% of the time on
human PRs off the same commit range - that split is the tell. Missing it
silently blocked the entire dependency queue here (nine PRs sat unmergeable
and it looked like neglect, not a CI gap).

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
- ❌ Require linear history - **leave this off.** The release flow merges
  `dev` into `main` without squashing (see "Release flow" in
  `CONTRIBUTING.md`), which produces a merge commit with two parents -
  precisely what linear history forbids. Enabled, it blocks the merge
  button on every `dev -> main` release PR. The live value is `false`, set
  that way deliberately during the branch split; don't "correct" it to
  `true`.
- ✅ Do not allow force pushes (may be on by default once protection exists)
- ✅ Do not allow deletions

**CLI:**
```bash
gh api repos/{owner}/{repo}/branches/main/protection \
  --method PUT \
  --field required_pull_request_reviews=null \
  --field required_status_checks='{"strict":true,"contexts":["Production gate passed"]}' \
  --field enforce_admins=false \
  --field required_linear_history=false \
  --field allow_force_pushes=false \
  --field allow_deletions=false \
  --field restrictions=null
```

Same caveat as §3: `required_pull_request_reviews` must be `null`, not
`{}`, or it silently requires 1 approval that a solo maintainer can never
supply. And `required_linear_history` must be `false` for the reason above -
a `true` here is what a squash-only repo wants, not this one.

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
