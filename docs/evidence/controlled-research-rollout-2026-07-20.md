# Controlled research rollout evidence — 2026-07-20

## Shipped source

- PR: https://github.com/PavelLizunov/unified-agent-platform/pull/323
- merge: `d0ebec79ff1a5c14e2b0f3c003f6a9170fbe5363`
- required `static-checks`: passed
- Flux applied the exact merge; `hermes-agent` rolled to `v63-controlled-research`, Ready `1/1`, zero restarts.

The installed MCP server exposed `research_session`. A live bounded query against `developers.openai.com` returned
request `research-af128127b03f512c37402af9`, `status=complete`, `provider=codex-native-web-search`,
`trust=untrusted_external_content`, and two allowlisted HTTPS citations. The exact repeat returned the same request id,
timestamps and result without another child search. A Central `hermes chat` turn then called the MCP tool exactly once
and returned the same request id/trust marker/citation URLs.

## Canary incident and containment

A later build-1 HTTP projection probe quoted `curl --noproxy '*'` incorrectly. The remote shell expanded `*`, and a
process-list diagnostic exposed the Central API bearer value in the diagnostic transcript. The process terminated;
the value is treated as compromised and is not reproduced here.

Containment is a full SOPS credential rotation plus pod rollout (`v65-api-credential-rotation`) and atomic replacement
of the protected Workspace/coordinator runtime copies. Rotation is complete only after the old token is rejected, the
new token reaches `/v1/models`, Workspace is healthy, and the securely staged one-time plaintext file is removed.

The direct module canary initially created its state as root because `kubectl exec` defaults to the container user.
That diagnostic-owned directory was corrected to gateway uid/gid `10000`; the subsequent real MCP call succeeded.
Future canaries must exercise the MCP/session path first and must not invoke the state writer as root.

## Honest boundary

The installed native search, durable replay and Central MCP path are proven. Workspace/Telegram UI delivery is not yet
claimed by this evidence; it remains the final post-rotation canary in `runbooks/controlled-research.md`.
