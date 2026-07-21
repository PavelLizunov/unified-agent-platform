# build-1: dedicated worktree storage volume

Isolated ext4 volume for delivery coordinator worktrees on `uap-build-1`.
Prevents root-filesystem exhaustion from Rust build artifacts, abandoned temp
files and swarm-out growth.

**Physical mount deployment: complete (2026-07-21).** Software 40 GiB
minimum-free guard: pending merge/deploy of this patch.

## Current state (verified 2026-07-21)

```
/dev/sdb1  ext4  UUID=f76e50ea-4b2f-46b5-91be-695f1456756a
  mounted rw,noatime at /home/uap/worktrees
  owner uap:uap, mode 0750
  196G total, 6.8G used, 179G available (4%)

/dev/sda1  root
  97G total, 46G used, 52G available (47%)
```

Post-cutover timer ticks for `vpnctl`, `ninitux-landing` and `vpnrouter`
succeeded. Two old profiles have unrelated pre-existing contract failures
(not a storage regression).

## /etc/fstab entry

```
UUID=f76e50ea-4b2f-46b5-91be-695f1456756a /home/uap/worktrees ext4 defaults,noatime 0 2
```

No `nofail`. If the mount is absent the boot will drop to emergency; this is
intentional — the coordinator must not silently run on the root filesystem.

## Systemd mount condition

The repo base unit (`tools/swarm/systemd/hermes-delivery-coordinator@.service`)
includes `ConditionPathIsMountPoint=/home/uap/worktrees` in `[Unit]`.
The 2026-07-21 production deployment also has a manually installed drop-in
(`~/.config/systemd/user/hermes-delivery-coordinator@.service.d/20-worktree-mount.conf`)
with the same condition; the duplicate is harmless and will be superseded
when the repo unit is next installed. Future installer runs persist the
condition from the repo base unit. `/etc/fstab` is **not** repo-managed.

If the mount is missing the service is skipped (not failed) and the timer
retries on the next tick. A manual `python3 delivery_coordinator.py`
invocation bypasses the systemd condition; the 40 GiB software check is a
free-space reserve, **not** a mount-identity guard — the coordinator code
does not verify that `worktree_root` is a separate mount.

Inspect and validate:

```bash
systemctl --user cat hermes-delivery-coordinator@vpnctl.service
systemd-analyze --user condition 'ConditionPathIsMountPoint=/home/uap/worktrees'
```

## Coordinator disk-space guard

- `_check_disk_space()` calls `shutil.disk_usage(worktree_root)`.
- Free < 40 GiB → `disk_space_wait` durable state with exact Kanban claim
  parking; timer retries with exponential backoff (5 min → 1 h cap).
- Guard points: before handoff/claim, before author, before reviewer,
  before post-verify checks.
- `owner_action_required=false`; notice is bounded/redacted, no raw paths,
  no free-byte telemetry in the event identity.
- Quality counters, model route and schema are **not** changed.
- No automatic `rm`/`reset`/`clean` of worktrees or data.
- On recovery the exact parked Kanban run is reclaimed with provenance
  validation before delivery resumes.

## Verification

```bash
findmnt /home/uap/worktrees
findmnt --verify

python3 -c "import shutil; u=shutil.disk_usage('/home/uap/worktrees'); print(f'free={u.free/2**30:.1f} GiB')"

systemctl --user list-timers --all 'hermes-delivery-coordinator@*.timer'
```

## Recovery from a full root

Do **not** use `mv /home/uap/worktrees/* …` — it misses dotfiles and can
cross filesystem boundaries unsafely.

1. **Stop all coordinator timers**:
   ```bash
   systemctl --user stop --all 'hermes-delivery-coordinator@*.timer'
   systemctl --user list-timers --all 'hermes-delivery-coordinator@*.timer'
   ```
   Commands without `--all` did not work; use an explicit unit list as a
   fallback.
2. **Verify no active coordinator process**:
   ```bash
   pgrep -af delivery_coordinator   # must return nothing
   ```
3. **Copy data with rsync** (preserves hardlinks, permissions, xattrs):
   ```bash
   sudo mount UUID=f76e50ea-4b2f-46b5-91be-695f1456756a /mnt/new-worktrees
   nice -n 19 rsync -aHAX --info=progress2 /home/uap/worktrees/ /mnt/new-worktrees/
   ```
4. **Final sync**:
   ```bash
   nice -n 19 rsync -aHAX --delete /home/uap/worktrees/ /mnt/new-worktrees/
   ```
5. **Verify equality before destructive cleanup** (dry-run first):
   ```bash
   rsync -aHAX --delete --dry-run --itemize-changes /home/uap/worktrees/ /mnt/new-worktrees/
   # must show no differences
   ```
6. **Switch the mount**:
   ```bash
   sudo umount /mnt/new-worktrees
   sudo mount UUID=f76e50ea-4b2f-46b5-91be-695f1456756a /home/uap/worktrees
   sudo chown uap:uap /home/uap/worktrees
   sudo chmod 0750 /home/uap/worktrees
   ```
7. **Verify**:
   ```bash
   findmnt /home/uap/worktrees
   python3 -c "import shutil; u=shutil.disk_usage('/home/uap/worktrees'); print(f'free={u.free/2**30:.1f} GiB')"
   ```
8. **Resume timers and confirm successful ticks**:
   ```bash
   systemctl --user start --all 'hermes-delivery-coordinator@*.timer'
   systemctl --user list-timers --all 'hermes-delivery-coordinator@*.timer'
   ```
   Destructive cleanup of the old data is gated: only after dry-run
   equality and at least one successful timer tick per active profile.
