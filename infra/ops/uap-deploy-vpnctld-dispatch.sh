#!/bin/sh
# ForcedCommand for the single build-1 deploy key on vpnctld.
set -eu
set -f
umask 077

set -- ${SSH_ORIGINAL_COMMAND:-}
[ "$#" -eq 3 ] || { printf '%s\n' "vpnctld-dispatch: invalid command" >&2; exit 2; }
ACTION=$1
REVISION=$2
ARCHIVE_SHA=$3
printf '%s' "$REVISION" | grep -Eq '^[0-9a-f]{40,64}$' || exit 2
printf '%s' "$ARCHIVE_SHA" | grep -Eq '^[0-9a-f]{64}$' || exit 2

INCOMING=/var/lib/uapdeploy/incoming
ARCHIVE=$INCOMING/$REVISION.tar
case "$ACTION" in
  upload)
    TMP=$ARCHIVE.tmp.$$
    trap 'rm -f "$TMP"' EXIT HUP INT TERM
    dd of="$TMP" bs=1M count=129 iflag=fullblock 2>/dev/null
    [ "$(wc -c < "$TMP")" -le 134217728 ] || exit 2
    [ "$(sha256sum "$TMP" | awk '{print $1}')" = "$ARCHIVE_SHA" ] || exit 2
    chmod 0600 "$TMP"
    mv -f "$TMP" "$ARCHIVE"
    ;;
  deploy)
    [ -f "$ARCHIVE" ] && [ ! -L "$ARCHIVE" ] || exit 2
    exec sudo -n /usr/local/sbin/uap-install-vpnctld \
      --archive "$ARCHIVE" --revision "$REVISION" --archive-sha "$ARCHIVE_SHA"
    ;;
  *) exit 2 ;;
esac
