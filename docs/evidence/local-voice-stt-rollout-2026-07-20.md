# Local voice STT rollout evidence — 2026-07-20

## Verdict

**PASS for the bounded local media-preprocessing seam and exactly-once Central intake.** Telegram voice/audio uses
the existing Hermes ingress without an external STT API, new cluster service or workflow engine. A bounded launchd
worker uses the always-on Mac GPU; checksum-pinned Linux CPU RNNT remains the automatic fallback. STT returns
untrusted owner text only; it has no author, reviewer, tool, project or model-routing authority.

Workspace projects the resulting Central mission, but it does not currently expose a binary voice-upload control.
This evidence therefore does not claim a Workspace voice recorder or an owner-sent Telegram UI canary. It combines
the exact Telegram adapter/overlay component gate with a deployed OGG/Opus provider canary and a live
`platform=telegram` stable-source Central acceptance/replay.

## Immutable Git and CI identity

- implementation PR: <https://github.com/PavelLizunov/unified-agent-platform/pull/324>
- implementation head: `7e0d47e9607169c7787eda9cebdaf4ec6de9bb48`
- merge: `cca3d47f0bd9e7a3447eb219190c9b75033cfa78`
- required `static-checks`: run `29737194530`, job `88335244582`, passed in 30 seconds
- model/runtime selection: `docs/research/local-voice-stt-2026-07-20.md`

The commit uses `UAP Agent <slovnmi@gmail.com>` and the required Claude co-author trailer. The protected branch
accepted it only after the strict required check passed.

## Deployed identity

Flux first applied the feature merge and rolled `v64-local-stt` Ready `1/1`, zero restarts. The later API credential
rotation retained the feature and converged to:

```text
GitRepository/uap-platform Ready=True
Kustomization/uap-platform Ready=True
revision=master@sha1:c98d0954ce444b30dabd78a4d16131d338eb92ff
deployment=hermes-agent config-rev=v65-api-credential-rotation ready=1 updated=1 available=1
pod=hermes-agent-7df686f45c-x5j5l phase=Running ready=true restarts=0
```

Mounted/cache hashes after that second restart:

```text
736f366beb8093eebd1a2ea694de48b6f87a34c6e5eb332384ba96fe3f4fceb3  transcribe_cpp-0.1.3.whl
5e150c7862748d33dc2f559a38274bcb46d06ba63f8f5d1247f8196569e02797  transcribe-native-0.1.3-linux-x86_64-cpu-vulkan.tar.gz
7d69952fb431a8d7800ed9910dc61fea37d8406bfe96d10bf24c8bd4b7c68623  gigaam-v3-e2e-rnnt-Q4_K_M.gguf
9ab992736130f158e8b688a63c4d278c49396ce65e57bb8c7e76e92eb28255b5  /opt/uap-stt/local_stt.py
6e3c2c01ce1bc2bac799eba95dde2f3affeda372be6fa119693c2b69ec89aaf5  /opt/hermes/gateway/run.py
```

The managed configuration still selects `provider=uap_local`, the exact model path, Russian, text output and a
45-second outer timeout.

## Runtime canaries

The candidate canary inside the production container on `uap-home-2` used a temporary 3.34-second Russian WAV and
selected the strict CPU/SSE4.2 backend:

```text
wall=2.744s
process peak RSS=223128 KiB
transcript=Создай канареечную задачу, ответь словом готово.
```

After deployment, the same harmless sample was converted to real OGG/Opus and passed through the configured Hermes
`transcribe_audio` dispatcher:

```json
{"provider":"uap_local","success":true,"wall_seconds":2.815,"child_maxrss_kib":222728,"chars":48,"transcript_sha256":"0b0a4be245891ac2a374bebb414ae2f834746c29d02998df6ac2eec3cc48f9bc"}
```

A second Russian OGG/Opus sample then passed through the same deployed provider and into the live Central store with
a stable Telegram source identity. Reopening `MissionStore` and replaying that source returned the original receipt:

```json
{"accepted_events":1,"first_created":true,"mission_id":"mission-intake-f54deecdcf0ffc7f0971f2372fad6637","provider":"uap_local","replay_created":false,"replay_same_mission":true,"source_message_id":"uap-local-stt-canary-20260720-v1","transcript_sha256":"d659493fe1f4e0277dc432e47d0e2d6abbe6cc2bcb3a51c5503d684fc36d6fb9","wall_seconds":3.938}
```

