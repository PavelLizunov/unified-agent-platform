# Signed completion attestation — 2026-07-19

This record publishes the closed schema-v3 two-channel completion certificate for the exact registered owner-gated
no-deploy pilot. The certificate binds ordinary Telegram intake, the Workspace owner answer, both channel cursors and
projection identities, and the autonomous delivery result under one Central mission. It does not claim arbitrary
repository/profile discovery, an actual deploy/release target, complete cross-channel chat transcripts, HA or a
platform-wide GPU/local-runtime hard deny.

## Subject

- Mission: `mission-intake-503332fe3dcba802ded5f3a1bd513026`.
- Input: ordinary Telegram goal; exact ordinary Workspace `APPROVE` resumed the same Central mission/root.
- Channels: Workspace and Telegram both reached cursor `27` and projection `bc4fe1095ad47411`; Telegram had one
  subscriber.
- Execution: root task `t_62231c95`, run `47`, Sol `xhigh` author session
  `019f7a85-6676-78a2-927d-07d8a61608b0`, distinct Terra `xhigh` read-only reviewer session
  `019f7a89-77b3-7222-bfe3-988d018fb30c` and reviewer source attestation
  `6c52c310521329f9cdd0da821662c5021b4a0cf4a557c823953d38f952429ba9`.
- Delivery: target [PR #11](https://github.com/PavelLizunov/hermes-flow-v2-pilot/pull/11), candidate
  `94165dde72e4333dc0acd40a65f7ea984b34900e`, required Linux/macOS/Windows/Python CI, exact merge/default revision
  `290ed192d19d0fdb6600953c607b2bfc7d3e1df7`, fresh-main post-verify, cleanup and explicit
  `delivery_mode: none` / `not_applicable`.
- Certificate: `docs/evidence/completion/mission-intake-503332fe3dcba802ded5f3a1bd513026.json`.
- Semantic self-digest: `afd42c9e4bc13e2cbfe00439045854f99bc50c2fe33c5f424c7424e4fd848c66`.
- Exact byte digest: `92178a9b679fddb420475fc4e002f42283e0f74048a0f848e2560d7c5e30164c`.

The closed schema contains only server-owned platform labels, one-way source/goal/answer hashes, bounded public
delivery facts and exact runtime/Git/CI/review/cleanup identities. Raw channel, message and session identifiers are not
published.

## Publication and review

- UAP PR: [#295](https://github.com/PavelLizunov/unified-agent-platform/pull/295).
- Exact independently reviewed head: `0d930cb3a2ff1d3a49894d48b102faa409f6fbd7`.
- Independent final verdict: `PASS` from Sol `low`, read-only session
  `019f7ab3-021e-7d33-bd23-db73aa1cb92e`, bound to source attestation
  `8e3318179f17a1fa2c38710f8b5ded6c2275836606dcc6268c3c591d76200326` and that exact clean SHA.
- Protected-master merge: `a127994aaf86661c5aadcde838f81373c1e1bb62`.
- PR `static-checks`: [run 29690154049](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29690154049).
- Master `static-checks`: [run 29690240902](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29690240902),
  job `88201554323`.
- Attestation: [run 29690240901](https://github.com/PavelLizunov/unified-agent-platform/actions/runs/29690240901),
  job `88201554326`.

The protected-master workflow re-ran the deterministic semantic verifier before issuing SLSA provenance for the exact
certificate bytes. `gh attestation verify` bound byte digest `92178a9b...` to merge `a127994...`,
`refs/heads/master`, the exact signer workflow and a GitHub-hosted runner. Rekor recorded the attestation at
`2026-07-19T14:08:38Z`.

## Independent verification

From an authenticated checkout containing merge `a127994aaf86661c5aadcde838f81373c1e1bb62`:

```bash
python3 tools/swarm/flow_contract.py verify-completion-evidence \
  --bundle docs/evidence/completion/mission-intake-503332fe3dcba802ded5f3a1bd513026.json

gh attestation verify \
  docs/evidence/completion/mission-intake-503332fe3dcba802ded5f3a1bd513026.json \
  --repo PavelLizunov/unified-agent-platform \
  --signer-workflow PavelLizunov/unified-agent-platform/.github/workflows/attest-completion-evidence.yml \
  --source-digest a127994aaf86661c5aadcde838f81373c1e1bb62 \
  --source-ref refs/heads/master \
  --deny-self-hosted-runners
```

The semantic verifier returns `hermes-flow-completion-evidence-ok`. GitHub verification returns SLSA provenance v1
for subject `mission-intake-503332fe3dcba802ded5f3a1bd513026.json` with SHA-256 `92178a9b...`.

## Default-route cleanup

The canary deliberately used the owner-gated diagnostic profile to prove a Telegram-origin question could be answered
through Workspace. That is not the ordinary safe-task route. PR [#296](https://github.com/PavelLizunov/unified-agent-platform/pull/296)
changed the server-owned Telegram mapping back to `build1-flow-pilot-registered-v4`, passed an independent exact-SHA
Sol read-only review and both PR/master CI, and merged as `135ab51adb7093f19f4f5beb6b7d248c6a9a8914`. Flux reported
both source and Kustomization Ready at that exact revision; the new pod was Ready, returned authenticated mission API
HTTP 200 and exposed registered-v4 for both Workspace and Telegram. The registered coordinator timer remained
enabled/active and its natural ticks completed successfully. The owner-gate profile remains available only for
deliberate privileged-flow diagnostics.

## Accepted claim

For this exact registered no-deploy target, UAP has a tamper-evident, GitHub-attested certificate binding an ordinary
Telegram goal, a required Workspace answer, approved OpenAI routing, coding, tests, independent exact-SHA review, PR,
CI, merge, explicit no-deploy applicability, post-verify, terminal publication, cross-channel cursor/projection
convergence and cleanup. Ordinary safe Telegram and Workspace intake now route to the automatic registered profile and
do not request owner approval merely for model selection, retries, tests or subscription spend.
