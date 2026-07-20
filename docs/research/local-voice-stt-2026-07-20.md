# Local Russian voice-note STT selection — 2026-07-20

## Decision

Use [`handy-computer/gigaam-v3-e2e-ctc-gguf`](https://huggingface.co/handy-computer/gigaam-v3-e2e-ctc-gguf)
at repository commit `075dff81f843cf23d22b4ce943ffdc4dd8650cd7`, file
`gigaam-v3-e2e-ctc-Q4_K_M.gguf`, with the Metal arm64 build of
[`handy-computer/transcribe.cpp`](https://github.com/handy-computer/transcribe.cpp) release `v0.1.3` on the
always-on M4 Mac mini. The original checksum-pinned e2e-RNNT Q4 CPU runtime remains in the Hermes pod as automatic
fallback. CTC is deterministic media preprocessing only: it is not an agent, author, reviewer or model-routing
component.

The alternative [`ai-sage/GigaAM-v3`](https://huggingface.co/ai-sage/GigaAM-v3) is not selected for this ingress.
Both options are MIT-licensed and recognize Russian, but the original PyTorch distribution requires a substantially
larger runtime and adds a gated long-form VAD dependency that the bounded voice-note path does not need.

## Compared artifacts

| Property | `handy-computer` GGUF | `ai-sage/GigaAM-v3` |
|---|---|---|
| Source identity | CTC repo commit `075dff81f843cf23d22b4ce943ffdc4dd8650cd7`; RNNT fallback repo commit `f719d70812344f4d0fb8c11c0887b190501a7465` | repo `main` commit `ec1dc1f01d0d627ab2c0d3acc1e235702300d95e`; `e2e_rnnt` revision `7655ad717f8122257385bb4b2f373db3697e8680` |
| License | MIT metadata; conversion points to the MIT upstream | MIT metadata and upstream repository license |
| Selected/nearest weight | CTC Q4_K_M: 182,497,888 bytes, SHA-256 `35581e11e048eef785657cff07e5fced794bba6d9c75143257f6452c8aeea655`; RNNT fallback: 183,948,704 bytes, SHA-256 `7d69952fb431a8d7800ed9910dc61fea37d8406bfe96d10bf24c8bd4b7c68623` | `pytorch_model.bin`: 448,928,167 bytes, SHA-256 `afc6dcbae8320ea56f2cddebc0f13fbf62c9d59b6ddcad899782623c8610826a` |
| Other useful size point | Q8_0: 273,724,832 bytes; F16: 452,381,408 bytes | approximately 220–240M parameters plus PyTorch/torchaudio/Transformers runtime |
| Runtime format | GGUF loaded by C/C++ `ggml`; Python wrapper is stdlib `ctypes` | custom Hugging Face Python module with `trust_remote_code=True` and PyTorch stack |
| Short-form boundary | model/runtime rejects audio beyond 25 seconds | `LONGFORM_THRESHOLD = 25 * 16000`; `transcribe()` rejects longer audio |
| Long-form/VAD | UAP splits decoded PCM into deterministic 20-second requests; no VAD/model dependency | `transcribe_longform()` adds `pyannote/segmentation-3.0`, extra packages, gated terms and `HF_TOKEN` |
| Input | 16 kHz mono PCM; UAP performs bounded OGG/Opus or audio-container decode with the image's FFmpeg | checked model code invokes FFmpeg to produce 16 kHz mono PCM |
| Timestamps | native API exposes timestamp modes; this model card mentions token timestamps, but UAP did not verify timestamp accuracy and requests `timestamps=none` | current upstream code/release mentions word timestamps, but the ordinary-goal intake does not consume them |

Model-card WER/RTF tables were used only to choose a canary candidate. They are not accepted as UAP runtime
evidence. The production choice is based on the checked files, exact hashes and live CPU/Metal runs below.

## Mac acceleration follow-up

The selected CTC artifact is 182,497,888 bytes with SHA-256
`35581e11e048eef785657cff07e5fced794bba6d9c75143257f6452c8aeea655`. The repository commit and file hash are
both pinned; launchd refuses to load a mismatched model. The pinned macOS arm64 Metal native archive is
`transcribe-native-0.1.3-macos-arm64-metal.tar.gz`, SHA-256
`5cd8791846dec8a4e1c269cbe836b7c7d294e7d6c295209a1348e3bc5aae08c3`.

On a 20.381-second Russian comparison sample, CTC Q4 completed in about 0.36â€“0.42 seconds versus 0.45â€“0.50 seconds
for RNNT Q4 and 1.21â€“1.24 seconds for MLX Whisper Large-v3-Turbo Q4. CTC and RNNT each missed one of 54 reference
words; Whisper missed three. The published Q4 WER is 5.57% for CTC versus 5.36% for RNNT, so CTC trades a small
benchmark-accuracy margin for the lowest observed latency. The owner explicitly selected that trade-off on
2026-07-20. Whisper was removed after the comparison.

## Runtime pin

The pod bootstrap verifies all three immutable inputs before use:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `transcribe_cpp-0.1.3-py3-none-any.whl` | 32,562 bytes | `736f366beb8093eebd1a2ea694de48b6f87a34c6e5eb332384ba96fe3f4fceb3` |
| `transcribe-native-0.1.3-linux-x86_64-cpu-vulkan.tar.gz` | 29,703,996 bytes | `5e150c7862748d33dc2f559a38274bcb46d06ba63f8f5d1247f8196569e02797` |
| `gigaam-v3-e2e-rnnt-Q4_K_M.gguf` | 183,948,704 bytes | `7d69952fb431a8d7800ed9910dc61fea37d8406bfe96d10bf24c8bd4b7c68623` |

The native release tag resolves to transcribe.cpp commit `a94e021ef658dc7c788837341a13f6acea3baf3c`.
The GGUF repository identifies transcribe.cpp commit `42b96d91404b1431bdbe29b1d9b4f3575d5e42ab` as its validated
runtime point; UAP separately ran the newer pinned `v0.1.3` release before selecting it.

## Fleet fit

Read-only probes on 2026-07-20 found:

| Host | Relevant real inventory | Fit |
|---|---|---|
| `uap-home-2` | Debian 12 VM, 6 vCPU with SSE4.2, 8 GB RAM, no GPU; Hermes pod limit 4 GiB | safe decode and automatic CPU fallback host |
| `uap-build-1` | Ubuntu 22.04, 8 vCPU Ryzen/AVX2+, about 12.5 GB assigned RAM, no GPU | safe build/research fallback; not needed at runtime |
| `uap-home-1` | Debian 12 VM, 4 vCPU, 8 GB RAM, no GPU | control plane; do not add inference load |
| `uap-ops-1` | Debian 12, 2 vCPU/2 GB, no swap | too small |
| owner Windows | Ryzen 9 7945HX3D, 32 GB, RTX 5060 Ti 16 GB | not always-on and owner-gated; unnecessary |
| owner Mac mini | M4/16 GB, Metal, always-on | selected primary CTC worker; Ornith remains an unrelated manual brain fallback |

The production-equivalent Q4 canary ran inside the existing `hermes-agent` container on `uap-home-2`. A 3.34-second
Russian synthesized voice note completed on the strict CPU/SSE4.2 backend in 2.744 seconds (RTF 0.82) with process
peak RSS 223,128 KiB. The expected harmless sentence and returned sentence differed only in punctuation. The audio
was temporary and is not stored in git, logs or evidence.

The original Linux CPU canary remains the fallback proof. The production Mac canary used a 19.178-second Russian
OGG/Opus note: safe decode plus the LAN router and tailnet Metal worker completed in 1.334 seconds. Direct resident
model inference was 0.23â€“0.28 seconds; bounded PCM transport dominates the end-to-end time. The worker process used
about 268 MiB RSS. Q8 was not advanced because Q4 passed the accuracy and latency canary.

## Production boundary

The wrapper and existing Hermes seam jointly enforce:

- Telegram rejects media above its existing pre-download bound; STT adds an 8 MiB regular-file bound;
- accepted container suffix plus FFprobe format check; local-file-only protocols;
- duration `0 < d <= 15m` as an emergency resource ceiling; no long-form VAD or HF token;
- FFmpeg `-nostdin`, one decode thread, no video/subtitle/data, 16 kHz mono signed-16 PCM, 12-second decode timeout and
  bounded PCM output;
- decoded PCM is sent sequentially in 20-second bodies capped at 640,000 bytes, with an eight-second per-request
  timeout, one serialized Mac request with queue depth two, Metal CTC with two host threads, 64 Mac file descriptors
  and launchd restart convergence;
- on remote failure, recordings fitting one chunk use CPU RNNT with two inference threads, 40 CPU seconds, 1.5 GiB
  address-space ceiling and a five-second exclusive model lock; longer recordings fail before mission creation
  instead of multiplying CPU time; the outer command timeout is 90 seconds;
- temporary decode/output directories removed automatically; Telegram cache audio removed after success or failure;
- the joined transcript is normalized and capped at 16,384 characters, then redacted before either durable store;
- STT failure returns the existing Russian retry/text message before `MissionStore` is opened;
- the Telegram message ID remains the durable intake identity, so replay and a new `MissionStore` instance converge
  to the original Central mission.

The transcript remains untrusted owner text. It enters the existing ordinary-goal/answer path and receives no
instruction-execution, author, reviewer, tool, project-selection or model-routing authority from STT.

Workspace currently transports text to the same Central intake but has no binary voice-upload control. This change
does not invent a second Workspace media endpoint: the production voice transport and requested live canary are
Telegram voice/audio, while the resulting mission and transcript projection remain visible through Workspace.
