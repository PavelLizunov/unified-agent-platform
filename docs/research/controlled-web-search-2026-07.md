# Controlled web research — provider/harness decision (2026-07-20)

## Product contract checked

Required path:

`owner research goal -> separate task/session -> allowlisted search capability -> bounded normalized result -> Central session -> Workspace/Telegram`

This is not the Codex in-app Browser and it does not grant shell/network access to build-1 coding workers. Search
content is external untrusted data, never system/owner instructions. The result contract is bounded to a summary plus
1..8 unique HTTPS citations (`url`, `title`, `snippet`, nullable `source_time`) and a retrieval timestamp.

## Reusable mechanisms found

1. **Codex native web search (selected).** Codex can enable its native `web_search` tool separately from command
   network access. The pinned `@openai/codex@0.142.0` supports the global `--search` flag plus `exec --ephemeral`,
   `--ignore-user-config`, `--sandbox read-only`, `--output-schema`, and `--output-last-message`. This gives a separate
   bounded research process without a new provider key or service.
2. **Pinned Hermes native provider interface (not selected for durable results).** The exact deployed upstream tag
   `v2026.7.1`, commit `7c1a029553d87c43ecff8a3821336bc95872213b`, already ships
   `plugins/web/brave_free/provider.py`, `web.search_backend: brave-free`, and `BRAVE_SEARCH_API_KEY`. Its public tool
   allows up to 100 results and the provider discards Brave `age`, has one 15-second attempt, and flattens provider
   errors. A UAP facade would still be needed for the requested contract.
3. **Legacy build-1 `ai-search` (kept only as an engineering CLI).** `tools/websearch/ai_search.py` provides
   Exa/Brave/Tavily/DDG auto-fallback and page fetch. It is not a deterministic research-session boundary: provider
   fallback is implicit, query/result validation is incomplete, page fetch can follow arbitrary URLs, errors are not
   typed, and its key file is readable in the same build-1 authority as coding workers.

## Brave Search API fact-check

- Endpoint: `GET https://api.search.brave.com/res/v1/web/search`; auth header: `X-Subscription-Token`.
- Web `count` accepts 1..20. Results expose title, URL, description and may expose `age`.
- Rate limiting uses a one-second sliding window. `429` responses and `X-RateLimit-*` headers distinguish throttling;
  retry/backoff should be conservative.
- Current Search pricing is $5 per 1,000 requests with a recurring $5 monthly credit. Price is not an approval gate.
- The Search API Terms last updated 2026-02-11 prohibit storing/caching Search Results beyond transient operational
  storage and prohibit derivative works of Search Results. A normal UAP Central result is deliberately durable, so a
  default Brave subscription cannot honestly back the required durable citation path. An Order Form can change the
  governing terms; no such authority or key exists in the repository.

Official sources:

- https://api-dashboard.search.brave.com/documentation/guides/authentication
- https://api-dashboard.search.brave.com/api-reference/web/search/get
- https://api-dashboard.search.brave.com/documentation/guides/rate-limiting
- https://api-dashboard.search.brave.com/documentation/pricing
- https://api-dashboard.search.brave.com/documentation/resources/terms-of-service
- https://hermes-agent.nousresearch.com/docs/user-guide/features/web-search
- https://hermes-agent.nousresearch.com/docs/developer-guide/web-search-provider-plugin
- https://developers.openai.com/codex/security

## Selected implementation

`research_session` is added to the existing Central `build1` MCP server, but it does not use build-1. It starts the
already installed Codex binary inside the Hermes pod with only native search enabled for the child run. The facade:

- validates a 1..2,000-character goal, at most eight public DNS allowlist entries, and 1..8 sources;
- uses a generated JSON Schema and independently revalidates the final result, HTTPS scheme, public hostname,
  optional domain suffix allowlist, unique URLs and string bounds;
- disables Codex's `shell_tool`, passes only `PATH` and proxy variables, and creates an ephemeral HOME/CODEX_HOME
  containing only the existing Codex auth; it neither prints nor persists raw auth;
- records deterministic `request_id`, running attempt and terminal normalized result atomically under
  `/opt/data/research-sessions`; a repeated successful request replays the same result without another search;
- retries once after one second only for timeout/connection/429/502/503/504/invalid-response classes;
- returns typed `rate_limited`, `quota_exhausted`, `credential_unavailable`, `upstream_unavailable`,
  `invalid_response`, or `invalid_request` errors without raw stderr and without asking the owner about transient
  failures.

The parent Central Hermes session persists the normalized tool result and returns it through its originating channel.
Workspace and Telegram can invoke the same deterministic request id and receive the same persisted result; this does
not claim full cross-channel transcript mirroring. No new workflow engine, dashboard, service, key, SOPS object, or
coding-worker network permission is introduced.

## Canary

After Flux deploys the merge, invoke `research_session` from a fresh Central session with a harmless primary-source
goal, an exact domain allowlist, and `max_sources=2`. Pass criteria:

1. tool result is `status=complete`, `provider=codex-native-web-search`, and
   `trust=untrusted_external_content`;
2. 1..2 unique citations are HTTPS and remain inside the requested domain;
3. the same call returns the same `request_id` and persisted result without a second child attempt;
4. the exact same request from Workspace and Telegram returns the same request id and cited result in each channel.

There is no owner setup for the selected path. A future Brave experiment must first supply both a SOPS-managed key
and explicit retention authority; the key alone is insufficient.
