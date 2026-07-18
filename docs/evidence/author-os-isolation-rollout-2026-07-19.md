# Author OS isolation rollout — 2026-07-19

## Scope

This record covers the author half of the existing model-process boundary on build-1. The coordinator now launches
both OpenAI actors through the same parent-bound user-systemd namespace. Reviewer remains exact-SHA read-only; author
receives one additional writable path, its deterministic disposable worktree. No new service, provider, dependency or
model route was added.

This is controlled component evidence. It proves one real Sol author can run through the installed boundary and pass
the existing runtime attestation. It is not an ordinary owner mission, PR/CI/merge campaign, hostile same-UID proof or
generic coverage for credential locations outside the enumerated host paths.

## Git and required CI

```text
PR                         #279
author head                cacd3a664a5bac80f1c908df51b92feea6245b6b
squash merge               fd5199d32161c09dca181bd1471715c2df92af4f
required CI run            29663646121
static-checks               success
```

Before merge:

- Windows coordinator suite: 121/121;
- Windows static discovery: 187 tests, one skip;
- `tests/verify-local.ps1`: `verify-local-ok`, including live cluster smoke;
- Linux static discovery: 187/187;
- Linux secret scan, Python bytecode compilation and `git diff --check`: passed;
- exact candidate namespace preflight: `author-isolation-exact-properties-preflight-ok`.

## Boundary

The installed coordinator uses its durable attempt ID to name a transient `uap-author-*` unit and binds that child to
the active `hermes-delivery-coordinator@<profile>.service`. The child keeps the existing exact route, prompt, Codex
runtime attestation and capacity semantics while applying:

- `PrivateUsers=true`;
- `ProtectSystem=strict` and `ProtectHome=read-only`;
- explicit read-only source checkout, complete worktree root and mission-state directory;
- explicit writable author worktree, mission-local model home and configured Codex home;
- `ProtectProc=invisible`, `ProcSubset=pid` and `PrivateTmp=true`;
- inaccessible common credential stores and user runtime;
- removal of inherited control-plane and credential environment names;
- `NoNewPrivileges`, `RestrictSUIDSGID`, `LockPersonality`, bounded runtime and parent `BindsTo`.

The raw last-message path moved under the already allowed mission-local model home. The systemd launcher receives only
the user-bus variables; model environment values are installed inside the child unit.

## Exact build-1 rollout

All five coordinator timers were stopped during installation. Installer `install` and `--check` returned
`hermes-flow-v2-install-ok`; the installed coordinator suite passed 121/121 and `systemd-analyze --user verify` passed.

```text
de7a405331edca402957d82301610adfee623446634ba1e502b59b30e684eb99  merge/tools/swarm/delivery_coordinator.py
de7a405331edca402957d82301610adfee623446634ba1e502b59b30e684eb99  /home/uap/swarm-bin/delivery_coordinator.py
```

The installed-code adversarial probe repeated the exact author write, credential, `/proc`, user-runtime and output
assertions and printed `installed-exact-author-wrapper-probe-ok`. It allowed writes only to the author worktree,
mission-local model home and Codex home, and denied the tested source/worktree-root/state writes and credential/runtime
reads.

After daemon reload all five standing timers were active. Natural registered-profile ticks returned `null` with
systemd result `success`; no manual coordinator tick was invoked.

## Real OpenAI actor proof

A disposable Git repository under `/home/uap` contained one tracked `result.txt`. The installed coordinator helper
constructed the author wrapper. Only the `BindsTo` target was changed from the production coordinator instance to a
disposable sleeping parent unit so the actor could be exercised without fabricating a Central mission. All namespace,
path, environment, model and Codex command properties remained those produced by the installed implementation.

The exact prompt allowed only replacing `result.txt`. The actor changed that file and no other path, the probe committed
the result, then the normal rollout parser attested the completed turn:

```text
token               installed-real-author-isolation-probe-ok
model               gpt-5.6-sol
model provider      openai
reasoning effort    xhigh
sandbox             workspace-write
session             019f7767-e892-78e0-a466-03a198116fe6
candidate SHA       77078ce9de350e0769262030b8f4ad635b11e016
worktree clean      true
```

The disposable parent and repository were removed after the assertion. The first real probe had already produced the
correct single-file change but its harness stripped the porcelain status before comparing it with a leading-space
expectation; the corrected assertion above passed. That was a probe defect, not a coordinator or actor failure.

## Proven boundary and remaining gate

The merged and installed coordinator can run a real runtime-attested Sol author inside the enforced namespace while
preserving the intended writable disposable worktree. Together with the prior live Terra reviewer evidence, both model
roles now have installed real-actor proof.

Still unproved here: an ordinary owner mission whose author and reviewer both execute through this exact installed
revision, protection from a hostile process running as the same host UID, all possible secret stores, and a platform-
wide kernel prohibition on local/GPU/non-OpenAI processes.
