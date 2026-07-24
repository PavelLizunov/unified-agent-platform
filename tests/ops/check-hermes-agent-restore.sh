#!/bin/sh
# Restore the latest R2 Hermes archive into a disposable PVC and validate it.
set -eu

# Closed restore-mode selector: resolves the hermes image for a given mode.
# Sourced by static tests (with _HERMES_RESTORE_SOURCE_ONLY=1) without reaching
# kubectl.  Only two modes accepted; anything else fails before any side effect.
select_hermes_image() {
  _mode="${1:-}"
  case "$_mode" in
    "")
      echo "nousresearch/hermes-agent@sha256:f7b35053268f532f98955195c909f15a230470fbcbdacaa9fdecb95707dad04a"
      ;;
    v0.18-rollback)
      echo "nousresearch/hermes-agent@sha256:b6c019227889e6675424a2b6223b2cafdd36bf7d1048d1ddd8e043b880d6cc0f"
      ;;
    *)
      echo "FATAL: HERMES_RESTORE_MODE must be empty or v0.18-rollback" >&2
      return 1 ;;
  esac
}

# When sourced for testing, export only the selector function.
if [ "${_HERMES_RESTORE_SOURCE_ONLY:-}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

namespace="${UAP_NAMESPACE:-uap-system}"
suffix="$(date +%s)-$$"
pvc="hermes-restore-canary-$suffix"
job="hermes-restore-canary-$suffix"
hermes_image="$(select_hermes_image "${HERMES_RESTORE_MODE:-}")" || exit 1
rclone_image="rclone/rclone@sha256:623378ad0ff3ebd5cebf77720843c0e02edfe46e2d5b5ac6bed54c6371780dfb"

cleanup() {
  kubectl -n "$namespace" delete job "$job" --ignore-not-found --wait=false >/dev/null
  kubectl -n "$namespace" delete pvc "$pvc" --ignore-not-found --wait=false >/dev/null
}
trap cleanup EXIT HUP INT TERM

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $pvc
  namespace: $namespace
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: local-path
  resources:
    requests:
      storage: 2Gi
---
apiVersion: batch/v1
kind: Job
metadata:
  name: $job
  namespace: $namespace
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 900
  template:
    spec:
      restartPolicy: Never
      nodeSelector:
        kubernetes.io/hostname: uap-home-2
      securityContext:
        fsGroup: 10000
      initContainers:
        - name: fetch
          image: $rclone_image
          command: ["/bin/sh", "-c"]
          args:
            - |
              set -eu
              export RCLONE_CONFIG=/cfg/rclone.conf
              dst="r2:uap-k3s-snapshots/hermes-agent-backup/"
              latest=\$(rclone lsf "\$dst" | grep -E '^hermes-backup-.*\.zip$' | sort | tail -n 1)
              [ -n "\$latest" ] || { echo "FATAL: no Hermes backup in R2"; exit 1; }
              rclone copyto "\$dst\$latest" /work/backup.zip --s3-no-check-bucket
          volumeMounts:
            - { name: work, mountPath: /work }
            - { name: r2cfg, mountPath: /cfg, readOnly: true }
        - name: restore
          image: $hermes_image
          command: ["/bin/sh", "-c"]
          args:
            - |
              set -eu
              env HOME=/restore HERMES_HOME=/restore hermes import /work/backup.zip --force
          volumeMounts:
            - { name: work, mountPath: /work, readOnly: true }
            - { name: restore, mountPath: /restore }
      containers:
        - name: verify
          image: $hermes_image
          securityContext:
            runAsUser: 0
          command: ["/bin/sh", "-c"]
          args:
            - |
              set -eu
              /opt/hermes/.venv/bin/python - <<'PY'
              import sqlite3
              from pathlib import Path

              root = Path("/restore")
              required = ("state.db", "auth.json", "missions-v1.sqlite3")
              missing = [name for name in required if not (root / name).is_file()]
              if missing:
                  raise SystemExit(f"missing restored files: {missing}")
              for name in ("state.db", "missions-v1.sqlite3"):
                  path = root / name
                  with sqlite3.connect(
                      f"{path.as_uri()}?mode=ro&immutable=1", uri=True
                  ) as connection:
                      check = [row[0] for row in connection.execute("PRAGMA quick_check")]
                      if check != ["ok"]:
                          raise SystemExit(f"{name} quick_check failed: {check[:3]}")
              with sqlite3.connect(root / "missions-v1.sqlite3") as connection:
                  count = connection.execute(
                      "SELECT count(*) FROM mission_events"
                  ).fetchone()[0]
              print(f"hermes-restore-canary-ok mission_events={count}")
              PY
          volumeMounts:
            - { name: restore, mountPath: /restore, readOnly: true }
      volumes:
        - name: work
          emptyDir: { sizeLimit: 1Gi }
        - name: restore
          persistentVolumeClaim:
            claimName: $pvc
        - name: r2cfg
          secret:
            secretName: hermes-agent-backup-r2
EOF

attempt=0
while [ "$attempt" -lt 180 ]; do
  succeeded="$(kubectl -n "$namespace" get job "$job" -o jsonpath='{.status.succeeded}' 2>/dev/null || true)"
  failed="$(kubectl -n "$namespace" get job "$job" -o jsonpath='{.status.failed}' 2>/dev/null || true)"
  [ "$succeeded" = "1" ] && break
  if [ -n "$failed" ] && [ "$failed" -ge 1 ]; then
    kubectl -n "$namespace" logs "job/$job" --all-containers --prefix || true
    echo "FATAL: disposable restore Job failed" >&2
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 5
done
[ "$succeeded" = "1" ] || { echo "FATAL: disposable restore Job timed out" >&2; exit 1; }
kubectl -n "$namespace" logs "job/$job" -c verify
kubectl -n "$namespace" logs "job/$job" -c verify | grep -q "hermes-restore-canary-ok"
echo "hermes-agent-restore-ok"
