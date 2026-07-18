# Ordinary bound Telegram answer rollout — 2026-07-18

## Scope and verdict

PR [#264](https://github.com/PavelLizunov/unified-agent-platform/pull/264) deployed the ordinary-owner-turn router into
Central Hermes. A normal Telegram turn from the chat/topic bound to a `waiting_owner` mission now records the exact
open `mission.question` answer instead of accepting another mission. The source Telegram message identity is durable:
same-text replay after restart returns the stored answer, changed-text replay fails closed, and a delayed replay after
the chat has moved to a later mission cannot steal the binding or create a goal.

**Verdict:** code, CI, Flux rollout, installed hashes, health and an in-pod temporary-store component scenario pass.
This is not yet a live owner-channel acceptance canary: no real Telegram-origin mission has produced and answered an
open question on this rollout.

## Immutable delivery identity

- author head: `337a20ee0887432b8954d27b833cb19b06012240`;
- required `static-checks`: GitHub Actions run
  [29655511819](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29655511819), `success`;
- squash merge: `4cd2c60f9d9f6c2c8e0d0612ef5d31eee88fbaaf`, merged at `2026-07-18T18:16:13Z`;
- final local static gate: `verify-local-ok`;
- Linux Python CI-equivalent: 20 commands passed;
- exact pinned Hermes overlay passed after updating only the two changed output fingerprints;
- the final runtime regression and generated ConfigMap drift check passed after synchronization.

The added regression exercises goal acceptance, producer question, ordinary Telegram answer, SQLite reopen, exact
replay, changed-payload rejection, a later goal/rebind and delayed replay of the earlier answer.

## Flux and runtime attestation

Both Flux objects reported `Ready=True` at the merge revision:

```text
GitRepository/uap-platform master@sha1:4cd2c60f9d9f6c2c8e0d0612ef5d31eee88fbaaf
Kustomization/uap-platform Applied revision: master@sha1:4cd2c60f9d9f6c2c8e0d0612ef5d31eee88fbaaf
```

The ConfigMap-safe pod-template revision is `v46-ordinary-owner-answer`. Pod
`hermes-agent-b589c975c-hddmf` was created at `2026-07-18T18:16:51Z`, became Ready with zero restarts, and returned
HTTP `200` from the in-pod API health endpoint.

Installed file hashes:

```text
4fd0d038ad88a6e4c2c1d22b5c2322a1d408eb535d3debe0688b5167395c0cbb  hermes_cli/uap_missions.py
e30907ecce05f268773f24263b69de5c07865b5805f4bf6256bd0d0e5f000716  gateway/run.py
866b570a1f63bf10612f67f2e120e2a0694adc6663be7beb4c9d43fcf6cff179  gateway/platforms/api_server.py
```

The installed mission runtime hash equals the exact merged source hash. The two Hermes file hashes equal the
repo-owned patched fingerprints.

## Live component check

An in-pod check used a temporary SQLite database and the deployed server-owned Telegram route. It performed:

```text
ordinary goal → bound mission → producer question → ordinary owner turn
→ mission.answer → MissionStore restart → same event replay
```

It returned `live-owner-answer-component-ok`. The production mission database was not mutated by this check.

## Automation boundary retained

The registered build-1 user timer `hermes-delivery-coordinator@flow-pilot-registered-v4.timer` remained active. Its
natural ticks returned `null`; no manual `accept`, `poll`, `tick`, coordinator or completion call was used. At the
checkpoint, the controlled capacity marker was still pending and the newest Central owner mission remained the
completed Workspace mission accepted at `2026-07-18T15:45:31.568Z`.

Still required for a live product claim:

1. an ordinary Telegram goal creates the registered mission;
2. that mission durably reaches `waiting_owner` with one canonical question;
3. the owner's next ordinary Telegram message records one answer under the same `mission_id`;
4. the standing timer resumes the same native task/run without manual delivery commands;
5. Workspace observes the same ordered question/answer events after cursor replay.

Complete Workspace/Telegram transcript synchronization remains outside this rollout.
