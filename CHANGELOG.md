# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-08-26

### Added

- nginx TLS edge for the production deployment
- Redis-backed rate limiting
- MinIO object storage for recordings
- `dev`/`main` branch model: `dev` as the default/integration branch, `main`
  as the production branch, promoted via a release PR + tag
- Tiered CI: `ci.yml` (Tier 1-2, aggregator "Dev checks passed"),
  `release-gate.yml` (Tier 3, aggregator "Production gate passed"),
  `nightly-e2e-dev.yml`, `scheduled-audit.yml`
- `CONTRIBUTING.md` documenting the branch model and CI tiers
- `docs/github-repo-settings.md` documenting non-tracked repository
  configuration (default branch, required secrets/variables, branch
  protection)

[1.0.0]: https://github.com/haswanth13901/Zenoscribe/releases/tag/v1.0.0
