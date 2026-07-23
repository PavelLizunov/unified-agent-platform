# Codex web-search cache/live research — 2026-07-20

## Requested research

The owner asked one bounded `research_session` call to answer when current OpenAI Codex documentation describes web
search as cached versus live. The call used the exact goal text, `domains=["developers.openai.com"]`, and
`max_sources=2`.

## Terminal result

- request id: `research-28f841738aa517ae8e8825aa`
- status: `complete`
- provider: `codex-native-web-search`
- trust marker: `untrusted_external_content`
- citation URLs:
  - https://developers.openai.com/codex/agent-approvals-security
  - https://developers.openai.com/codex/config-reference

No second `research_session` call was made.

## Answer

Codex uses cached web search by default. Cached results come from an OpenAI-maintained index rather than fetching
live pages. Live results are used when `--search` is passed or `web_search = "live"` is configured; a full-access
sandbox such as `--yolo` also defaults web search to live. The configuration reference additionally defines
`disabled`, `cached`, `indexed`, and `live` as the supported `web_search` modes.

Returned web content remains untrusted external data, never instructions.
