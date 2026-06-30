# Codex Readonly Code Review - 2026-06-28

Audience: Claude Code and future Codex workers.

Mode:

- Readonly code review, except for writing this report file.
- No source code, manifest, script, or runbook fixes were made in this pass.
- No `kubectl apply/delete/rollout`, restore drill, failover drill, or destructive operation was performed.
- Do not copy secret values from any tool output into prompts, commits, markdown, logs, or issues.

## Reviewed Blocks

Primary review blocks:

1. Hermes runtime service and tests: `hermes/hermes.py`, `hermes/tests/*`, `hermes/README.md`.
2. GitOps deploy artifacts for Hermes and agent runtime: `clusters/prod/infra/hermes*.yaml`, `litellm.yaml`, egress manifests.
3. Static gates and CI: `.github/workflows/ci.yml`, `tests/static/*`, `tests/verify-local.ps1`.
4. Ops/bootstrap/backup scripts: `infra/ops/configure-github-flux.sh`, `clusters/prod/infra/hermes-agent-backup.yaml`, `infra/ops/ops-backup/backup.sh`.
5. Light pass only: Ansible k3s playbooks and sing-box config generator.

Deferred deeper blocks:

- Full OpenTofu module review.
- Full Ansible idempotency review against real hosts.
- Full restore/failover behavior review.
- Full external hermes-agent upstream behavior review.

## Findings

### P1 - Hermes source code and deployed ConfigMap are out of sync

Files:

- `hermes/hermes.py`
- `clusters/prod/infra/hermes-code-configmap.yaml`
- `clusters/prod/infra/hermes.yaml`
- `.github/workflows/ci.yml`

Observed:

- Current `hermes/hermes.py` normalized-LF hash: `02d91d69f5d8`.
- Embedded `clusters/prod/infra/hermes-code-configmap.yaml` hash: `e972b6461691`.
- Deployment annotation `hermes/code-rev` is also `e972b6461691` at `clusters/prod/infra/hermes.yaml:71`.
- First functional diff appears around the Kubernetes devmode fallback:
  - source has the fallback branch at `hermes/hermes.py:365-374`;
  - embedded ConfigMap still returns immediately at `clusters/prod/infra/hermes-code-configmap.yaml:368-369`.
- CI runs unit tests against `hermes/hermes.py` at `.github/workflows/ci.yml:34-35`, and separately runs `kustomize build` at `.github/workflows/ci.yml:38-39`, but there is no check that the generated ConfigMap matches the source.

Why this matters:

- A green CI run can test code that is not the code Flux deploys.
- A source-only fix to Hermes can look validated while the live cluster continues running stale embedded code.

Acceptance criteria:

- Regenerate `clusters/prod/infra/hermes-code-configmap.yaml` from `hermes/hermes.py`.
- Update `clusters/prod/infra/hermes.yaml` `hermes/code-rev` to the current source hash.
- Add a CI/static check that extracts `data.hermes.py` from the ConfigMap and compares it to `hermes/hermes.py`, including the expected annotation hash.

### P1 - Hermes exposes full tool traces, including pod logs, back to API clients

Files:

- `hermes/hermes.py`
- `clusters/prod/infra/hermes.yaml`

Observed:

- `tool_kube_logs` can return up to 12k chars of pod logs at `hermes/hermes.py:380-391`.
- Tool results are stored directly in `trace` at `hermes/hermes.py:523` and `hermes/hermes.py:581`.
- The HTTP response always includes `"hermes_trace": trace` at `hermes/hermes.py:682-689`.
- The ServiceAccount ClusterRole grants cluster-wide access to `pods/log` at `clusters/prod/infra/hermes.yaml:17-22`.
- `hermes/README.md:48-51` says a deployed read-only key exists for safe inspection.

Why this matters:

- A read-scoped API key can trigger log reads and receive raw log payloads in `hermes_trace`, even if the final answer is short or sanitized.
- Kubernetes logs often accidentally contain tokens, env dumps, OAuth errors, request headers, or other sensitive operational context.
- This is worse because the trace is returned by default, not only in a debug mode.

Acceptance criteria:

