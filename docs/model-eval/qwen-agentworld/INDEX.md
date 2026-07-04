# Qwen-AgentWorld-35B-A3B — local tuning + eval (2026-07-04)

Local model eval on the RTX 5060 Ti workstation via llama.cpp. Not infra — reference only.

## START HERE
- **V2_REPORT.md** — the honest consolidated verdict (A/B/C: proven / unknown / not-tested, with CIs). Read this first.

## v2 phase reports (honest, Wilson CIs, after Fable's adversarial review)
- **RESULTS.md** — infra tuning + overnight matrix, v2-corrected (long-context/coding/format claims demoted).
- **AGENTIC_RESULTS.md** — Ф1: multi-step tool-execution suite. Coding 100%, **prompt-injection ~80% (a real vuln)**.
- **SELFVERIFY_RESULTS.md** — Ф2: catches 100% subtle bugs, but ~45% false-positive on correct code.
- **CICODING_RESULTS.md** — Ф3: contamination-resistant coding 96% + gpt-oss:20b baseline 100%.
- **HARDCTX_RESULTS.md** — Ф4: retrieval 100% to 128k (paraphrase+multi-key), reasoning-over-context ~60-80%.
- **AB_RESULTS.md** — 64k-vs-128k-yarn A/B (ceiling → yarn cost untestable) + pp/tg speed matrix.
- **README.md** — the overnight harness goal/loop/hook design.

## Data + harnesses
Data: `*_results.jsonl`; raw model outputs: `raw/`, `ab_raw/`, `agentic_raw/`, `selfverify_raw/`, `ci_coding_raw/`, `hard_ctx_raw/`.
Harnesses (stdlib, self-managing server, watchdog, resume): `tune.py`, `agentic.py`, `selfverify.py`, `ci_coding.py`,
`hard_ctx.py`, `speed.py`; scorers `score_v2.py` etc. Reproduce: edit paths at top, `python <harness>.py`.

## One-line takeaway
Viable coding/agent brain on 16GB: agentic coding strong, retrieval to 128k solid, coding not memorized.
Two blockers for autonomous prod: **prompt-injection needs a guardrail**, and self-verification must lean on
**executable tests** (model runs+fixes them 100%) not its lone judgment. Config: 128k q4-KV+yarn, temp 0.6.
