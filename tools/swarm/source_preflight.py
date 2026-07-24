#!/usr/bin/env python3
"""Deterministic required-source preflight.

A mission whose goal depends on an external source must not begin author or
reviewer execution (or any Git mutation/push/PR/CI/deploy) until that exact
source has been obtained and durably bound to an immutable commit SHA, a
content hash and redacted provenance, and the bounded source content has been
made available to BOTH the author and the reviewer.

Design (owner-approved authority only):

* ``source_request`` is a closed, validated, immutable mission structure parsed
  ONCE at intake (``{repo, ref, path}``).  The coordinator never reparses the
  free-form goal; it reads the immutable ``source_request`` from the accepted
  mission and replays it deterministically.
* Authority is the already-declared selected-target capability only: the source
  repository MUST equal the mission's selected target repository.  Any
  cross-repo source fails closed before execution (future catalog-declared
  cross-repo read authority is a separate, unaccepted ADR draft).
* A user-supplied full 40-hex commit SHA is already immutable.  A branch/tag is
  resolved read-only to a commit SHA before content retrieval; the binding
  persists the immutable resolved full commit SHA and content is fetched by
  that SHA, never by the mutable ref.  Changed content/provenance is rejected
  fail-closed on restart and never adopted.
* Fetched content is bounded, validated as text, stored as a private artifact
  and bound into the author and reviewer input.  No credential or secret-bearing
  URL is ever persisted; diagnostics are redacted.

The module is stdlib-only and side-effect free except through an injected
``fetcher`` callable (the existing authenticated ``gh`` boundary).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

SCHEMA_VERSION = 1
QUESTION_PREFIX = "source-preflight:"

_MAX_PATH_CHARS = 512
_MAX_REF_CHARS = 200
# Bounded source content that can be safely bound into model input.
MAX_SOURCE_CONTENT_BYTES = 256 * 1024

# Closed immutable source_request fields (mission acceptance data).
SOURCE_REQUEST_FIELDS = {"repo", "ref", "path"}

# Closed durable binding fields (coordinator state).
BINDING_FIELDS = {
    "schema_version",
    "mission_id",
    "source_request_sha256",
    "repo",
    "ref",
    "resolved_ref",
    "path",
    "content_sha256",
    "size_bytes",
    "provenance_sha256",
    "provenance",
}

# Closed durable preflight-question fields.
PREFLIGHT_FIELDS = {
    "schema_version",
    "mission_id",
    "source_request_sha256",
    "question_id",
    "question_text",
    "status",
    "answer_sha256",
}

_PROVENANCE_FIELDS = {"repo", "ref", "resolved_ref", "path", "blob_sha", "public_url"}

# A fetcher is the existing authenticated boundary:
#   fetcher(repo, ref, path) -> {
#       "resolved_ref": <immutable 40-hex commit SHA the content was fetched at>,
#       "content": <bytes>,
#       "blob_sha": <git blob SHA>,
#       "public_url": <token-free public URL>,
#   }
# It resolves a branch/tag read-only to a commit SHA and fetches the content by
# that SHA.  When called with an already-immutable SHA it fetches by that SHA.
Fetcher = Callable[[str, str, str], dict[str, Any]]


class SourcePreflightError(ValueError):
    """A required source cannot be resolved, pinned or verified; fail closed."""


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_REPO_SLUG = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98})?/[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98})?$"
)
_REF_SHA = re.compile(r"^[0-9a-f]{40}$")
_REF_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_UNTRUSTED_REF_TOKENS = ("..", "~", "^", ":", "?", "*", "[", "\\", "@{", "//")


def is_immutable_ref(ref: str) -> bool:
    """A full 40-hex commit SHA is already immutable; anything else must be
    resolved read-only to a commit SHA before content retrieval."""
    return bool(_REF_SHA.fullmatch(ref))


def validate_repo(repo: object) -> str:
    if not isinstance(repo, str) or not _REPO_SLUG.fullmatch(repo):
        raise SourcePreflightError("source repository slug is malformed")
    return repo


def validate_ref(ref: object) -> str:
    """Validate a git ref.  Accepts a full 40-char SHA or a safe branch/tag
    name; rejects malformed or untrusted refs."""
    if not isinstance(ref, str) or not ref or len(ref) > _MAX_REF_CHARS:
        raise SourcePreflightError("source ref is malformed")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in ref):
        raise SourcePreflightError("source ref is malformed")
    if ref.startswith("-") or ref.startswith("/") or ref != ref.strip():
        raise SourcePreflightError("source ref is untrusted")
    if _REF_SHA.fullmatch(ref):
        return ref
    if any(token in ref for token in _UNTRUSTED_REF_TOKENS):
        raise SourcePreflightError("source ref is untrusted")
    if (
        not _REF_NAME.fullmatch(ref)
        or ref.endswith("/")
        or ref.endswith(".")
        or ref.endswith(".lock")
        or "/." in ref
        or "//" in ref
    ):
        raise SourcePreflightError("source ref is untrusted")
    return ref


def validate_path(path: object) -> str:
    if not isinstance(path, str):
        raise SourcePreflightError("source path is malformed")
    cleaned = path.strip()
    if not cleaned or len(cleaned) > _MAX_PATH_CHARS:
        raise SourcePreflightError("source path is malformed")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in cleaned):
        raise SourcePreflightError("source path is malformed")
    if "\\" in cleaned or cleaned.startswith("~") or cleaned.startswith("/"):
        raise SourcePreflightError("source path is untrusted")
    parts = cleaned.split("/")
    if any(part in {"", "..", "."} for part in parts):
        raise SourcePreflightError("source path is untrusted")
    return cleaned


def validate_source_request(source_request: Any) -> dict[str, Any]:
    """Validate the closed immutable source_request structure."""
    if not isinstance(source_request, dict) or set(source_request) != SOURCE_REQUEST_FIELDS:
        raise SourcePreflightError("source request is invalid")
    return {
        "repo": validate_repo(source_request["repo"]),
        "ref": validate_ref(source_request["ref"]),
        "path": validate_path(source_request["path"]),
    }


def source_request_identity(source_request: dict[str, Any]) -> str:
    return _canonical_sha256(
        {
            "repo": source_request["repo"],
            "ref": source_request["ref"],
            "path": source_request["path"],
        }
    )


def _sanitize_provenance(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SourcePreflightError("source provenance is invalid")
    provenance: dict[str, Any] = {}
    for field in _PROVENANCE_FIELDS:
        item = value.get(field)
        if item is None:
            continue
        if not isinstance(item, str) or not item or len(item) > 1024:
            raise SourcePreflightError("source provenance is invalid")
        lowered = item.casefold()
        if any(token in lowered for token in ("token", "secret", "password", "key=")):
            raise SourcePreflightError("source provenance carries a secret")
        provenance[field] = item
    return provenance


def _validate_content(content: Any) -> bytes:
    if not isinstance(content, bytes):
        raise SourcePreflightError("source content is invalid")
    if not content or len(content) > MAX_SOURCE_CONTENT_BYTES:
        raise SourcePreflightError("source content is empty or too large to bind")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourcePreflightError("source content is not bounded text") from error
    scan_content_secrets(text)
    return content


# Narrow, deterministic credential patterns.  A required source that carries a
# secret is rejected fail-closed BEFORE the durable raw artifact or model input
# is written; the source is never persisted or sent verbatim and never silently
# redacted.  These patterns are deliberately narrow so benign content such as
# Windows/path-like text (backslashes, drive letters) does not false-positive
# (no general diagnostic normalization or backslash stripping is applied here).
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bauthorization\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?i)\b(?:access[_-]?token|api[_-]?key|secret[_-]?key|auth[_-]?token|"
        r"client[_-]?secret|password|passwd|pwd)\s*[:=]\s*\S+"
    ),
    re.compile(r"\bgh[psuor]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAGE-SECRET-" + r"KEY-[A-Z0-9-]+\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*" + r"PRIVATE KEY-----"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\b[0-9]{8,10}:[A-Za-z0-9_-]{35}\b"),
    re.compile(r"https?://[^/\s:@]+:[^/\s@]+@"),
)


def scan_content_secrets(text: str) -> None:
    """Reject fail-closed when bounded source text carries a credential pattern."""
    if not isinstance(text, str):
        raise SourcePreflightError("source content is invalid")
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            raise SourcePreflightError(
                "required source carries a secret and cannot be bound"
            )


def _fetch(fetcher: Fetcher, repo: str, ref: str, path: str) -> dict[str, Any]:
    try:
        result = fetcher(repo, ref, path)
    except SourcePreflightError:
        raise
    except Exception as error:  # noqa: BLE001 - fetch boundary is untrusted
        raise SourcePreflightError(
            f"required source could not be fetched: {type(error).__name__}"
        ) from error
    if not isinstance(result, dict):
        raise SourcePreflightError("source fetch returned an invalid result")
    resolved_ref = result.get("resolved_ref")
    if not isinstance(resolved_ref, str) or not _REF_SHA.fullmatch(resolved_ref):
        raise SourcePreflightError("source fetch did not pin an immutable commit SHA")
    content = _validate_content(result.get("content"))
    blob_sha = result.get("blob_sha")
    if blob_sha is not None and (not isinstance(blob_sha, str) or not blob_sha):
        raise SourcePreflightError("source fetch returned an invalid blob SHA")
    provenance = _sanitize_provenance(result.get("provenance"))
    return {
        "resolved_ref": resolved_ref,
        "content": content,
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "blob_sha": blob_sha,
        "provenance": provenance,
    }


def resolve_source(
    source_request: dict[str, Any],
    target_repo: str,
    fetcher: Fetcher,
    *,
    mission_id: str,
) -> tuple[dict[str, Any], bytes]:
    """Resolve the immutable source exactly and produce a durable binding plus
    the bounded source content.

    Enforces same-target authority: the source repository must equal the
    selected target repository.  Raises ``SourcePreflightError`` fail-closed for
    cross-repo sources, malformed refs/paths, or an unavailable source."""
    if not isinstance(mission_id, str) or not mission_id:
        raise SourcePreflightError("source preflight requires a mission identity")
    request = validate_source_request(source_request)
    target = validate_repo(target_repo)
    if request["repo"] != target:
        raise SourcePreflightError(
            "cross-repo source is not authorized for the selected target"
        )
    fetched = _fetch(fetcher, request["repo"], request["ref"], request["path"])
    provenance = dict(fetched["provenance"])
    provenance.setdefault("repo", request["repo"])
    provenance.setdefault("ref", request["ref"])
    provenance.setdefault("resolved_ref", fetched["resolved_ref"])
    provenance.setdefault("path", request["path"])
    binding = {
        "schema_version": SCHEMA_VERSION,
        "mission_id": mission_id,
        "source_request_sha256": source_request_identity(request),
        "repo": request["repo"],
        "ref": request["ref"],
        "resolved_ref": fetched["resolved_ref"],
        "path": request["path"],
        "content_sha256": fetched["content_sha256"],
        "size_bytes": fetched["size_bytes"],
        "provenance_sha256": _canonical_sha256(provenance),
        "provenance": provenance,
    }
    return binding, fetched["content"]


def validate_binding(
    binding: Any, *, mission_id: str, source_request: dict[str, Any]
) -> dict[str, Any]:
    """Validate a stored durable binding against the immutable mission identity."""
    request = validate_source_request(source_request)
    if (
        not isinstance(binding, dict)
        or set(binding) != BINDING_FIELDS
        or binding.get("schema_version") != SCHEMA_VERSION
        or binding.get("mission_id") != mission_id
        or binding.get("source_request_sha256") != source_request_identity(request)
    ):
        raise SourcePreflightError("durable source binding is missing or invalid")
    if binding.get("repo") != request["repo"] or binding.get("ref") != request["ref"]:
        raise SourcePreflightError("durable source binding detached from its request")
    if binding.get("path") != request["path"]:
        raise SourcePreflightError("durable source binding detached from its request")
    resolved_ref = binding.get("resolved_ref")
    if not isinstance(resolved_ref, str) or not _REF_SHA.fullmatch(resolved_ref):
        raise SourcePreflightError("durable source binding lost its immutable SHA")
    if not isinstance(binding.get("content_sha256"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", binding["content_sha256"]
    ):
        raise SourcePreflightError("durable source binding is invalid")
    size_bytes = binding.get("size_bytes")
    if (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or not 0 < size_bytes <= MAX_SOURCE_CONTENT_BYTES
    ):
        raise SourcePreflightError("durable source binding is invalid")
    provenance = binding.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) > _PROVENANCE_FIELDS:
        raise SourcePreflightError("durable source binding is invalid")
    if binding.get("provenance_sha256") != _canonical_sha256(provenance):
        raise SourcePreflightError("durable source provenance changed after binding")
    return binding


def verify_binding(
    binding: dict[str, Any],
    fetcher: Fetcher,
    *,
    mission_id: str,
    source_request: dict[str, Any],
) -> tuple[dict[str, Any], bytes]:
    """Re-fetch the bound source BY ITS IMMUTABLE RESOLVED SHA and fail closed if
    the content or provenance changed.  Changed content is never adopted."""
    binding = validate_binding(
        binding, mission_id=mission_id, source_request=source_request
    )
    fetched = _fetch(fetcher, binding["repo"], binding["resolved_ref"], binding["path"])
    if (
        fetched["content_sha256"] != binding["content_sha256"]
        or fetched["resolved_ref"] != binding["resolved_ref"]
        or fetched["size_bytes"] != binding["size_bytes"]
    ):
        raise SourcePreflightError("required source changed after binding")
    return binding, fetched["content"]


def expected_question(
    source_request: dict[str, Any] | None,
    *,
    mission_id: str,
    reason: str,
) -> dict[str, Any]:
    """Deterministic identity for the idempotent owner question raised when a
    required source cannot be resolved/pinned exactly."""
    source_request_sha256 = (
        source_request_identity(source_request)
        if isinstance(source_request, dict)
        else None
    )
    identity = _canonical_sha256(
        {
            "mission_id": mission_id,
            "source_request_sha256": source_request_sha256,
            "reason": reason,
        }
    )
    question_text = (
        "This mission requires an external source that is not yet bound to an "
        "exact, immutable reference. ANSWER this question with one exact source "
        "from the SAME target repository as a canonical GitHub URL pinned to a "
        "full 40-character commit SHA plus a normalized path, for example "
        "https://github.com/<target-repo>/blob/<full-commit-sha>/<path>. The "
        "answered source is bound to this same mission and execution resumes "
        "after it is fetched by that immutable SHA. Reading a source from a "
        "different (cross-repo) repository is not authorized and needs separately "
        "approved authority; branch/tag refs, bare repositories and non-GitHub "
        "URLs are rejected. Execution stays blocked until a valid same-target "
        "source is bound."
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "mission_id": mission_id,
        "source_request_sha256": source_request_sha256,
        "question_id": f"{QUESTION_PREFIX}{identity[:24]}",
        "question_text": question_text,
    }


def provenance_evidence(binding: dict[str, Any]) -> dict[str, str]:
    """Bounded, owner-safe source provenance for completion evidence and the
    owner-visible terminal result.  Never includes a token or raw secret URL."""
    return {
        "repo": str(binding.get("repo")),
        "resolved_ref": str(binding.get("resolved_ref")),
        "path": str(binding.get("path")),
        "content_sha256": str(binding.get("content_sha256")),
    }
