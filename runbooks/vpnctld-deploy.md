# vpnctld exact-revision deployment

This is the single approved production deploy path for the registered `PavelLizunov/vpnctl` profile. It is deliberately
not a generic remote shell or a template for automatically enrolling other projects.

## Boundary

- source and coordinator: `uap-build-1`;
- target: Proxmox VM 119, hostname `vpnctld`, tailnet `100.88.198.106`;
- environment: `vpnctl-production`;
- service: `vpnctld.service`, local health `http://127.0.0.1:18402/api/v1/health`;
- accepted input: one exact merged Git revision from the coordinator's fresh verification worktree;
- installed payload: `/opt/vpnctl/vpnctld` and `/opt/vpnctl/assets` only.

The coordinator writes the plan before invoking the driver. A restart repeats the same revision idempotently. Two
failed attempts produce an explicit deployment failure without an owner question. Central cannot complete a deploy
mission without the deployment gate, environment, exact deployed revision, full installed-payload SHA-256 and health
verification.

## Network prerequisite

`vpnctld` requires `infra/ops/tailscaled-vless-proxy.conf` at
`/etc/systemd/system/tailscaled.service.d/proxy.conf`. Direct Tailscale control-plane initial netmaps were repeatedly
cut after about two minutes; the existing VLESS egress on `192.168.0.202:30880` restores the long poll. Keep
`18402/tcp` allowed only from LAN and `tailscale0`. Verify from build-1:

```sh
tailscale ping vpnctld
NO_PROXY="${NO_PROXY:+$NO_PROXY,}vpnctld" no_proxy="${no_proxy:+$no_proxy,}vpnctld" \
  curl -fsS http://vpnctld:18402/api/v1/health
```

## One-time restricted transport provisioning

Provision only after the scripts are merged, using their exact bytes from protected `master`:

1. Create system user `uapdeploy` with no password and no interactive shell; create
   `/var/lib/uapdeploy/incoming` owned by it and `/var/lib/uapdeploy/build` writable only by root plus the existing
   unprivileged build user as required by the installer.
2. Install `infra/ops/uap-deploy-vpnctld-dispatch.sh` as `/usr/local/libexec/uap-deploy-vpnctld-dispatch` and
   `infra/ops/uap-install-vpnctld.sh` as `/usr/local/sbin/uap-install-vpnctld`, both root-owned and not writable by
   `uapdeploy` or `user`.
3. Generate `/home/uap/.ssh/vpnctld_deploy` on build-1 with mode `0600`. The target `authorized_keys` line must use
   `restrict,command="/usr/local/libexec/uap-deploy-vpnctld-dispatch"`; do not grant a shell, forwarding or PTY.
4. Sudoers grants `uapdeploy` only the exact root helper, with no environment preservation. Keep the key value and
   public-key line out of the repository and logs.
5. Install `infra/ops/uap-deploy-vpnctld.sh` on build-1 through the existing Flow installer and pin `vpnctld` in the
   deploy key's `known_hosts`.

## Remote activation and rollback

The forced command accepts only `upload REVISION SHA256` or `deploy REVISION SHA256`. It caps archives at 128 MiB,
checks their SHA-256 and passes only the exact staged path to the root helper. The helper builds as the existing
unprivileged `user`, saves the old daemon/assets, installs the new payload, restarts the fixed service and checks local
health. Any activation failure restores both old components and restarts the previous service. A successful record is
`REVISION|INSTALLED_PAYLOAD_SHA256`; replay verifies the current payload and health before returning success.

## Acceptance

Before claiming the deploy boundary complete, an ordinary Workspace or Telegram goal for `vpnctl` must automatically
pass coding, tests, independent exact-SHA review, PR/CI, exact merge, fresh-main verification, deployment and cleanup.
The final shared projection must name `vpnctl-production`, the exact deployed revision and deployment verification.
Also fault-test one failed activation in a disposable copy or controlled wrapper and prove the previous service remains
healthy; do not deliberately break the live daemon merely to exercise rollback.
