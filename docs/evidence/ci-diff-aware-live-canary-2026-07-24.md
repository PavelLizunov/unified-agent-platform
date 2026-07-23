# CI diff-aware skip live canary — 2026-07-24

## Purpose

Verify that a pure added Markdown file (this evidence document) causes the diff-aware CI
matrix to **skip** expensive groups — IaC, healthcheck, Hermes, static fixtures, tools,
kustomize — while the Secret scan and gitleaks jobs still execute unconditionally and the
required `static-checks` status check remains green.

## Predeclaration

| Item | Value |
|---|---|
| Base commit | `3cb45d50c1e85da5fee902e1ea62ed5f1946c1f6` |
| Branch | `codex/ci-docs-canary-20260724` |
| Canary change | single added file `docs/evidence/ci-diff-aware-live-canary-2026-07-24.md` |
| Expected skipped groups | IaC, healthcheck, Hermes, static fixtures, tools, kustomize |
| Expected executed jobs | Secret scan, gitleaks |
| Expected required check | `static-checks` green |

This commit **is** the predeclared canary payload. No result is claimed yet.

## Observation (pending)

Run URL: _to be filled after CI observation_

Result: _to be filled after CI observation_

## Honest boundary

This canary proves only that one added `.md` file triggers the expected skip/execute
pattern on this branch. It does not prove correctness for mixed diffs, code changes,
deleted files, or renames. Those remain covered by existing full-matrix runs.
