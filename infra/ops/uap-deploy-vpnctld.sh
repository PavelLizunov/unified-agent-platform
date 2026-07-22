#!/bin/sh
# Fixed build-1 side of the vpnctld deployment protocol. The coordinator supplies
# only an already verified checkout and its exact merged revision.
set -eu
umask 077

SOURCE=
REVISION=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --source) [ "$#" -ge 2 ] || exit 2; SOURCE=$2; shift 2 ;;
    --revision) [ "$#" -ge 2 ] || exit 2; REVISION=$2; shift 2 ;;
    *) printf '%s\n' "vpnctld-deploy: invalid argument" >&2; exit 2 ;;
  esac
done

case "$SOURCE" in
  /home/uap/worktrees/vpnctl-registered-v4/verify-*) ;;
  *) printf '%s\n' "vpnctld-deploy: source is outside the approved verify root" >&2; exit 2 ;;
esac
printf '%s' "$REVISION" | grep -Eq '^[0-9a-f]{40,64}$' || {
  printf '%s\n' "vpnctld-deploy: invalid revision" >&2; exit 2;
}
[ -d "$SOURCE/.git" ] || [ -f "$SOURCE/.git" ] || {
  printf '%s\n' "vpnctld-deploy: source is not a Git worktree" >&2; exit 2;
}
[ "$(git -C "$SOURCE" rev-parse HEAD)" = "$REVISION" ] || {
  printf '%s\n' "vpnctld-deploy: verify HEAD changed" >&2; exit 2;
}
[ -z "$(git -C "$SOURCE" status --porcelain=v1 --untracked-files=all)" ] || {
  printf '%s\n' "vpnctld-deploy: verify worktree is not clean" >&2; exit 2;
}

TMP=${TMPDIR:-/tmp}/uap-vpnctld-${REVISION}-$$.tar
trap 'rm -f "$TMP"' EXIT HUP INT TERM
git -C "$SOURCE" archive --format=tar --output="$TMP" "$REVISION"
[ "$(wc -c < "$TMP")" -le 134217728 ] || {
  printf '%s\n' "vpnctld-deploy: source archive exceeds 128 MiB" >&2; exit 2;
}
ARCHIVE_SHA=$(sha256sum "$TMP" | awk '{print $1}')

SSH="ssh -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=15 -i /home/uap/.ssh/vpnctld_deploy uapdeploy@vpnctld"
# shellcheck disable=SC2086
$SSH "upload $REVISION $ARCHIVE_SHA" < "$TMP" >/dev/null
# The remote helper emits exactly one bounded JSON result on stdout.
# shellcheck disable=SC2086
$SSH "deploy $REVISION $ARCHIVE_SHA"