- Make trace emission opt-in, admin-only, or redacted by default.
- Redact or omit `result` fields for sensitive tools such as `kube_logs`.
- Consider removing `pods/log` from the general read scope, or restrict it to an explicit namespace/pod allowlist.
- Add tests proving non-debug responses do not include raw tool results.

### P1 - Hermes-agent backup can succeed while silently missing important files

Files:

- `clusters/prod/infra/hermes-agent-backup.yaml`
- `runbooks/hermes-agent-dr.md`

Observed:

- Backup validation only checks that the zip exists, is structurally valid, and contains at least one `.codex/*.sqlite` file at `clusters/prod/infra/hermes-agent-backup.yaml:45-50`.
- The manifest comments claim the backup covers auth/config/state such as `auth.json`, `.env`, and Codex/Hermes state at `clusters/prod/infra/hermes-agent-backup.yaml:1-9`.
- The DR runbook lists `auth.json`, Codex brain SQLite files, `USER.md`, and other state as recoverable at `runbooks/hermes-agent-dr.md:12-14`.
- A live readonly log check observed permission-denied skips for several `.claude*` and `.codex/config.toml` files while the backup still completed. Do not copy any skipped file contents or secret values into notes.

Why this matters:

- The CronJob can publish a "successful" archive that passes current validation but is not a complete restore artifact.
- DR confidence becomes false: the project may discover missing auth/config files only during an actual restore.

Acceptance criteria:

- Treat permission-denied backup warnings as failure, or explicitly exclude those paths and document why they are regeneratable.
- Validate a manifest of expected files, not only `.codex/*.sqlite`.
- Add a canary restore check that verifies restored Hermes/Codex/Claude behavior without printing secrets.

### P2 - `verify-local -IncludeReadiness` and `-IncludeOps` can pass when required dependencies are missing

Files:

- `tests/verify-local.ps1`
- `tests/git/check-git-remote.ps1`
- `tests/s3/check-s3-env.ps1`
- `tests/ops/check-ops-node.ps1`
- `tests/ops/check-ops-deploy-path.ps1`

Observed:

- `tests/verify-local.ps1:45-57` invokes readiness and ops checks as if they are gates.
- `tests/git/check-git-remote.ps1:19-22` prints `git-remote-missing` and exits `0`.
- `tests/s3/check-s3-env.ps1:23-28` prints `s3-env-missing` and exits `0`.
- `tests/ops/check-ops-node.ps1:28-35` prints `ops-node-missing` and exits `0` unless `-Require` is passed.
- `tests/ops/check-ops-deploy-path.ps1:53-60` prints `ops-deploy-path-missing` and exits `0` unless `-Require` is passed.
- `verify-local.ps1` calls the ops checks without `-Require` at `tests/verify-local.ps1:55-57`.

Why this matters:

- A user or agent can run a command named like a readiness/ops gate and receive an overall success even when git remote, S3 env, or ops node access is missing.
- This weakens milestone claims and can mislead handoffs.

Acceptance criteria:

- Add a strict mode to readiness checks, or make `verify-local -IncludeReadiness/-IncludeOps` pass `-Require` equivalents.
- Keep optional informational checks available under a clearly named non-gating mode.
- Add tests or a transcript fixture showing missing dependencies return non-zero in gating mode.

### P2 - Kustomization orphan check compares basenames, not resolved resource paths

Files:

- `tests/static/validate_iac.py`
- `tests/static/test_validate_iac_orphans.py`

Observed:

- `_find_kustomization_orphans` builds `referenced = {Path(r).name for r in resources}` at `tests/static/validate_iac.py:195-200`.
- Local YAML files are then checked by `yaml_file.name` at `tests/static/validate_iac.py:203-208`.
- Existing tests cover same-directory references and allowlist behavior at `tests/static/test_validate_iac_orphans.py:26-68`, but not duplicate basenames or `../shared/foo.yaml`.

Why this matters:

- A kustomization resource such as `../shared/foo.yaml` can incorrectly satisfy a local `foo.yaml`.
- Duplicate basenames across directories can hide real orphan manifests or flag the wrong target.

