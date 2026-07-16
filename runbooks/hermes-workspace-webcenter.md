# Central Hermes Workspace webcenter

Workspace runs on `uap-build-1:3000` (tailnet-only) and points to central hermes-agent on
`100.94.228.67`: gateway API NodePort `30642` and authenticated dashboard NodePort `30911`.
Build-1's `hermes-gateway`/`hermes-dashboard` remain running for Hermes Flow v2's Kanban dispatcher;
they are not the Workspace backend.

When `HERMES_CENTRAL_ONLY=1`, the pinned overlay treats central Hermes as the only authority for sessions, profiles,
tasks, Kanban, jobs and Conductor state. If the corresponding central capability is unavailable, Workspace must show
an unavailable error rather than read or write build-1/browser fallback state. The canonical projection contract is
`docs/hermes-mission-contract-v1.md`. Applying the overlay does not itself migrate Flow; that is A6.2.

## Reproducible rollout

1. Confirm the external checkout is exactly `c1e6ed979dcb8dddf79c5b163150c6c23c4dce0c`, then run
   `python3 tools/hermes-workspace/apply_overlay.py /path/to/hermes-workspace` twice. The second run
   must report an already-applied overlay; any other upstream commit/fingerprint fails closed.
2. First provision the separate coordinator environment from `runbooks/hermes-flow-v2.md`. Then stream the owner
   capability from uap-home-1 into the stdin-only installer on build-1. The helper copies the closed legacy variable
   set, validates every nonempty value, adds only the owner key, writes a temporary `0600` file below the `0700`
   `~/.config/uap` directory, fsyncs and atomically installs the canonical runtime file without printing values:

   ```bash
   SOPS_AGE_KEY_FILE=/home/uap/.config/sops/age/keys.txt \
     sops --decrypt --output-type json \
       /path/to/unified-agent-platform/clusters/prod/infra/hermes-agent-owner.sops.yaml \
   | python3 -c 'import base64,json,sys; sys.stdout.buffer.write(base64.b64decode(json.load(sys.stdin)["data"]["owner-key"], validate=True))' \
   | ssh uap@100.85.56.31 \
       python3 /home/uap/unified-agent-platform/tools/hermes-workspace/install_runtime_env.py \
         --source /home/uap/hermes-workspace/.env \
         --target /home/uap/.config/uap/hermes-workspace.env
   ```

   Run the left side only on uap-home-1; the age key never leaves that host and the decrypted capability exists only
   in the protected SSH/stdin stream. The canonical runtime file is never committed.
3. The closed runtime file contains, without exposing values:
   `HERMES_API_URL=http://100.94.228.67:30642`, `HERMES_API_TOKEN` from Secret `hermes-agent-api/api-key`,
   `HERMES_MISSION_OWNER_KEY` from Secret `hermes-agent-owner/owner-key`,
   `HERMES_CENTRAL_ONLY=1` to exclude build-1 config and local discovery from the model picker,
   `HERMES_DASHBOARD_URL=http://100.94.228.67:30911`, `HERMES_DASHBOARD_USERNAME` to the configured
   dashboard user, and `HERMES_DASHBOARD_PASSWORD` from Secret `hermes-agent-dashboard/password`.
   Both dashboard credential variables must be present, or both must be absent for loopback ephemeral-token
   mode. `HERMES_PASSWORD` remains the existing Workspace UI password.
4. Set build-time variables only in the protected build environment before `pnpm build`:
   `VITE_HERMESWORLD_ENABLED=0` and `VITE_UPDATE_CENTER_ENABLED=0`. They are compiled into the UI and are
   not substitutes for the runtime `HERMES_*` variables.
5. Install the tracked systemd drop-in and verify that it resets the legacy EnvironmentFile before selecting the
   canonical protected file:

   ```bash
   sudo install -D -m 0644 \
     /home/uap/unified-agent-platform/tools/hermes-workspace/systemd/10-uap-runtime-env.conf \
     /etc/systemd/system/hermes-workspace.service.d/10-uap-runtime-env.conf
   sudo systemctl daemon-reload
   python3 /home/uap/unified-agent-platform/tools/hermes-workspace/install_runtime_env.py \
     --check --target /home/uap/.config/uap/hermes-workspace.env
   test "$(systemctl show hermes-workspace -p EnvironmentFiles --value | awk '{print $1}')" = \
     /home/uap/.config/uap/hermes-workspace.env
   ```

6. Build and restart only the Workspace unit on build-1 after the overlay and environment are installed:
   `pnpm install --frozen-lockfile && pnpm build`, then `sudo systemctl restart hermes-workspace`.
   Do not restart the local gateway/dashboard for this change.
7. Reinstall the separate coordinator environment and unit described in `runbooks/hermes-flow-v2.md`, then run
   `systemctl --user daemon-reload`. Verify without
   printing values that `~/.config/uap/delivery-coordinator.env` contains exactly `HERMES_API_URL` and
   `HERMES_API_TOKEN`, and no `HERMES_MISSION_OWNER_KEY`. The coordinator unit must include
   `UnsetEnvironment=HERMES_MISSION_OWNER_KEY`.
8. After the Workspace restart, verify the protected file and directory remain `0600`/`0700` and the running Workspace process
   has `HERMES_MISSION_OWNER_KEY` without printing its environment. A missing key must leave mission answers
   fail-closed with HTTP 503; the coordinator continues to operate using its separate environment. After HTTP and
   answer-route post-verification, securely remove the unused legacy `/home/uap/hermes-workspace/.env` copy:

   ```bash
   test "$(stat -c %a /home/uap/.config/uap)" = 700
   test "$(stat -c %a /home/uap/.config/uap/hermes-workspace.env)" = 600
   pid="$(systemctl show hermes-workspace -p MainPID --value)"
   test "$pid" -gt 1
   sudo tr '\0' '\n' < "/proc/$pid/environ" | grep -q '^HERMES_MISSION_OWNER_KEY=.'
   shred -u /home/uap/hermes-workspace/.env
   ```

For later owner-key rotation, use the canonical protected file as both `--source` and the source of the atomic
replacement; never recreate the legacy checkout-local file.

Secret values must be streamed between trusted hosts or supplied on stdin; never put values in commands,
shell history, process listings, logs, markdown, or manifests. The encrypted Secret remains GitOps-managed.

## Smoke sequence

```bash
curl -fsS -H "Authorization: Bearer $HERMES_API_TOKEN" http://100.94.228.67:30642/v1/models
curl -fsS -o /dev/null -w '%{http_code}\n' http://100.85.56.31:3000/
curl -fsS -o /dev/null -w '%{http_code}\n' http://100.94.228.67:30911/api/status
test "$(curl -sS -o /dev/null -w '%{http_code}' -X POST http://100.85.56.31:3000/api/playground-npc)" = 404
test "$(curl -sS -o /dev/null -w '%{http_code}' http://100.85.56.31:3000/api/playground-admin)" = 404
```

Log in to Workspace and verify chat, central dashboard-backed Profiles, and Kanban. Verify no HermesWorld,
build-1 local-model, or Update Center navigation is present. A dashboard 401 must trigger one in-memory
password-session refresh; credentials and cookies must never appear in logs.
