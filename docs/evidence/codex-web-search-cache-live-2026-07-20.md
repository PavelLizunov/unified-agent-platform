# Codex web-search cache/live research attempt — 2026-07-20

## Requested research

The owner asked one bounded `research_session` call to answer when current OpenAI Codex documentation describes web
search as cached versus live. The call used the exact goal text, `domains=["developers.openai.com"]`, and
`max_sources=2`.

## Terminal result

- request id: `research-28f841738aa517ae8e8825aa`
- status: `error`
- error: `research_failed`
- retryable: `false`
- returned trust marker: none
- returned citation URLs: none

The tool did not produce a normalized research result, so the successful-result trust marker
`untrusted_external_content` and citation URLs cannot honestly be attributed to this request. No second
`research_session` call was made.

## Locally corroborated behavior

The installed `codex-cli 0.144.6` help identifies `--search` as enabling **live** native Responses `web_search`.
Current Codex documentation describes the normal restricted mode as using cached search and live search as the mode
selected by `--search` or `web_search = "live"`; full network access also defaults search to live. These official
documentation targets are recorded for a future successful bounded retry, not represented as citations returned by
the failed call:

- https://developers.openai.com/codex/security
- https://developers.openai.com/codex/config-reference
