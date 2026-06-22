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

The model is told to emit ONLY a fenced ```tool_call``` block to call a tool; Hermes parses it,
executes the tool out-of-band, feeds back a ```tool_result``` (untrusted data), and loops until the
model answers in prose. Effort routes to the `-think` model group (LiteLLM rejects a client-sent
`reasoning_effort`). Repeated identical calls are force-converged (the model is told to answer now),
so the loop never hangs.

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

- `tests/test_hermes.py` — 26 unit tests (parser, calc sandbox, SSRF guard, ReAct loop incl. dedup/
  force-final, slash, registry). Run: `cd hermes && python3 -m unittest -v`.
- `tests/run_integration.py` — live scenarios against the gateway (tool use, no-tool, model variants,
  effort, injection resistance). Needs `LITELLM_BASE`/`LITELLM_KEY` (+ `HERMES_DEVMODE=1` for the local
  kubectl fallback). Last run: 8/8.

## Known limitation

Prompt-based ReAct tool-compliance is **probabilistic**: the model usually calls tools correctly, but
on some tasks (e.g. "count and reply with only the number") it may skip a tool, miscount, or loop.
Hermes guarantees convergence (no infinite loops) and the tools/infra are deterministic, but final
answer quality on adversarial-terse tasks varies. Native function-calling would fix this but is
infeasible through the subscription CLI (see above). Mitigations in place: firm system prompt,
identical-call dedup + forced final answer.

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
