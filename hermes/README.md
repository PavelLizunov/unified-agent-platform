# Hermes — the agent orchestrator (DEPLOYED)

Hermes is UAP's **agent/orchestration layer**: it turns the plain chat backend (LiteLLM → subfleet →
Claude) into a tool-using agent. It is the "agent" in unified-**agent**-platform.

## Live

- Code: `hermes.py` — a single-file **stdlib-only** service, deployed on a stock `python:3.11-slim`
  with the code mounted from the `hermes-code` ConfigMap (no image build, no pip — RU-egress safe).
- In-cluster: `hermes.uap-system.svc:8900`. Over the tailnet: **`http://<node-tailnet-ip>:30890`**
  (NodePort; WireGuard-encrypted, `HERMES_KEY` auth). E.g. `http://uap-home-1.tail9fd337.ts.net:30890`.
  (tailscale-serve can't proxy to the ClusterIP — the cluster net itself runs on tailscale, ADR-021 —
  so NodePort is used; see the Service note in `clusters/prod/infra/hermes.yaml`.)
- Auth key: `kubectl -n uap-system get secret hermes-keys -o jsonpath='{.data.HERMES_KEY}' | base64 -d`
- OpenAI-compatible: `POST /v1/chat/completions` runs a tool-using ReAct loop and returns the final
  answer (plus a `hermes_trace`). Also `GET /healthz`, `GET /tools`, and slash commands (`/help`,
  `/tools`, `/model`) handled locally.

## Why prompt-based ReAct (not native function-calling)

subfleet's bridge spawns the bundled `claude` CLI, a monolithic agentic loop that executes tools
itself and does NOT surface `tool_use` to the caller — so native OpenAI `tools`/`tool_calls` through
the bridge is infeasible (the CLI is frozen at 2.1.90; newer = 403). Decision: **prompt-based ReAct at
the Hermes layer, zero subfleet change.** Hermes owns the tool registry, the loop, and tool execution.

## How it works

Default loop is **ReWOO plan-then-execute** (`run_rewoo`): a planner lists every needed tool call
upfront → a worker executes them all → a solver answers from the gathered evidence with NO tool
affordance. This is the research-backed fix for tool-result faithfulness + multi-tool chaining (see
Reliability below); it is the default. `HERMES_AGENT_MODE=react` switches to the interleaved ReAct loop
(also the fallback for a malformed plan). Tools are invoked by the model emitting a fenced JSON
`tool_call`; Hermes executes them out-of-band and treats every `tool_result` as UNTRUSTED data. Effort
routes to the `-think` model group (LiteLLM rejects a client-sent `reasoning_effort`).

## Tools (each carries a scope: compute | read | net)

- `calc` (compute) — arithmetic via an AST sandbox (no `eval`; magnitude/length caps).
- `now` (compute) — current UTC.
- `http_get` / `http_post` (net) — GET/POST a public URL, **SSRF-guarded** (blocks private/internal
  IPs incl. on every redirect hop).
- `kube_pods` / `kube_get` / `kube_logs` (read) — read-only cluster inspection via the in-cluster k8s
  API (ServiceAccount `hermes` + a get/list-only ClusterRole on pods, pods/log, services, events,
  deployments, nodes, namespaces). `kube_get` lists pods|services|events|deployments|nodes|namespaces.

## Authorization (per-tool scopes)

`HERMES_KEY` grants ALL scopes. `HERMES_KEYS_JSON` (a SOPS secret value, e.g. `{"<key>":["compute","read"]}`)
defines scoped keys: a key only SEES (in the system prompt) and can only CALL tools whose scope it holds —
e.g. a read-only key gets calc/now + the kube_* tools but is blocked from http_get/http_post. A deployed
read-only key exists for safe inspection. Unknown bearer → 401; out-of-scope tool call → authz error.

## Hardening (from the multi-agent code review)

Bounded thread pool, per-connection socket timeout, request body-size cap, SSRF-revalidating
redirects, constant-time auth that **fails closed** unless `HERMES_DEVMODE=1`, upstream retry +
error sanitisation (no key leak), step/conversation caps, graceful shutdown, stderr request logging.

## Tests

- `tests/test_hermes.py` — 41 unit tests (parser, calc sandbox, SSRF guard, ReAct + ReWOO loops,
  per-tool authz/scopes, tools, slash, registry). `python3 -m unittest -v`.
- `tests/run_integration.py` — live scenarios against the gateway (tool use, no-tool, model variants,
  effort, injection resistance). Needs `LITELLM_BASE`/`LITELLM_KEY` (+ `HERMES_DEVMODE=1`). Last run: 8/8.
- `tests/reliability.py` — measures how faithfully the MODEL reads/uses what Hermes feeds it: N trials
  per scenario vs the live model. `HERMES_TEST_MODEL` and `HERMES_AGENT_MODE` let you compare models and
  loops. This is the agent's behavioral characterisation (see Reliability).

## Reliability (measured)

The harness surfaced two real, named failure modes under plain interleaved ReAct — *tool-result
faithfulness* (the model calls `calc`, gets the right value, then states its OWN wrong number) and
*multi-tool chaining* (calls one tool, hallucinates the second). The research-backed fix, **ReWOO
plan-then-execute** (now the default loop), resolves both: the plan forces every tool to run, and the
solver answers from evidence with no tool affordance so it can't re-guess. Measured on Opus over a
representative run (9 scenarios × 20 trials = 180):

| scenario | ReAct | **ReWOO** |
|---|---|---|
| count / list / deployments / nodes / recall / http_fetch | mixed (1–20/20) | **20/20 each** |
| multi-tool **chaining** (time+count, 3-facts) | 0–1/20 | **20/20** |
| arithmetic **faithfulness** | 0/20 | **20/20** |
| **overall (180 trials)** | 84/180 (47%) | **180/180 (100%)** |

**Model choice:** Opus (`smart-cloud`) is the most reliable — a comparison run gave Opus 47% vs Sonnet
40% vs **Haiku 0%** under ReAct. The weakness was the *technique*, not the model (constrained-decoding /
grammars need token-logit access Claude doesn't expose; "a flagship is worse at faithfulness" was
refuted in the literature — larger instruction-tuned models follow grounding prompts *better*). The
failure modes are studied 2026 phenomena ("artifact-faithfulness" / "Tool Ignored").

## Deploy / iterate

Code lives in `hermes/hermes.py`; the deploy ConfigMap is generated from it and the Deployment's
`hermes/code-rev` annotation is set to the file hash (so a code change rolls the pod):

```bash
H=$(sha256sum hermes/hermes.py | cut -c1-12)
kubectl create configmap hermes-code -n uap-system --from-file=hermes.py=hermes/hermes.py --dry-run=client -o yaml > clusters/prod/infra/hermes-code-configmap.yaml
sed -i "s|hermes/code-rev: .*|hermes/code-rev: \"$H\"|" clusters/prod/infra/hermes.yaml
# commit -> Flux rolls it
```

## Next (not built)

More tools (HTTP POST, k8s logs/events read, retrieval/RAG) in the sandboxed registry; a chat UI;
per-tool authz; a scoped LiteLLM key for Hermes instead of the master key.