Acceptance criteria:

- Resolve each `resources:` entry relative to the kustomization directory.
- Compare normalized repo-root-relative paths, not basenames.
- Add tests for `../shared/foo.yaml`, duplicate basenames, and same-directory references.

### P2 - Gitleaks allowlist can hide plaintext secrets in `.sops.yaml` files

Files:

- `.gitleaks.toml`
- `tests/static/secret_scan.py`
- `.github/workflows/ci.yml`

Observed:

- `.gitleaks.toml:6-14` path-allowlists `clusters/.*\.sops\.ya?ml$` and `infra/.*\.sops\.ya?ml$`.
- `tests/static/secret_scan.py:8-19` has a small hand-rolled pattern set and does not cover many project-specific token formats such as Anthropic/OpenAI/OpenRouter/R2/VLESS/Codex/Claude OAuth-like values.
- CI runs both the custom scanner and gitleaks at `.github/workflows/ci.yml:30-44`, but gitleaks is configured to skip the exact files where operators are most likely to edit secret material.

Why this matters:

- A malformed SOPS file with plaintext `stringData` can pass gitleaks because the entire path is allowlisted.
- The custom scanner may still miss provider-specific tokens.

Acceptance criteria:

- Do not path-allowlist whole SOPS files for all gitleaks rules.
- Add a structural SOPS validation that ensures secret data values are encrypted `ENC[...]` where expected.
- Add project-specific token patterns to the custom scanner.
- Add fixture tests that prove a plaintext token inside a `.sops.yaml` file fails CI.

### P2 - HTTP `max_steps` is ignored in the default ReWOO path

Files:

- `hermes/hermes.py`
- `hermes/tests/test_hermes.py`

Observed:

- The HTTP handler parses `max_steps` at `hermes/hermes.py:669-679`.
- `run_agent` accepts `max_steps` at `hermes/hermes.py:590-595`.
- In default ReWOO mode, `run_agent` calls `run_rewoo(...)` without passing any cap derived from `max_steps`; `run_rewoo` uses its default `max_tools=8`.
- Existing unit tests cover ReAct `max_steps`, but do not assert default ReWOO honors the HTTP/user cap.

Why this matters:

- Clients and operators can believe they limited tool use for a request, but the default path can still execute up to 8 planned tools.
- This matters for cost, latency, and blast radius of tools such as HTTP and Kubernetes reads.

Acceptance criteria:

- Decide whether `max_steps` should cap ReWOO planned tools or introduce a separate `max_tools` request field.
- Enforce the selected cap in `run_agent`.
- Add a unit test where `max_steps=1` in default mode prevents execution of more than one planned tool.

### P2 - Summarizer prompt drops the explicit untrusted-tool-result boundary

Files:

- `hermes/hermes.py`

Observed:

- The main system prompt warns that tool results are untrusted at `hermes/hermes.py:447-449`.
- `_summarize` calls the model with a single user message only at `hermes/hermes.py:476-482`.
- The summarizer prompt says to answer using the data, but does not restate that fetched/logged/tool data is untrusted and must never be obeyed as instructions.

Why this matters:

- The summarizer is used after repeated tool calls, max steps, and ReWOO evidence collection.
- A malicious fetched page or log line can inject instructions into the exact evidence block passed to the final model call.
- The summarizer cannot call tools, but it can still produce an attacker-shaped final answer.

Acceptance criteria:

- Give `_summarize` its own system message that treats evidence as untrusted data.
- Delimit evidence clearly and require quoting/paraphrasing only from evidence.
- Add a unit test with a malicious tool result that tries to override the answer.

### P2 - GitHub/Flux bootstrap script still conflicts with the protected public-repo path

Files:

- `infra/ops/configure-github-flux.sh`

Observed:

- Default visibility is `private` at `infra/ops/configure-github-flux.sh:20-23`.
- The script pushes directly to the configured branch at `infra/ops/configure-github-flux.sh:52-56`.
- Optional `UAP_COMMIT_AND_PUSH=1` commits and pushes generated Flux sync files at `infra/ops/configure-github-flux.sh:94-102`.

Why this matters:

