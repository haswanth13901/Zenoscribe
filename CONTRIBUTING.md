# Contributing

## Branch model

- **`main`** is production. Every commit on `main` has passed the full
  release gate and is safe to deploy with `docker-compose.prod.yml`.
- **`dev`** is integration. It's the default branch and where day-to-day
  work - features, fixes, dependency bumps - lands first.

## The invariant

**Both branches carry the identical file set.** `dev` and `main` differ only
in *maturity* (what's been through the release gate), never in *content
shape*. There is no branch that has `docker-compose.yml` and no branch that
doesn't; no branch that has `voice_transcriber/tests/` and no branch that
doesn't.

Dev/prod separation already exists at the file level - which compose file,
which env file, and which `ENV` value you use at runtime:

| Concern | Dev | Prod |
|---|---|---|
| Compose | `docker-compose.yml` | `docker-compose.prod.yml` |
| Env template | `.env.example` -> `.env` | `.env.production.example` -> `.env.production` |
| Backend image target | `backend-with-frontend` | `backend` (Dockerfile default) |
| Frontend image target | `frontend/Dockerfile` -> `dev` stage | `frontend/Dockerfile` -> final nginx stage |
| Runtime switch | `ENV=development` | `ENV=production` (enforced in `config.py`) |
| Dependencies | `requirements-dev.txt` | `requirements.txt` |

Environment is selected by **which file you point at**, never by which
branch you're on. A future "clean up `main`" pass that deletes
`docker-compose.yml`, `requirements-dev.txt`, or `voice_transcriber/tests/`
from `main` would break the very next `dev -> main` merge (they'd come
right back) and fail CI on `main` immediately (`backend-fast`/
`frontend-unit` need them). `.dockerignore` already keeps all of this out of
the *shipped image* - that's the actual dev/prod boundary, not the branch.

## Daily flow

`dev` -> feature branch -> PR into `dev` -> CI green -> squash merge.

## Release flow

1. Open a PR from `dev` into `main`.
2. Full release gate green (see CI section below).
3. Merge - **no squash**, so the release history stays traceable to the
   individual commits that made it in.
4. Tag it: `git tag -a vX.Y.Z -m "..." && git push origin vX.Y.Z`.

`main` is what the deploy VM pulls - a merge into `main` is a release.

## Hotfix flow

1. Branch from `main` (not `dev`).
2. PR into `main`, release gate green, merge.
3. Tag it.
4. **Immediately back-merge `main` -> `dev`** so the fix isn't lost the next
   time `dev` merges forward - the branches drift apart the moment this step
   is skipped.

## CI - four tiers

| Tier | Runs on | Jobs | Why |
|---|---|---|---|
| 1 - Fast (~5 min) | Every push to `dev`/`main`, every PR into `dev` | lint, fast pytest, Vitest, compose/env validation | Immediate signal, cheap |
| 2 - Dev-parity | `dev` pushes/PRs only | builds both dev images (`backend-with-frontend`, frontend `dev` stage) | Nothing built these before - they could break silently |
| 3 - Release gate | PRs/pushes to `main`, version tags | Playwright E2E, prod image build + Trivy scan, dependency audit, production config guardrails | Everything that must be true before a deploy |
| 4 - Scheduled | Weekly cron on `main` | dependency + image audit | Catches a CVE disclosed against an unchanged dependency |

Tier 3's Playwright suite doesn't run on every `dev` PR (it's a real
~15-20 minute job) - see `nightly-e2e-dev.yml` for the tradeoff (a nightly
run against `dev` instead) and how to change that decision if it's wrong for
how this team works.

Branch protection depends only on each workflow's aggregator job
("Dev checks passed" / "Production gate passed"), never on an individual
conditional or path-filtered job - see `docs/github-repo-settings.md` for
why and how it's wired up.

## Which command runs where

| Situation | Command |
|---|---|
| Local dev (full stack, hot-reload) | `docker compose up -d --build` |
| Local bare-metal | `scripts/bootstrap.sh` / `bootstrap.ps1`, then the two-terminal workflow (see README) |
| Production | `docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build` |
| First prod boot only | `scripts/init-letsencrypt.sh` |

See `README.md` for the full developer setup and `DEPLOYMENT.md` for the
full production runbook.

## Branch naming

| Pattern | Use |
|---|---|
| `feature/<issue>-<slug>` | New functionality, branched from `dev` |
| `fix/<issue>-<slug>` | Bug fix, branched from `dev` |
| `hotfix/<issue>-<slug>` | Urgent production fix, branched from `main` (see Hotfix flow above) |
| `chore/<slug>` | Maintenance/governance work with no tracking issue |
| `docs/<slug>` | Documentation-only changes |

## Commit messages

This project follows [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <description>
```

Common types: `feat`, `fix`, `chore`, `ci`, `docs`. For example:
`feat(auth): add password reset flow` or `fix: correct off-by-one in turn
attribution`.

This isn't just style - `gh release create --generate-notes` groups the
release notes by these types, so a consistent prefix makes the generated
changelog for the next release actually readable.
