#!/usr/bin/env python3
"""UAP Engineering Knowledge System — canonical registry + local vector retrieval.

Design (docs: runbooks/knowledge-system.md; research: Drive doc 2026-07-09):
  - Source of truth = SQLite canonical registry (records + documents + append-only audit),
    NOT the vector index. The vector side (sqlite-vec) is a derived, rebuildable index.
  - Default retrieval sees only ACTIVE knowledge (lifecycle-filtered); history on demand.
  - Local embeddings only (fastembed/ONNX, multilingual for RU+EN). No cloud calls.
  - Documents are DATA, not instructions (prompt-injection rule enforced by consumers).

Deps (venv on build-1): fastembed, sqlite-vec, pyyaml.  Stdlib otherwise.
"""

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import sqlite3
import struct
import sys
from pathlib import Path

HOME = Path(os.environ.get("KNOWLEDGE_HOME", str(Path.home() / "knowledge")))
DB_PATH = HOME / "knowledge.db"
MODEL_NAME = os.environ.get("KNOWLEDGE_MODEL", "intfloat/multilingual-e5-large")
CHUNK_TARGET = 1600  # chars; header-aware chunker below
DEFAULT_K = 8

# Lifecycle (from the research doc, section 5)
STATUSES = [
    "hypothesis", "needs_verification", "confirmed", "patch_ready", "implemented",
    "validation_pending", "confirmed_fixed", "resolved", "superseded", "rejected",
    "obsolete", "regression_watch",
]
TRANSITIONS = {
    "hypothesis": ["needs_verification", "rejected"],
    "needs_verification": ["confirmed", "rejected"],
    "confirmed": ["patch_ready", "superseded", "obsolete"],
    "patch_ready": ["implemented", "obsolete"],
    "implemented": ["validation_pending"],
    "validation_pending": ["confirmed_fixed", "needs_verification"],
    "confirmed_fixed": ["resolved"],
    "resolved": ["regression_watch"],
    "regression_watch": ["confirmed", "resolved"],
}
# Transitions that require an explicit human --approve (doc section 5)
APPROVAL_REQUIRED = {"confirmed_fixed", "resolved", "rejected", "superseded"}
# Default retrieval: active statuses only (doc section 6)
ACTIVE_STATUSES = ["confirmed", "patch_ready", "implemented", "validation_pending"]

# ---------------------------------------------------------------- redaction --
SECRET_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"sk-[A-Za-z0-9\-_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"age1[a-z0-9]{50,}"),
    re.compile(r"(vless|ss|vmess|trojan)://\S+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{25,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"(?i)\b(password|passwd|api_key|apikey|secret|token|auth[_-]?key)\b(\s*[:=]\s*)(\"[^\"]{6,}\"|'[^']{6,}'|[^\s\"',;]{8,})"),
]
BLOCK_MARKERS = ["-----BEGIN", "PRIVATE KEY"]  # both present => skip whole file


def redact(text: str):
    """Return (sanitized_text, n_redactions). Never index raw secrets."""
    n = 0
    for pat in SECRET_PATTERNS:
        def _sub(m):
            nonlocal n
            n += 1
            if m.lastindex and m.lastindex >= 2:  # key: value form — keep the key
                return m.group(1) + m.group(2) + "[REDACTED]"
            return "[REDACTED]"
        text = pat.sub(_sub, text)
    return text, n


def is_blocked(text: str) -> bool:
    return all(m in text for m in BLOCK_MARKERS)


# ------------------------------------------------------------------ chunker --
def chunk_markdown(text: str, ctx_label: str):
    """Header-aware greedy chunker: split on #/##/### headings, pack ~CHUNK_TARGET chars.
    Each chunk is prefixed with its breadcrumb so embeddings carry context."""
    lines = text.splitlines()
    sections, cur, crumb = [], [], ""
    for ln in lines:
        m = re.match(r"^(#{1,3})\s+(.*)", ln)
        if m:
            if cur:
                sections.append((crumb, "\n".join(cur).strip()))
            crumb, cur = m.group(2).strip(), []
        else:
            cur.append(ln)
    if cur:
        sections.append((crumb, "\n".join(cur).strip()))

    chunks, buf, buf_crumbs = [], "", []
    def flush():
        nonlocal buf, buf_crumbs
        body = buf.strip()
        if body:
            head = f"[{ctx_label}" + (f" > {' / '.join(c for c in buf_crumbs if c)}" if any(buf_crumbs) else "") + "]\n"
            chunks.append(head + body)
        buf, buf_crumbs = "", []

    for crumb, body in sections:
        if not body:
            continue
        # split oversized sections on blank lines
        parts = [body] if len(body) <= CHUNK_TARGET * 1.5 else re.split(r"\n\s*\n", body)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if buf and len(buf) + len(part) > CHUNK_TARGET:
                flush()
            buf += ("\n\n" if buf else "") + part
            if crumb not in buf_crumbs:
                buf_crumbs.append(crumb)
    flush()
    return chunks


