# Bounded adapter terminal-log rollout — 2026-07-19

## Scope

This record closes the adapter failure where a native Kanban log larger than 1 MiB could make mission reconciliation
fail forever. The merged implementation projects a deterministic source tail, preserves every previously committable
line event identity, replaces a single over-limit line with one redacted placeholder, and never splits a possible
secret across independently redacted producer events.

## Immutable Git and CI identity

- Pull request: <https://github.com/PavelLizunov/unified-agent-platform/pull/289>
- Base: `03d696b0bd6161e165b4a34b88a8d0e9991c8317`
- Reviewed candidate: `fd78226933d4cde62d5db86fe1790c83520f9f1f`
- Merge commit: `951ee7bc0db9a88805a2dbec20b73f1e68f6d828`
- Required `static-checks`: run `29677799988`, job `88168348794`, conclusion `success`

The candidate passed `29` focused adapter tests (`1` platform skip), `git diff --check`, and the complete Windows
validation gate with terminal token `verify-local-ok`.

## Independent exact-SHA review

The final reviewer ran in a clean detached checkout at the reviewed candidate SHA.

- Codex session: `019f7940-6823-7c11-b46d-fca2d26ae30a`
- Runtime provider: `openai`
- Runtime model: `gpt-5.6-terra`
- Reasoning effort: `xhigh`
- Sandbox: `read-only`
- Checkout after review: clean

The initial verdict identified dropped whitespace-only events as a possible compatibility issue. Reassessment against
the closed Central validator proved that such an event was never committable: Central rejects a whitespace-only
`payload.text` with `MissionError("invalid payload.text")`. The same persisted reviewer then returned:

> REVISED PASS — Central rejects blank `payload.text`, so no committable legacy event/ID exists. HEAD correctly omits
> it while counting its bytes in the 1 MiB tail; valid emitted events remain size-compatible and deterministic.

The review comment is preserved on PR #289.

## Build-1 rollout

The six delivery timers were stopped only for the bounded installer transaction. The existing Flow v2 installer was
run from the clean reviewed tree, followed by its check mode and systemd unit verification:

```text
hermes-flow-v2-install-ok
hermes-flow-v2-install-ok
source mission_adapter.py sha256    7fc659ac774019efa20135b417e8d943e896d6b8e16a793125986c64761ed7c5
installed mission_adapter.py sha256 7fc659ac774019efa20135b417e8d943e896d6b8e16a793125986c64761ed7c5
systemd-analyze --user verify       exit 0
```

All six pre-existing timers were restored as both `enabled` and `active`:

- `flow-pilot-a7-3k`
- `flow-pilot-a7-3l`
- `flow-pilot-owner-gate-v4`
- `flow-pilot-registered-v4`
- `vpnrouter-a7-3i`
- `vpnrouter-a7-3j`

After installation, every corresponding natural oneshot invocation reported `Result=success`, `ExecMainStatus=0`,
and `ActiveState=inactive`; `systemctl --user --failed` was empty.

## Claim boundary

This proves exact reviewed code installation, regression coverage, and idle production timer compatibility. It does not
claim that a live mission naturally produced a greater-than-1-MiB Kanban log. The oversized-log and replay boundaries
are hermetic/fault tests; the live rollout proof is fail-closed installation plus successful natural coordinator ticks.
