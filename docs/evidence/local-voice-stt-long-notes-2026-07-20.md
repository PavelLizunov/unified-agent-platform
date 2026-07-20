# Long Telegram voice-note STT rollout evidence — 2026-07-20

## Verdict

**PASS.** The former 25-second ingress limit is removed without changing the selected model or adding VAD, a
service, a GPU dependency in k3s or an external STT API. Hermes safe-decodes once, sends sequential 20-second PCM
chunks to the existing M4 Metal worker, joins the normalized text and enters the existing ordinary owner-intake
path. STT remains deterministic media preprocessing with no author, reviewer, tool, project or routing authority.

## Git, CI and deployment identity

- implementation PR: <https://github.com/PavelLizunov/unified-agent-platform/pull/343>
- final PR head: `58ded911dfa44e141ec7decf9833aafff554ce8d`
- required `static-checks`: run `29750121083`, job `88378097699`, passed in 55 seconds
- squash merge: `9a50a3d6b2ecc8a3df9ab156649b577a27bf53fa`
- Flux `GitRepository/uap-platform` and `Kustomization/uap-platform`: Ready at that exact merge
- workload: `hermes-agent-744755dbf7-279hl`, `config-rev=v73-long-voice-stt`, Ready `1/1`, zero restarts

`tests/verify-local.ps1` completed with `secret-scan-ok`, `iac-static-ok` and `verify-local-ok`. The runnable POSIX
component `tools/hermes-mission/test_local_stt.py` passed on ops-1. It models a 65-second decode, verifies request
sizes `640000, 640000, 640000, 160000`, joined text, one Central mission on stable-source replay, short-note CPU
fallback, symlink rejection and zero mission state for an over-ceiling input. The Central runtime and deployment
fixtures also passed.

## Live Russian canary

An ephemeral 99.832517-second Russian AIFF note was generated on the always-on Mac and passed through the mounted
production `/opt/uap-stt/local_stt.py`, the ops-1 router and the live Metal CTC worker. The isolated transcription
call completed in 5.168 seconds (RTF 0.052) and returned 1,722 Unicode characters with SHA-256
`cdb66c6f6f732b56714c4d653107a09caa1fa6ef23fe257899b8215a05da1418`.

The redacted transcript then entered the live Central store with a stable Telegram source identity:

```json
{"accepted_events":1,"chars":1722,"created":true,"mission_id":"mission-intake-78e9a42790ab9299087baa5c689a2894","replay_created":false,"replay_same_mission":true,"status_after_cleanup":"cancelled","transcript_sha256":"cdb66c6f6f732b56714c4d653107a09caa1fa6ef23fe257899b8215a05da1418"}
```

The canary supplied the server-owned `uap` project ID; STT did not choose it. An initial invocation used the
repository slug instead of the catalog ID and failed before mission creation; its selection draft was explicitly
cancelled. The successful mission was terminally cancelled immediately after replay, before execution. All audio,
transcript and canary-script files were removed from the Mac, ops-1 and pod. No audio or transcript content was
written to git, evidence or service logs.

## Production resource boundary

- input: regular non-symlink file, allowed suffix/container, at most 8 MiB;
- duration: 15-minute emergency ceiling, not a normal short-note limit;
- decode: local-file protocols, one FFmpeg thread, 12-second timeout, mono 16 kHz signed-16 PCM, at most 28.8 MB;
- inference: sequential 20-second/640,000-byte requests, eight-second timeout per request, serialized Mac worker;
- command: 90-second outer timeout; joined transcript at most 16,384 characters;
- fallback: checksum-pinned RNNT CPU is retained for recordings fitting one chunk; longer recordings fail before
  mission creation when the Mac path is unavailable rather than consuming unbounded pod CPU;
- process: 40 CPU seconds, 1.5 GiB address space, 64 descriptors and automatic temporary-file cleanup.

This proves practical long voice notes through Telegram and exactly-once Central intake. It does not claim verified
timestamp accuracy, semantic VAD, arbitrary languages or a Workspace binary voice-upload control.