The synthesized voice slightly misrecognized the spoken English project name, so the canary supplied the closed
server-owned `uap` project ID rather than asking STT to choose a project. This is the intended authority boundary.

## Failure, replay and cleanup gates

`tools/hermes-mission/test_local_stt.py` is a runnable POSIX component regression. It proves:

- successful bounded decode/transcription enters `MissionStore` once;
- the same Telegram message ID through a newly constructed store returns the same mission and `created=false`;
- an over-25-second decode failure produces no transcript and a fresh Central DB contains zero mission events;
- symlink input is rejected before decode.

`tools/hermes-mission/test_overlay.py` applies the exact pinned NousResearch source, compiles it and asserts that both
`VOICE` and `AUDIO` transcribe before `ingest_owner_turn`, require every audio path to succeed, redact before durable
stores and remove only files under the exact Hermes audio cache on success or failure. Unknown upstream bytes still
fail the overlay hash gate.

All synthetic audio and transient canary scripts were removed from the Mac, operator host and pod after the checks.
The Hermes durable audio-cache directory did not exist after rollout. No audio is stored in git, logs or this evidence;
only harmless transcript text, hashes and aggregate resource numbers are recorded.

## Resource ceiling and allowed claims

The production boundary is 8 MiB, 25 seconds, checked container format, local-file-only FFmpeg protocols, one decode
thread, 12-second decode timeout, 800,000-byte signed-16 PCM body, eight-second remote timeout, serialized Metal CTC,
64 Mac file descriptors, 45-second outer timeout and a five-second CPU-fallback model wait. CPU fallback retains two
inference threads, 40 CPU seconds and 1.5 GiB address space; the pod retains its 4 GiB memory limit. Q8 was not
advanced after Q4 passed on both real workers.

It is correct to claim local Mac Metal Russian Telegram voice/audio preprocessing, automatic Linux CPU fallback and
exactly-once Central acceptance at the deployed seam. It is not yet correct to claim long-form/VAD beyond 25 seconds, verified timestamp accuracy,
arbitrary languages, a Workspace voice-upload UI or an owner-sent Telegram client transport canary.

## Mac CTC acceleration follow-up

The follow-up selects `gigaam-v3-e2e-ctc-Q4_K_M.gguf` at repository commit
`075dff81f843cf23d22b4ce943ffdc4dd8650cd7`, 182,497,888 bytes, SHA-256
`35581e11e048eef785657cff07e5fced794bba6d9c75143257f6452c8aeea655`. The M4 worker binds only
`100.116.97.112:8091`, validates the model hash before load, accepts at most 25 seconds / 800,000 bytes of mono
16 kHz signed-16 PCM, serializes inference and is kept alive by `com.uap.local-stt`. The existing ops-1
`local-model-router` proxies only the exact bounded transcription path and does not log bodies or transcripts.

A 19.178-second harmless Russian OGG/Opus note passed the updated Hermes wrapper from the live pod:

```json
{"chars":314,"returncode":0,"stderr":"","transcript_sha256":"43f74dbb6dff9a77eb88e6de92e674ba21826c6559ed51f8f12d2754a316f796","wall_seconds":1.334}
```

The transcript then entered the live Central store and replayed through a newly opened store:

```json
{"event_count":1,"first_created":true,"mission_id":"mission-intake-11807b9d61c3f804b09c6d3ba2116fe4","replay_created":false,"replay_same_mission":true,"source_message_id":"uap-mac-stt-canary-20260720-v1","types":["mission.accepted"]}
```

Three warm 19.178-second calls through ops-1 measured 1.618, 0.767 and 1.182 seconds (median 1.182 seconds); the
resident worker used 267,648 KiB RSS. All canary audio and transient scripts were deleted from the workstation,
ops-1, pod and Mac immediately after the run. Linux CPU fallback, failure-before-mission and replay remain covered by
`tools/hermes-mission/test_local_stt.py`.

The acceleration PR and exact rollout identity are appended after the protected-branch deployment.
