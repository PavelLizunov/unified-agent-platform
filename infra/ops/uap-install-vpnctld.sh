#!/bin/sh
# Root-only, closed installer for vpnctld. It builds unprivileged, installs one
# fixed service payload, verifies health, and rolls back on any failed activation.
set -eu
umask 077

ARCHIVE=
REVISION=
ARCHIVE_SHA=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --archive) [ "$#" -ge 2 ] || exit 2; ARCHIVE=$2; shift 2 ;;
    --revision) [ "$#" -ge 2 ] || exit 2; REVISION=$2; shift 2 ;;
    --archive-sha) [ "$#" -ge 2 ] || exit 2; ARCHIVE_SHA=$2; shift 2 ;;
    *) printf '%s\n' "vpnctld-install: invalid argument" >&2; exit 2 ;;
  esac
done

printf '%s' "$REVISION" | grep -Eq '^[0-9a-f]{40,64}$' || exit 2
printf '%s' "$ARCHIVE_SHA" | grep -Eq '^[0-9a-f]{64}$' || exit 2
[ "$ARCHIVE" = "/var/lib/uapdeploy/incoming/$REVISION.tar" ] || exit 2
[ -f "$ARCHIVE" ] && [ ! -L "$ARCHIVE" ] || exit 2
[ "$(sha256sum "$ARCHIVE" | awk '{print $1}')" = "$ARCHIVE_SHA" ] || exit 2

exec 9>/run/lock/uap-vpnctld-deploy.lock
flock -x 9

STATE_DIR=/var/lib/vpnctl
RECORD=$STATE_DIR/uap-deployment-v1
HEALTH=http://127.0.0.1:18402/api/v1/health
health_ready() {
  curl -fsS --retry 12 --retry-connrefused --retry-delay 2 \
    --connect-timeout 2 --max-time 40 "$HEALTH" >/dev/null
}
cleanup_deploy_residue() {
  rm -f "$ARCHIVE"
  find /opt/vpnctl -mindepth 1 -maxdepth 1 -type d \
    -name '.uap-rollback.*' -exec rm -rf -- {} +
}
installed_artifact_sha() {
  tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
    -cf - -C /opt/vpnctl vpnctld assets | sha256sum | awk '{print $1}'
}
if [ -f "$RECORD" ]; then
  IFS='|' read -r OLD_REV OLD_ARTIFACT < "$RECORD" || true
  if [ "$OLD_REV" = "$REVISION" ] && [ -n "$OLD_ARTIFACT" ] && \
     [ "$(installed_artifact_sha)" = "$OLD_ARTIFACT" ] && \
     systemctl is-active --quiet vpnctld && curl -fsS --max-time 10 "$HEALTH" >/dev/null; then
    cleanup_deploy_residue
    printf '{"schema_version":1,"status":"verified","driver":"vpnctld-systemd-v1","environment":"vpnctl-production","target":"vpnctld","health_url":"http://vpnctld:18402/api/v1/health","deployed_revision":"%s","artifact_sha256":"%s"}\n' "$REVISION" "$OLD_ARTIFACT"
    exit 0
  fi
fi

BUILD_ROOT=/var/lib/uapdeploy/build
BUILD=$BUILD_ROOT/$REVISION
rm -rf "$BUILD.tmp" "$BUILD"
mkdir -p "$BUILD.tmp"
tar -xf "$ARCHIVE" --no-same-owner --no-same-permissions -C "$BUILD.tmp"
mv "$BUILD.tmp" "$BUILD"
chown -R user:user "$BUILD"
runuser -u user -- env HOME=/home/user CARGO_HOME=/home/user/.cargo \
  /home/user/.cargo/bin/cargo build --locked --release -p vpnctld \
  --manifest-path "$BUILD/Cargo.toml"

NEW_BIN=$BUILD/target/release/vpnctld
[ -x "$NEW_BIN" ] || { printf '%s\n' "vpnctld-install: build produced no daemon" >&2; exit 2; }
[ -d "$BUILD/daemon/assets" ] || { printf '%s\n' "vpnctld-install: assets are missing" >&2; exit 2; }
BACKUP=$(mktemp -d /opt/vpnctl/.uap-rollback.XXXXXX)
cp -a /opt/vpnctl/vpnctld "$BACKUP/vpnctld"
cp -a /opt/vpnctl/assets "$BACKUP/assets"
install_binary() {
  SOURCE=$1
  TEMP_BINARY=/opt/vpnctl/.vpnctld.uap.$$
  rm -f "$TEMP_BINARY"
  install -o root -g root -m 0755 "$SOURCE" "$TEMP_BINARY" || return 1
  mv -f "$TEMP_BINARY" /opt/vpnctl/vpnctld
}
restore_backup() {
  trap - EXIT HUP INT TERM
  systemctl stop vpnctld || true
  install_binary "$BACKUP/vpnctld" || return 1
  rm -rf /opt/vpnctl/assets.restore
  cp -a "$BACKUP/assets" /opt/vpnctl/assets.restore || return 1
  rm -rf /opt/vpnctl/assets
  mv /opt/vpnctl/assets.restore /opt/vpnctl/assets || return 1
  systemctl start vpnctld || return 1
  health_ready
}
rollback_exit() {
  STATUS=$?
  trap - EXIT HUP INT TERM
  restore_backup || true
  exit "$STATUS"
}
rollback_signal() {
  trap - EXIT HUP INT TERM
  restore_backup || true
  exit 2
}
trap rollback_exit EXIT
trap rollback_signal HUP INT TERM

rm -rf /opt/vpnctl/assets.new
cp -a "$BUILD/daemon/assets" /opt/vpnctl/assets.new
chown -R root:root /opt/vpnctl/assets.new
find /opt/vpnctl/assets.new -type d -exec chmod 0755 {} +
find /opt/vpnctl/assets.new -type f -exec chmod 0644 {} +
systemctl stop vpnctld
install_binary "$NEW_BIN"
rm -rf /opt/vpnctl/assets
mv /opt/vpnctl/assets.new /opt/vpnctl/assets
if ! systemctl start vpnctld || ! health_ready; then
  if restore_backup; then
    rm -rf "$BACKUP" "$BUILD"
    rm -f "$ARCHIVE"
    printf '%s\n' "vpnctld-install: activation failed and was rolled back" >&2
  else
    printf '%s\n' "vpnctld-install: activation failed and rollback verification failed" >&2
  fi
  exit 2
fi
trap - EXIT HUP INT TERM
ARTIFACT_SHA=$(installed_artifact_sha)
printf '%s|%s\n' "$REVISION" "$ARTIFACT_SHA" > "$RECORD.tmp"
chown root:root "$RECORD.tmp"
chmod 0644 "$RECORD.tmp"
mv -f "$RECORD.tmp" "$RECORD"
rm -rf "$BACKUP" "$BUILD"
cleanup_deploy_residue
printf '{"schema_version":1,"status":"verified","driver":"vpnctld-systemd-v1","environment":"vpnctl-production","target":"vpnctld","health_url":"http://vpnctld:18402/api/v1/health","deployed_revision":"%s","artifact_sha256":"%s"}\n' "$REVISION" "$ARTIFACT_SHA"