# ---------------------------------------------------------------- embeddings --
_model = None

def get_model():
    global _model
    if _model is None:
        import warnings
        warnings.filterwarnings("ignore", category=UserWarning)  # fastembed pooling-change notice — noise for CLI consumers
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(HOME / "models"))
    return _model


def embed_texts(texts, kind="passage"):
    """e5 models need 'query: '/'passage: ' prefixes; harmless no-op for others."""
    if "e5" in MODEL_NAME.lower():
        texts = [f"{kind}: {t}" for t in texts]
    return [list(map(float, v)) for v in get_model().embed(texts)]


def vec_blob(v):
    return struct.pack(f"{len(v)}f", *v)


# ----------------------------------------------------------------------- db --
def db_connect():
    HOME.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.enable_load_extension(True)
    import sqlite_vec
    sqlite_vec.load(con)
    con.enable_load_extension(False)
    con.execute("PRAGMA journal_mode=WAL")
    return con


def db_init(con, dim):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS documents(
      id INTEGER PRIMARY KEY, path TEXT UNIQUE, project TEXT, source_type TEXT,
      sha256 TEXT, version INTEGER DEFAULT 1, mtime REAL, status TEXT DEFAULT 'active',
      redactions INTEGER DEFAULT 0, indexed_at TEXT);
    CREATE TABLE IF NOT EXISTS records(
      id TEXT PRIMARY KEY, title TEXT, project TEXT, type TEXT, status TEXT,
      priority TEXT, confidence REAL, created_at TEXT, updated_at TEXT,
      created_by TEXT, source_uri TEXT, retrieval_scope TEXT DEFAULT 'active',
      superseded_by TEXT, body TEXT, yaml TEXT);
    CREATE TABLE IF NOT EXISTS chunks(
      id INTEGER PRIMARY KEY, kind TEXT, ref TEXT, chunk_index INTEGER,
      project TEXT, status TEXT, retrieval_scope TEXT, title TEXT,
      sha256 TEXT, text TEXT);
    CREATE TABLE IF NOT EXISTS audit(
      id INTEGER PRIMARY KEY, ts TEXT, actor TEXT, action TEXT, ref TEXT, details TEXT);
    CREATE INDEX IF NOT EXISTS idx_chunks_ref ON chunks(kind, ref);
    """)
    con.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(embedding float[{dim}])")
    cur_model = con.execute("SELECT value FROM meta WHERE key='embedding_model'").fetchone()
    if cur_model and cur_model[0] != MODEL_NAME:
        sys.exit(f"DB was embedded with {cur_model[0]}, current model {MODEL_NAME}. Run `reindex` or set KNOWLEDGE_MODEL.")
    con.execute("INSERT OR REPLACE INTO meta VALUES('embedding_model', ?)", (MODEL_NAME,))
    con.execute("INSERT OR REPLACE INTO meta VALUES('embedding_dim', ?)", (str(dim),))
    con.commit()


def audit(con, actor, action, ref, details=""):
    con.execute("INSERT INTO audit(ts, actor, action, ref, details) VALUES (?,?,?,?,?)",
                (dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), actor, action, ref,
                 details if isinstance(details, str) else json.dumps(details, ensure_ascii=False)))


def load_ragignore(root: Path):
    pats = [".git/*", "*.sops.yaml", "*.env", "*.key", "node_modules/*"]
    f = root / ".ragignore"
    if f.exists():
        pats += [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]
    return pats


def ignored(rel: str, pats):
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p.rstrip("/*") + "/*") for p in pats)


def replace_chunks(con, kind, ref, texts, project, status, scope, title):
    """Delete + reinsert chunks and vectors for one doc/record (idempotent)."""
    old = [r[0] for r in con.execute("SELECT id FROM chunks WHERE kind=? AND ref=?", (kind, ref))]
    for cid in old:
        con.execute("DELETE FROM vec_chunks WHERE rowid=?", (cid,))
    con.execute("DELETE FROM chunks WHERE kind=? AND ref=?", (kind, ref))
    if not texts:
        return 0
    vecs = embed_texts(texts)
    for i, (t, v) in enumerate(zip(texts, vecs)):
        cur = con.execute(
            "INSERT INTO chunks(kind, ref, chunk_index, project, status, retrieval_scope, title, sha256, text) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (kind, ref, i, project, status, scope, title,
             hashlib.sha256(t.encode()).hexdigest(), t))
        con.execute("INSERT INTO vec_chunks(rowid, embedding) VALUES (?,?)", (cur.lastrowid, vec_blob(v)))
    return len(texts)


# --------------------------------------------------------------------- sync --
def cmd_sync(args):
    root = Path(args.repo).resolve()
    pats = load_ragignore(root)
    con = db_connect()
    dim = len(embed_texts(["probe"])[0])
    db_init(con, dim)
    seen, added, updated, skipped, blocked = set(), 0, 0, 0, 0
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if ignored(rel, pats):
            continue
        seen.add(rel)
        raw = p.read_text(encoding="utf-8", errors="replace")
        if is_blocked(raw):
            blocked += 1
            audit(con, "sync", "blocked_secret_file", rel)
            continue
        text, n_red = redact(raw)
        sha = hashlib.sha256(text.encode()).hexdigest()
        row = con.execute("SELECT id, sha256, version FROM documents WHERE path=?", (rel,)).fetchone()
        if row and row[1] == sha:
            skipped += 1
            continue
        chunks = chunk_markdown(text, rel)
        if row:
            con.execute("UPDATE documents SET sha256=?, version=?, mtime=?, redactions=?, status='active', indexed_at=? WHERE path=?",
                        (sha, row[2] + 1, p.stat().st_mtime, n_red, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), rel))
            updated += 1
            audit(con, "sync", "doc_updated", rel, {"version": row[2] + 1, "chunks": len(chunks), "redactions": n_red})
        else:
            con.execute("INSERT INTO documents(path, project, source_type, sha256, mtime, redactions, indexed_at) VALUES (?,?,?,?,?,?,?)",
                        (rel, args.project, "repo_file", sha, p.stat().st_mtime, n_red,
                         dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")))
            added += 1
            audit(con, "sync", "doc_added", rel, {"chunks": len(chunks), "redactions": n_red})
        replace_chunks(con, "doc", rel, chunks, args.project, "active", "active", rel)
        con.commit()
    # mark deleted files' docs superseded (keep chunks out of default retrieval)
    gone = 0
    for (rel,) in con.execute("SELECT path FROM documents WHERE status='active' AND project=?", (args.project,)):
        if rel not in seen:
            con.execute("UPDATE documents SET status='superseded' WHERE path=?", (rel,))
            con.execute("UPDATE chunks SET retrieval_scope='archive', status='superseded' WHERE kind='doc' AND ref=?", (rel,))
            audit(con, "sync", "doc_gone", rel)
            gone += 1
    con.commit()
    print(f"sync done: +{added} added, ~{updated} updated, ={skipped} unchanged, x{blocked} blocked(secrets), -{gone} gone")


# -------------------------------------------------------------------- query --
def cmd_query(args):
    con = db_connect()
    dim = int(con.execute("SELECT value FROM meta WHERE key='embedding_dim'").fetchone()[0])
    qv = embed_texts([args.text], kind="query")[0]
    assert len(qv) == dim, "dim mismatch — reindex needed"
    # over-fetch KNN, then filter by payload in SQL (sqlite-vec MATCH has no payload filters)
    rows = con.execute(
        "SELECT rowid, distance FROM vec_chunks WHERE embedding MATCH ? AND k = ?",
        (vec_blob(qv), max(args.k * 12, 60))).fetchall()
    if not rows:
        print("index empty — run sync first")
        return
    ids = [r[0] for r in rows]
    dist = {r[0]: r[1] for r in rows}
    ph = ",".join("?" * len(ids))
    sql = f"SELECT id, kind, ref, title, status, retrieval_scope, project, text FROM chunks WHERE id IN ({ph})"
    params = list(ids)
    if args.project:
        sql += " AND project=?"
        params.append(args.project)
    if args.scope != "all":
        sql += " AND retrieval_scope=?"
        params.append(args.scope)
    if not args.historical:
        # docs: status active; records: ACTIVE_STATUSES (doc section 6)
        sql += f" AND (kind='doc' AND status='active' OR kind='record' AND status IN ({','.join('?'*len(ACTIVE_STATUSES))}))"
        params += ACTIVE_STATUSES
    hits = sorted(con.execute(sql, params).fetchall(), key=lambda r: dist[r[0]])[: args.k]
    audit(con, "query", "search", args.text[:120], {"k": args.k, "hits": len(hits)})
    con.commit()
    for cid, kind, ref, title, status, scope, project, text in hits:
        print(f"\n--- {kind}:{ref} [{status}/{scope}] d={dist[cid]:.3f}")
        body = text if args.show_text else text[:400]
        print(body.strip() + ("" if args.show_text or len(text) <= 400 else " …"))
    if not hits:
        print("no hits under current filters (try --historical or --scope all)")


# ------------------------------------------------------------------ records --
def next_record_id(con, project):
    pref = f"{project.upper()}-K-"
    row = con.execute("SELECT id FROM records WHERE id LIKE ? ORDER BY id DESC LIMIT 1", (pref + "%",)).fetchone()
    n = int(row[0].rsplit("-", 1)[1]) + 1 if row else 1
    return f"{pref}{n:04d}"


def cmd_record_add(args):
    import yaml
    con = db_connect()
    dim = len(embed_texts(["probe"])[0])
    db_init(con, dim)
    body = sys.stdin.read() if args.body_file == "-" else Path(args.body_file).read_text(encoding="utf-8")
    body, n_red = redact(body)
    if args.status not in STATUSES:
        sys.exit(f"bad status; allowed: {STATUSES}")
    rid = next_record_id(con, args.project)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    rec = {
        "id": rid, "title": args.title, "project": args.project, "type": args.type,
        "status": args.status, "priority": args.priority, "confidence": args.confidence,
        "created_at": now, "updated_at": now, "created_by": args.actor,
        "source": {"primary_uri": args.source or "", "source_type": "local_markdown"},
        "scope": {"affected_files": args.files or [], "tags": args.tags or []},
        "evidence": [{"kind": "note", "ref": e} for e in (args.evidence or [])],
        "privacy": {"level": "internal", "contains_secrets": False,
                    "redaction_status": "passed" if n_red == 0 else "redacted"},
        "relations": {"supersedes": [], "superseded_by": None},
    }
    con.execute(
        "INSERT INTO records(id, title, project, type, status, priority, confidence, created_at, updated_at, "
        "created_by, source_uri, body, yaml) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, args.title, args.project, args.type, args.status, args.priority, args.confidence,
         now, now, args.actor, args.source or "", body, yaml.safe_dump(rec, allow_unicode=True, sort_keys=False)))
    replace_chunks(con, "record", rid, chunk_markdown(f"# {args.title}\n\n{body}", rid),
                   args.project, args.status, "active", args.title)
    audit(con, args.actor, "record_added", rid, {"status": args.status, "redactions": n_red})
    con.commit()
    print(rid)


def cmd_record_set_status(args):
    con = db_connect()
    row = con.execute("SELECT status, project FROM records WHERE id=?", (args.id,)).fetchone()
    if not row:
        sys.exit(f"no record {args.id}")
    cur, project = row
    if args.status not in TRANSITIONS.get(cur, []):
        sys.exit(f"transition {cur} -> {args.status} not allowed; allowed: {TRANSITIONS.get(cur, [])}")
    if args.status in APPROVAL_REQUIRED and not args.approve:
        sys.exit(f"'{args.status}' requires human sign-off: re-run with --approve")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    scope = "archive" if args.status in ("resolved", "rejected", "obsolete", "superseded") else "active"
    con.execute("UPDATE records SET status=?, updated_at=?, retrieval_scope=?, superseded_by=? WHERE id=?",
                (args.status, now, scope, args.superseded_by, args.id))
    con.execute("UPDATE chunks SET status=?, retrieval_scope=? WHERE kind='record' AND ref=?",
                (args.status, scope, args.id))
    audit(con, args.actor, "status_transition", args.id,
          {"from": cur, "to": args.status, "approved": bool(args.approve),
           "evidence": args.evidence or [], "superseded_by": args.superseded_by})
    con.commit()
    print(f"{args.id}: {cur} -> {args.status} (scope={scope})")


def cmd_record_list(args):
    con = db_connect()
    q = "SELECT id, status, priority, retrieval_scope, title FROM records"
    params = []
    if args.status:
        q += " WHERE status=?"
        params.append(args.status)
    for r in con.execute(q + " ORDER BY id", params):
        print(f"{r[0]}  {r[1]:<20} {r[2] or '-':<4} {r[3]:<8} {r[4]}")


def cmd_record_show(args):
    con = db_connect()
    row = con.execute("SELECT yaml, body FROM records WHERE id=?", (args.id,)).fetchone()
    if not row:
        sys.exit(f"no record {args.id}")
    print(row[0])
    print("---\n" + row[1])
    print("\n== audit ==")
    for ts, actor, action, details in con.execute(
            "SELECT ts, actor, action, details FROM audit WHERE ref=? ORDER BY id", (args.id,)):
        print(f"{ts} {actor} {action} {details}")


# -------------------------------------------------------------------- misc --
def cmd_stats(_):
    con = db_connect()
    for k, v in con.execute("SELECT key, value FROM meta"):
        print(f"{k}: {v}")
    for label, sql in [
        ("documents", "SELECT status, COUNT(*) FROM documents GROUP BY status"),
        ("records", "SELECT status, COUNT(*) FROM records GROUP BY status"),
        ("chunks", "SELECT kind, retrieval_scope, COUNT(*) FROM chunks GROUP BY kind, retrieval_scope"),
    ]:
        print(f"-- {label}")
        for row in con.execute(sql):
            print("  ", *row)
    print("audit events:", con.execute("SELECT COUNT(*) FROM audit").fetchone()[0])


def cmd_reindex(args):
    con = db_connect()
    dim = len(embed_texts(["probe"])[0])
    con.execute("DROP TABLE IF EXISTS vec_chunks")
    con.execute(f"CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[{dim}])")
    rows = con.execute("SELECT id, text FROM chunks ORDER BY id").fetchall()
    B = 32
    for i in range(0, len(rows), B):
        batch = rows[i:i + B]
        for (cid, _), v in zip(batch, embed_texts([t for _, t in batch])):
            con.execute("INSERT INTO vec_chunks(rowid, embedding) VALUES (?,?)", (cid, vec_blob(v)))
        con.commit()
        print(f"re-embedded {min(i + B, len(rows))}/{len(rows)}", end="\r")
    con.execute("INSERT OR REPLACE INTO meta VALUES('embedding_model', ?)", (MODEL_NAME,))
    con.execute("INSERT OR REPLACE INTO meta VALUES('embedding_dim', ?)", (str(dim),))
    audit(con, "reindex", "full_reembed", MODEL_NAME, {"chunks": len(rows)})
    con.commit()
    print(f"\nreindexed {len(rows)} chunks with {MODEL_NAME}")


def main():
    ap = argparse.ArgumentParser(prog="knowledge", description=__doc__.splitlines()[0])
    ap.add_argument("--actor", default=os.environ.get("KNOWLEDGE_ACTOR", "agent"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sync", help="scan+ingest a markdown corpus (idempotent)")
    s.add_argument("--repo", required=True)
    s.add_argument("--project", default="uap")
    s.set_defaults(fn=cmd_sync)

    s = sub.add_parser("query", help="semantic search with lifecycle filters")
    s.add_argument("text")
    s.add_argument("--project")
    s.add_argument("--scope", default="active", choices=["active", "archive", "all"])
    s.add_argument("--historical", action="store_true", help="include resolved/rejected/superseded/obsolete")
    s.add_argument("-k", type=int, default=DEFAULT_K)
    s.add_argument("--show-text", action="store_true")
    s.set_defaults(fn=cmd_query)

    r = sub.add_parser("record", help="canonical records")
    rs = r.add_subparsers(dest="rcmd", required=True)
    a = rs.add_parser("add")
    a.add_argument("--title", required=True)
    a.add_argument("--project", default="uap")
    a.add_argument("--type", default="finding",
                   choices=["finding", "decision", "research", "patch_plan", "validation_report", "handoff", "test_plan"])
    a.add_argument("--status", default="hypothesis")
    a.add_argument("--priority", default="P2")
    a.add_argument("--confidence", type=float, default=0.5)
    a.add_argument("--body-file", required=True, help="markdown body path or '-' for stdin")
    a.add_argument("--source")
    a.add_argument("--files", nargs="*")
    a.add_argument("--tags", nargs="*")
    a.add_argument("--evidence", nargs="*")
    a.set_defaults(fn=cmd_record_add)
    st = rs.add_parser("set-status")
    st.add_argument("id")
    st.add_argument("status")
    st.add_argument("--approve", action="store_true", help="human sign-off for risky transitions")
    st.add_argument("--evidence", nargs="*")
    st.add_argument("--superseded-by")
    st.set_defaults(fn=cmd_record_set_status)
    ls = rs.add_parser("list")
    ls.add_argument("--status")
    ls.set_defaults(fn=cmd_record_list)
    sh = rs.add_parser("show")
    sh.add_argument("id")
    sh.set_defaults(fn=cmd_record_show)

    sub.add_parser("stats").set_defaults(fn=cmd_stats)
    sub.add_parser("reindex", help="rebuild the whole vector index (e.g. after model change)").set_defaults(fn=cmd_reindex)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
