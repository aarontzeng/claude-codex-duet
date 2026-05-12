# Changelog

All notable changes to `claude-codex-duet` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- Nothing yet.

## [0.3.0] - 2026-05-12

### Added

- `cc-duet upgrade` command
- runtime `manifest.json` generation and drift detection
- package-owned `cc-duet hook-dispatch`
- tutorial, feature request template, release workflow, and changelog
- `REVIEW_CRITERIA.md` in the packaged runtime assets

### Changed

- renamed the generated target runtime to `.cc-duet/`
- renamed packaged scaffold assets to `src/cc_duet/assets/runtime/`
- expanded `doctor` into layered installer diagnostics with `--strict`
- updated install docs around release artifacts, upgrade flow, and venv-first maintainer workflows
- CI now runs on Ubuntu + macOS and validates built wheel artifacts

### Fixed

- existing target-project `.claude/` policy is preserved during setup
- setup now preflights settings and rolls back on invalid settings
- global hook no longer executes repo-local shell code

## [0.2.0] - 2026-05-12

### Added

- packaged `cc-duet` installer/scaffold workflow
- global `/cc-duet:setup` command
- initial OSS docs, CI, security policy, and contribution files

## [0.1.0] - 2026-05-12

### Added

- initial local dual-agent scaffold prototype
