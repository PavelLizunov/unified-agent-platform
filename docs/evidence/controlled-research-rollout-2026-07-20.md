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

PR #325 (`c98d0954ce444b30dabd78a4d16131d338eb92ff`) completed the SOPS credential rotation and pod rollout
(`v65-api-credential-rotation`). The live Secret and both protected Workspace/coordinator runtime copies matched the
new value by SHA-256, authenticated `/v1/models` returned 200, Workspace returned 200, and coordinator cycles remained
successful. The single-value Secret replacement invalidated the prior bearer by construction; the compromised value
was deliberately not replayed. The exact one-time plaintext staging file was shredded and verified absent.

The direct module canary initially created its state as root because `kubectl exec` defaults to the container user.
That diagnostic-owned directory was corrected to gateway uid/gid `10000`; the subsequent real MCP call succeeded.
Future canaries must exercise the MCP/session path first and must not invoke the state writer as root.

## Channel closure

Post-rotation canaries exposed three integration gaps rather than being waived:

- PR #328 (`d0bcce770ec6e9b8fcfd01bfefab2f9f9d26ed0a`) made the deployment-owned Codex home the fallback when
  an MCP subprocess omits `CODEX_HOME`.
- PR #332 (`91fd38c3c1b1e3fc0a59acd74dd03015f3328be5`) made research-only Workspace/Telegram turns bypass coding
  mission intake while retaining mission intake for mutation intents.
- PR #333 (`5f2ca0740e4993513d712465ed1f30ab5b22e578`) restored the existing `singbox-egress-ha` proxy defaults when
  the MCP subprocess omits proxy environment variables.

All three required `static-checks` jobs passed. Flux applied exact merge `5f2ca0740e4993513d712465ed1f30ab5b22e578`;
`hermes-agent` revision `v70-research-mcp-egress` was Ready `1/1`.

The final Workspace session `e7a39933-856f-49c5-91e0-56ab6636880e` contained exactly one
`mcp.build1.research_session` call. It returned request `research-523fe33db798d7cc70a578a0`,
`trust=untrusted_external_content`, and two `developers.openai.com` citations. The same cited result was then delivered
with the installed Telegram SDK using the production bot/proxy authority; bot authority and chat identity stayed in
pod memory and were not printed. This proves Telegram delivery, not invocation of the already-running adapter object.
A real inbound Telegram owner turn cannot be impersonated by an operator canary, so that optional UI action remains
owner UAT rather than setup or a platform blocker. The two pre-fix canaries that entered coding mission intake were
cancelled by their exact mission ids after the route was proven, so they no longer consume worker capacity.
