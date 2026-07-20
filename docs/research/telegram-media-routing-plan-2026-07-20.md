# Telegram media routing — implementation handoff

**Status:** implementation included; code- and component-proven. Live Telegram topic canary still required.
**Owner decision:** one-bot / private-forum Code+Images topology authorized (ADR-034 amendment).

## Proven current behavior

- A `$imagegen` request completed through the production subscription-authenticated Codex path
  and produced a durable 796,818-byte PNG artifact returned to the originating **session**.
  Telegram image delivery is code-complete but **not canary-proven**: no live Telegram image
  was sent (`docs/evidence/subscription-imagegen-rollout-2026-07-20.md`).
- Image generation is projectless (`media.image.generate`), while ordinary software-delivery
  intake requires a registered project.
- Generation is live-proven. Image editing is not: the production adapter does not pass a
  source image into the Codex media session.

Relevant implementation:

- `tools/hermes-mission/runtime.py`: `ingest_owner_turn`, `_intake_scope`, `ingest_media_goal`,
  `media_topic_pairs`
- `tools/hermes-mission/apply_overlay.py`: Telegram voice intake and image return
- `clusters/prod/infra/hermes-agent.yaml`: one production `TELEGRAM_BOT_TOKEN`,
  `HERMES_MISSION_MEDIA_TOPICS` allowlist

## Structural topic isolation (code-proven)

`_intake_scope()` keys on `chat_id + thread_id`. All downstream structures — intake drafts,
subscriptions, bound missions — include `thread_id`. A pending Code draft in one topic
**cannot** consume a message in a different topic. This is structurally guaranteed by the
existing scope mechanism and covered by component regression.

## Topic capability dispatch (code- and component-proven; live canary still required)

`media_topic_pairs()` reads a server-owned JSON array of exact `{"chat_id", "thread_id"}`
pair objects from `HERMES_MISSION_MEDIA_TOPICS`. Telegram's `message_thread_id` is unique
within a chat, not globally, so both fields are required. In `ingest_owner_turn()`, **after**
bound-question answering and **before** project-selection draft resolution, a configured
`(chat_id, thread_id)` pair routes the entire redacted text to `ingest_media_goal()` as
`media.image.generate` — no `$imagegen` prefix or image verb required. The model never
guesses capability; the exact pair allowlist does.

Ordering rationale:

- **After bound questions**: a media mission's owner question is still answerable in its topic.
- **Before drafts**: media intake is projectless, so a configured media topic never creates a
  draft; an unrelated stale draft cannot consume a media-topic message.
- **Explicit `$imagegen`/`/image`/`/imagine`** still works in any topic via the later
  `image_generation_prompt()` check.
- **Fail-closed**: empty/absent `HERMES_MISSION_MEDIA_TOPICS` → no topic routing; ordinary
  text follows existing project intake. Malformed configuration raises `MissionError` and
  blocks the owner turn with zero mission/draft side effects.

Voice reuse: the gateway overlay transcribes voice → redacts → calls `ingest_owner_turn()`
with the same `chat_id`/`thread_id`. No voice-specific change is needed; the topic dispatch
seam catches the transcript.

Deployment: `HERMES_MISSION_MEDIA_TOPICS` is wired in `hermes-agent.yaml` with a safe
disabled default (`"[]"`). The owner sets the real `{"chat_id","thread_id"}` pair after
creating the supergroup.

## Topology (owner-authorized)

One bot in one private Telegram supergroup with separate topics:

- **Code / projects:** ordinary text and voice enter registered-project intake and Flow delivery.
- **Images:** ordinary text and voice deterministically enter a separate media mission; no
  project is requested. The topic's exact `(chat_id, thread_id)` pair is in the
  `HERMES_MISSION_MEDIA_TOPICS` allowlist.

Both topics project into the existing Central mission ledger and Workspace.

Fallback: two direct-message bots with explicit bot/account isolation, only if the live
topic canary fails. That design would require an explicit bot/account identity in channel
scope, another BotFather credential, and proof that the pinned gateway can host multiple
Telegram adapters without a new service.

## Remaining live-canary gate

The pinned upstream Hermes Telegram adapter's population of `source.thread_id` from Telegram's
`message_thread_id` is **not verified by committed evidence**. UAP-owned code passes `thread_id`
correctly in all paths (gateway overlay, API server, voice intake, notification, image
delivery), but the upstream adapter is a pinned binary outside this repository.

### Acceptance canary

1. Create a private Telegram supergroup with forum/topics enabled. Create **Code** and
   **Images** topics. Note the supergroup's `chat_id` and the Images topic's `thread_id`.
2. Set `HERMES_MISSION_MEDIA_TOPICS` to `[{"chat_id":"<real-chat-id>","thread_id":"<real-images-thread-id>"}]`
   and roll the pod.
3. In **Code** topic: send an ambiguous coding goal → expect project-selection prompt.
4. In **Images** topic: send ordinary text with no image command words (e.g. "lighthouse on
   a rocky shore") → expect exactly one media mission, image returned to Images topic, no
   project list.
5. In **Images** topic: send a voice note → expect media mission from transcript.
6. In **Code** topic: send the project name → draft resolves, mission created.
7. Replay the image message → no second generation.
8. Restart pod after artifact creation → artifact delivery retries, no re-generation.
9. Confirm both missions and durable artifact metadata are visible in Central/Workspace.

Resume prompt for another Codex task: `Continue docs/research/telegram-media-routing-plan-2026-07-20.md. The topic dispatch is implemented and component-tested with (chat_id, thread_id) pairs. Run the live canary with real chat_id and Images thread_id, then record evidence.`
