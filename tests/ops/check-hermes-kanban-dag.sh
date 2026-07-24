#!/bin/sh
set -eu

hermes_bin=${HERMES_BIN:-hermes}
command -v "$hermes_bin" >/dev/null 2>&1 || {
  echo "Hermes executable not found: $hermes_bin" >&2
  exit 1
}

home=$(mktemp -d "${TMPDIR:-/tmp}/uap-kanban-dag.XXXXXX")
trap 'rm -rf "$home"' EXIT HUP INT TERM
export HERMES_HOME=$home
export HERMES_KANBAN_DB=$home/kanban.db

"$hermes_bin" kanban boards create dag-canary >/dev/null
"$hermes_bin" kanban --board dag-canary swarm \
  "Prove dependency promotion" \
  --worker worker-a:"Worker A" \
  --worker worker-b:"Worker B" \
  --verifier verifier \
  --synthesizer synthesizer \
  --tenant dag-canary \
  --idempotency-key dag-canary \
  --json >/dev/null

python3 - "$HERMES_KANBAN_DB" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
connection.row_factory = sqlite3.Row
tasks = {
    row["id"]: dict(row)
    for row in connection.execute("SELECT id, title, status, assignee FROM tasks")
}
edges = {
    (row["parent_id"], row["child_id"])
    for row in connection.execute("SELECT parent_id, child_id FROM task_links")
}

assert len(tasks) == 5
assert len(edges) == 5
root = next(task for task in tasks.values() if task["title"].startswith("Swarm:"))
workers = [task for task in tasks.values() if task["title"] in {"Worker A", "Worker B"}]
verifier = next(task for task in tasks.values() if task["assignee"] == "verifier")
synthesizer = next(task for task in tasks.values() if task["assignee"] == "synthesizer")
assert root["status"] == "done"
assert len(workers) == 2 and all(task["status"] == "ready" for task in workers)
assert verifier["status"] == synthesizer["status"] == "todo"
assert all((root["id"], task["id"]) in edges for task in workers)
assert all((task["id"], verifier["id"]) in edges for task in workers)
assert (verifier["id"], synthesizer["id"]) in edges
print("hermes-kanban-dag-ok tasks=5 edges=5 ready_workers=2")
PY
