# Central Hermes Workspace webcenter

Workspace runs on `uap-build-1:3000` (tailnet-only) and points to central hermes-agent on
`100.94.228.67`: gateway API NodePort `30642` and authenticated dashboard NodePort `30911`.
Build-1's `hermes-gateway`/`hermes-dashboard` remain running for Hermes Flow v2's Kanban dispatcher;
they are not the Workspace backend.

## Reproducible rollout

1. Confirm the external checkout is exactly `c1e6ed979dcb8dddf79c5b163150c6c23c4dce0c`, then run
   `python3 tools/hermes-workspace/apply_overlay.py /path/to/hermes-workspace` twice. The second run
   must report an already-applied overlay; any other upstream commit/fingerprint fails closed.
2. Provision the owner-only runtime file `/home/uap/hermes-workspace/.env` on build-1 with mode `0600`,
   and configure the systemd unit with `EnvironmentFile=/home/uap/hermes-workspace/.env`. Stream the
   encrypted-secret-derived values between trusted hosts or into a protected stdin consumer; do not print
   values, place them in command arguments/history, logs, or documentation. The runtime file is the one
   deliberate owner-only secret store and is never committed.
3. Put runtime variables in that file without exposing values:
   `HERMES_API_URL=http://100.94.228.67:30642`, `HERMES_API_TOKEN` from Secret `hermes-agent-api/api-key`,
   `HERMES_DASHBOARD_URL=http://100.94.228.67:30911`, `HERMES_DASHBOARD_USERNAME` to the configured
   dashboard user, and `HERMES_DASHBOARD_PASSWORD` from Secret `hermes-agent-dashboard/password`.
   Both dashboard credential variables must be present, or both must be absent for loopback ephemeral-token
   mode. `HERMES_PASSWORD` remains the existing Workspace UI password.
4. Set build-time variables only in the protected build environment before `pnpm build`:
   `VITE_HERMESWORLD_ENABLED=0` and `VITE_UPDATE_CENTER_ENABLED=0`. They are compiled into the UI and are
   not substitutes for the runtime `HERMES_*` variables.
5. Build and restart only the Workspace unit on build-1 after the overlay and environment are installed:
   `pnpm install --frozen-lockfile && pnpm build`, then `sudo systemctl restart hermes-workspace`.
   Do not restart the local gateway/dashboard for this change.

Secret values must be streamed between trusted hosts or supplied on stdin; never put values in commands,
shell history, process listings, logs, markdown, or manifests. The encrypted Secret remains GitOps-managed.

## Smoke sequence

```bash
curl -fsS -H "Authorization: Bearer $HERMES_API_TOKEN" http://100.94.228.67:30642/v1/models
curl -fsS -o /dev/null -w '%{http_code}\n' http://100.85.56.31:3000/
curl -fsS -o /dev/null -w '%{http_code}\n' http://100.94.228.67:30911/api/status
```

Log in to Workspace and verify chat, central dashboard-backed Profiles, and Kanban. Verify no HermesWorld,
build-1 local-model, or Update Center navigation is present. A dashboard 401 must trigger one in-memory
password-session refresh; credentials and cookies must never appear in logs.
