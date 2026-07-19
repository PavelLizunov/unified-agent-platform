# Signed completion attestation — 2026-07-19

This record closes signed publication for the existing registered no-deploy delivery/input-lineage bundle. The signed
JSON does not contain Workspace/Telegram cursor or projection-hash fields, so it is not yet the final two-channel
Product Operating Contract certificate. It also does not claim arbitrary-repository routing, a deploy/release target,
complete cross-channel chat transcripts, HA or a platform-wide GPU/local-runtime hard deny.

## Subject

- Mission: `mission-intake-e966529d2686998b2c8f55acd06716a8`.
- Input: ordinary Telegram goal; exact ordinary Workspace `APPROVE` resumed the same Central mission/root.
- Delivery: Sol author, distinct exact-SHA Terra reviewer, target PR #10, required CI, exact merge, fresh-main
  post-verify, cleanup, terminal sequence 27 and explicit `delivery_mode: none` / `not_applicable`.
- Certificate: `docs/evidence/completion/mission-intake-e966529d2686998b2c8f55acd06716a8.json`.
- Semantic self-digest: `70fe43b78444d85b0bfb63f801abb80ed052e65a7437e749f868fe45009a764d`.
- Exact byte digest: `509117fb78b85ee9671de3fb6a1e08ee1d4e6707b38a45c8086785e9568e78ef`.

The closed schema contains only the server-owned input platform, one-way source/goal/answer hashes, bounded public
delivery facts and exact runtime/Git/CI/review/cleanup identities. Raw channel, message and session identifiers are not
published.

## Publication and review

- UAP PR: [#291](https://github.com/PavelLizunov/unified-agent-platform/pull/291).
- Exact independently reviewed head: `9ec6d8f8692eca213ac1e14d768846d1d6cf1f60`.
- Independent final verdict: `PASS — no actionable P0/P1/P2 findings remain` from a distinct Terra `xhigh`, read-only
  session reviewing that exact SHA.
- Protected-master merge: `1fd06f63439ca056325ca86f6ab8bd639f3af47d`.
- Master `static-checks`: [run 29680293505](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29680293505).
- Attestation: [run 29680293407](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29680293407),
  job `88175101441`.

The workflow triggers only when `docs/evidence/completion/*.json` changes on `master`. Top-level permissions are empty;
the single GitHub-hosted job has only `contents: read`, `id-token: write` and `attestations: write`. Checkout and
attestation actions are pinned to exact commit SHAs. The job first runs the repository's deterministic semantic
verifier and only then asks GitHub to issue SLSA provenance for the exact certificate bytes.

The first PR run correctly failed because the certificate digest resembled a generic API key. The final narrow
Gitleaks allowlist accepts only a standalone `source_key_sha256` property in this exact evidence directory. A
same-line `source_key_sha256` plus real `api_key` fixture remains detected; Gitleaks 8.24.3 passed the canonical bundle
and reported both injected secrets in that adversarial fixture.

## Independent verification

From an authenticated checkout at merge `1fd06f63439ca056325ca86f6ab8bd639f3af47d`:

```bash
python3 tools/swarm/flow_contract.py verify-completion-evidence \
  --bundle docs/evidence/completion/mission-intake-e966529d2686998b2c8f55acd06716a8.json

gh attestation verify \
  docs/evidence/completion/mission-intake-e966529d2686998b2c8f55acd06716a8.json \
  --repo PavelLizunov/unified-agent-platform \
  --signer-workflow PavelLizunov/unified-agent-platform/.github/workflows/attest-completion-evidence.yml \
  --source-digest 1fd06f63439ca056325ca86f6ab8bd639f3af47d \
  --source-ref refs/heads/master \
  --deny-self-hosted-runners
```

The semantic verifier returns `hermes-flow-completion-evidence-ok`. GitHub verification returned SLSA provenance v1,
subject name `mission-intake-e966529d2686998b2c8f55acd06716a8.json`, subject SHA-256
`509117fb78b85ee9671de3fb6a1e08ee1d4e6707b38a45c8086785e9568e78ef` and one verified timestamp.

## Accepted claim

For the exact registered pilot whose repository contract declares no deployment step, the published redacted bundle
deterministically binds server-owned ordinary Telegram intake, a hashed owner answer, approved OpenAI routing, coding,
tests, independent exact-SHA review, PR, CI, merge, post-verify, terminal publication and cleanup. Its exact bytes are
tamper-evident and GitHub-attested.

The [prior live record](cross-channel-owner-answer-live-canary-2026-07-19.md) separately shows that the ordinary
Workspace answer resumed the same Central mission and that Workspace and Telegram converged at cursor 27. Because
those cursor/projection facts are not fields of the signed JSON, the final two-channel certificate and broader product
claims remain bounded by section 8 of `docs/product-operating-contract.md`.
