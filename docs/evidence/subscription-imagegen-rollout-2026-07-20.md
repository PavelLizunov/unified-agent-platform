# Subscription image generation rollout — 2026-07-20

## Scope

ADR-034 adds `media.image.generate` to the existing Central Hermes process. It uses the deployed
`openai-codex` / `codex_app_server` subscription boundary and built-in `$imagegen`; there is no new service,
paid Image API, Claude, local-model or GPU fallback. Image editing remains fail-closed because the pinned adapter
does not preserve source image bytes.

## Source and gates

- PR #327 merged as `07edfb440656865fc35b22c11c76f1e0617a3047` after required `static-checks` run
  `29738435921` passed.
- The first live canary exposed a real Codex `0.142.0` quirk: terminal `image_generation_end` retained
  `status="generating"` despite one valid `saved_path`. The durable mission failed without retrying or adopting an
  ambiguous result.
- PR #329 encoded that production shape in the component regression and merged as
  `5efe2401d5720c7f6d791f4698719df2553c6de8` after required `static-checks` run `29739095357` passed.
- Local gates: `test_hermes_media.py`, mission runtime/deployment tests, generated ConfigMap check,
  `verify-local.ps1 -SkipSmoke`, whitespace and secret scans.

## Rollout and canary

Flux source and Kustomization both applied exact merge `5efe2401d5720c7f6d791f4698719df2553c6de8`.
`hermes-agent` rolled to `v68-imagegen-completion`; pod `hermes-agent-ffcd6f8d8-pb4mp` was Ready with zero restarts.
Mounted `uap_media.py` SHA-256 matched source:

`c4f8d0e88df55871970408b20f7ebf9fdc4871fc969bf2091bc627c30de2c095`

Authenticated app-server capability remained `imageGeneration=True`. One ordinary Workspace-style turn created
mission `mission-intake-abfe8c7e91320c8bc73ae028e68dab52` and separate Codex thread
`019f7f52-5308-7540-9cbe-d29e5f4a9e9f`. The originating session returned the completed result.

Central projected exactly one artifact:

- name: `image-c5efc58aa4cc13a7.png`
- type: `image/png`
- size: `796818` bytes
- SHA-256: `c5efc58aa4cc13a76146f2d77a94a0df4982540153d2780fbd1789582bdf5949`

Authenticated download matched the metadata and PNG magic. Replaying the identical source message completed in
24 ms with the same sequence `10`, projection `315e181ba1f4b6a7`, thread id and single artifact: no second generation.

## Workspace and remaining boundary

The build-1 UAP checkout was advanced to exact merge `5efe2401...`; all 25 Workspace overlay files then reported
`exact-patched`. `pnpm install --frozen-lockfile` and `pnpm build` passed, only `hermes-workspace` was restarted, and
the service returned HTTP 200. Installed artifact route/card hashes matched repository source; the artifact route
returned 401 without login as required.

No live Telegram image was sent to avoid an unsolicited owner message. Its installed path reuses the existing
`send_image_file` adapter and durable notification cursor, but real Telegram delivery is not claimed as canary-proven.
No browser-authenticated visual `<img>` check was performed. Image editing remains unsupported and fails before any
generation.