- The current repository policy is a public repo with protected `master` and required PR/static checks.
- Re-running this bootstrap path can fail unexpectedly or teach future agents the wrong deployment path.

Acceptance criteria:

- Make the default visibility and flow match ADR-026/current repo policy.
- Replace direct protected-branch push with a branch/PR instruction or explicit owner-approved bootstrap exception.
- Add a dry-run mode that prints the intended GitHub changes before making them.

### P2 - Hermes-agent runtime is installed at pod boot from floating package/image refs

Files:

- `clusters/prod/infra/hermes-agent.yaml`
- `clusters/prod/infra/hermes-agent-backup.yaml`

Observed:

- `hermes-agent` init and gateway containers use `nousresearch/hermes-agent:latest` at `clusters/prod/infra/hermes-agent.yaml:45-57` and `clusters/prod/infra/hermes-agent.yaml:103-106`.
- The init container installs `@openai/codex` and `@anthropic-ai/claude-code` with unpinned `npm i -g` at `clusters/prod/infra/hermes-agent.yaml:51-58`.
- Backup uses `nousresearch/hermes-agent:latest` and `rclone/rclone:latest` at `clusters/prod/infra/hermes-agent-backup.yaml:35-65`.

Why this matters:

- A pod recreate can change the coding runtime without any Git diff.
- Restore/debug behavior can differ from the behavior that was originally validated.

Acceptance criteria:

- Pin images by digest or document a temporary exception with a review date.
- Pin Codex and Claude Code CLI versions, or bake them into a controlled image.
- Add a runtime version smoke that records image digest and CLI versions without printing secrets.

### P3 - Live integration test still exercises ReAct instead of the default ReWOO entrypoint

Files:

- `hermes/tests/run_integration.py`
- `hermes/hermes.py`
- `hermes/README.md`

Observed:

- `hermes/README.md:28-31` says ReWOO is the default loop.
- `run_agent` implements that default at `hermes/hermes.py:590-595`.
- `hermes/tests/run_integration.py:57` still calls `hermes.run_react(...)` directly.

Why this matters:

- The live integration script can fail or pass based on the old loop, not the deployed default behavior.
- It can mislead future agents comparing "last run: 8/8" against the current ReWOO path.

Acceptance criteria:

- Make the integration test call `run_agent` by default.
- Keep an explicit `HERMES_AGENT_MODE=react` comparison path if the old mode remains useful.
- Update README wording after the test is aligned.

### P3 - Public `/tools` endpoint exposes tool inventory without auth

Files:

- `hermes/hermes.py`

Observed:

- `GET /tools` returns tool names and scopes before auth at `hermes/hermes.py:640-647`.

Why this matters:

- This is not a direct secret leak, but it exposes operational capabilities to anyone who can reach the NodePort/tailnet endpoint.
- It also ignores scoped-key visibility rules because no key is presented.

Acceptance criteria:

- Either require auth for `/tools`, or only return a minimal unauthenticated health-style response.
- If kept public, document why tool inventory disclosure is acceptable on the tailnet.

## Suggested Fix Order

1. Fix P1 source/ConfigMap drift and add CI sync check.
2. Fix P1 trace/log exposure before adding more read tools.
3. Fix P1 backup completeness validation before relying on DR claims.
4. Fix P2 gating false-greens in `verify-local`.
5. Fix P2 kustomization orphan logic and scanner coverage.
6. Fix P2 Hermes max-step/summarizer issues.
7. Align bootstrap/runtime pinning and integration-test defaults.

## Suggested Delegation

- Claude Code PR 1: `fix(hermes-deploy-sync)` - regenerate ConfigMap, update hash, add sync check.
- Claude Code PR 2: `fix(hermes-trace-redaction)` - gate/redact `hermes_trace`, narrow `kube_logs`.
- Claude Code PR 3: `fix(validation-gates)` - strict readiness/ops mode, kustomization path fix, scanner fixtures.
- Claude Code PR 4: `fix(hermes-agent-dr)` - backup manifest validation and restore check plan.
- Claude Code PR 5: `chore(runtime-pinning)` - image/CLI pins and version smoke.

