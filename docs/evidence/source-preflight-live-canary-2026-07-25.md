# Required-source preflight — live component canary (2026-07-25)

## Verdict

**PASS for authenticated fetch, immutable binding, and restart-style re-verification.**

This is a component canary of the installed build-1 coordinator. It did not accept a Central mission, invoke a
model, create a worktree, or mutate Git/GitHub.

## Boundary

- Runtime: installed `/home/uap/swarm-bin/delivery_coordinator.py` and `source_preflight.py`.
- Authority: the existing build-1 `gh api` authentication; no token value was read or printed.
- Target and source repository: private `PavelLizunov/hermes-flow-v2-pilot`.
- Requested source: `README.md` at `main`.
- Canary mission identity: `source-live-canary-20260725`.
- Persisted/output data: bounded provenance, immutable commit, byte count, and SHA-256 only. Raw source content was
  held in memory for comparison and was not printed or written.

## Observed proof

The installed coordinator:

1. resolved `main` through the GitHub commits API;
2. fetched the source by the resolved immutable commit;
3. produced a closed source binding;
4. re-fetched the source using the binding's immutable commit;
5. required identical bytes, size, resolved commit, and content hash.

Output:

```text
source-preflight-live-ok
{"content_sha256":"b080090a0bfbe545a4a0b4fb50cb9629bd6154488da4fe706356b2af532d494e",
 "path":"README.md",
 "repo":"PavelLizunov/hermes-flow-v2-pilot",
 "resolved_ref":"325dd53e7af6dc4f154fa0429513398b0d059b75"}
size_bytes=2871
```

## Claim boundary

Proven:

- the installed fetch path can read an authenticated private repository;
- a mutable branch name is converted to an immutable commit before binding;
- re-verification uses the immutable commit and rejects changed identity/content;
- provenance output does not carry credentials or raw file content.

Not proven by this component canary:

- a full ordinary-message mission containing a required source through author/reviewer/PR/merge;
- separately authorized cross-repository source use, which remains fail-closed;
- provider availability outside the existing GitHub authority.
