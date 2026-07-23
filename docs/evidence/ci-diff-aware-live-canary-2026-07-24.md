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
| Branch | `codex/ci-docs-live-canary-20260724` |
| Canary change | single added file `docs/evidence/ci-diff-aware-live-canary-2026-07-24.md` |
| Expected skipped groups | IaC, healthcheck, Hermes, static fixtures, tools, kustomize |
| Expected executed jobs | Secret scan, gitleaks |
| Expected required check | `static-checks` green |

The first commit in PR #439 was the predeclared canary payload. It made no runtime or
production changes.

## Observed result

PR: <https://github.com/PavelLizunov/unified-agent-platform/pull/439>

Run: <https://github.com/PavelLizunov/unified-agent-platform/actions/runs/30054160600/job/89362279743>

`static-checks` passed in 12 seconds. The classifier, Secret scan, and gitleaks succeeded.
IaC validation, the healthcheck self-test, Hermes tests, static fixture tests, tools tests,
kustomize installation, and the kustomize build were all reported as `skipped`.

Acceptance verdict: **PASS**. The observed steps match the predeclared expectation.

## Honest boundary

This canary proves only that one added `.md` file triggers the expected skip/execute
pattern on this branch. It does not prove correctness for mixed diffs, code changes,
deleted files, or renames. It also does not live-inject a classifier crash. Those cases
remain covered by deterministic regression tests and full-matrix runs.
