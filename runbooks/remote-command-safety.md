# Remote command safety: quoting, escaping, encoding (cookbook)

Durable reference for driving commands through layered contexts on UAP:
**Windows workstation (Git Bash / PowerShell 5.1) → `ssh` → `kubectl exec` → POSIX `sh` (dash/busybox) → sometimes `python -c` / heredoc**, plus `git`/`gh` bodies. Backed by deep-research (14 findings, 3-vote adversarially verified against POSIX, BashFAQ/Pitfalls, ShellCheck, OpenSSH, Python PEPs, git/kubectl/Microsoft docs — 2026-07-11).

## The one idea

**Every hop RE-PARSES its input.** Local shell parses → `ssh` concatenates the rest into one string the *remote* shell re-parses → `kubectl exec` after `--` hands a bare argv to the process (no shell) → `sh -c` parses again → `python -c` parses again. Quoting/encoding that survives one layer is consumed by the next, so escaping "harder" explodes combinatorially and is the wrong instinct. **Fix = stop the re-parsing** (safe-by-construction): send payloads on **stdin**, from **files**, or **base64**-encoded, so no intermediate shell ever tokenizes them.

## Decision guide — pick the pattern by payload

| Situation | Use this | Never |
|---|---|---|
| Multi-line / metachar / quote-bearing remote script | `ssh host 'bash -s' <<'EOF' … EOF` (stdin + quoted heredoc) or base64-transport | inline `ssh host "big …quoted… script"` |
| Same, into a pod | `kubectl exec -i POD -c C -- sh -s <<'EOF' … EOF` | `kubectl exec POD -- sh -c "…nested quotes…"` |
| One-shot remote cmd with a pipe/glob | `kubectl exec POD -- sh -c 'a | b'` (explicit shell) | `kubectl exec POD -- a | b` (`--` has NO shell) |
| `echo` a line containing `( ) & ; \| < >` | `printf '%s\n' 'literal (text)'` or a heredoc | `echo ===foo (bar)===` (dash: `Syntax error: "(" unexpected`) |
| Python one-liner emitting non-ASCII | write to a UTF-8 file (`open(p,"w",encoding="utf-8")`) and Read it; run `python3 -X utf8` | `print()` `→`/em-dash/Cyrillic to a Windows console (cp1252 `UnicodeEncodeError`) |
| Commit message / PR body with any punctuation | `git commit -F msg.txt` / `gh pr create --body-file body.md` | inline `-m "…apostrophes/backticks/parens…"` |
| `.sh` piped over ssh from a Windows checkout | `tr -d '\r'` before piping, or base64-transport; commit with `.gitattributes *.sh text eol=lf` | piping a CRLF file straight into remote `bash` |
| Applying a hand-/agent-edited patch | `git apply --recount patch` | `git apply patch` (fails `corrupt patch at line N` on header drift) |
| Passing a value INTO a nested command | env var (`ssh host 'X=$X cmd'` set remotely) or positional arg | interpolating quotes into a shell variable (quotes become literal data) |

## Root causes (one line each, cited)

1. **`kubectl exec … -- ARGV` has no implicit shell** — metacharacters are inert; wrap in `sh -c`. (k8s docs)
2. **Single quotes make every byte literal** — an apostrophe can't be escaped *inside* `'…'`; canonical fix is close/escape/reopen: `'don'\''t'`. (POSIX 2.2.2, Wooledge Quotes)
3. **Unquoted `( ) & ; | < > \` $ *` are shell syntax** — the `(` in `echo foo (bar)` is what dash rejects. `printf`/quoting/heredoc avoids it. (Wooledge Quotes)
4. **`ssh` appends post-host args into ONE string re-parsed remotely** — two-stage parse, word boundaries lost, one extra quoting layer per hop; `bash -s` on stdin skips the argv layer. (BashFAQ/096, ssh(1))
5. **You can't quote by interpolating into a variable** — quote recognition happens *before* expansion, so stored quotes are literal data (word-splitting still applies). Pass via env/argv. (BashFAQ/050, ShellCheck SC2089/90)
6. **Quoted heredoc delimiter `<<'EOF'` = literal mode** — no `$VAR`/`$(...)` expansion; the safe way to ship a script evaluated on the *remote* host. Unquoted `<<EOF` expands locally first. (POSIX 2.7.4)
7. **dash/busybox reject bashisms** — no `[[ ]]`, arrays, `<<<`, `${v/…}`, `${v:1}`, `echo -e`, `select`, `((…))`. Use `printf`, run ShellCheck. (ShellCheck SC2039 family)
8. **Python <3.12 f-strings can't reuse the delimiter quote** (and no backslash in the expr) — use distinct inner quotes or a local var; 3.12+ (PEP 701) allows it. (PEP 701)
9. **cp1252 `UnicodeEncodeError`** — fix with UTF-8 Mode `python3 -X utf8` / `PYTHONUTF8=1` (also makes `open()`/argv/env UTF-8). (PEP 540)
10. **`chcp 65001` is NOT a reliable fix** for Python console output — force `PYTHONIOENCODING`/`PYTHONUTF8`, or write to a file. (bpo-21808)
11. **PowerShell 5.1 reads BOM-less UTF-8 as the locale codepage** (cp1252 en-US, cp1251 on a RU box) → non-ASCII becomes parse errors. Keep generated `.ps1` ASCII-only (or add a BOM). (Microsoft Learn)
12. **`.gitattributes` `<glob> text eol=lf`** forces LF on checkout even on Windows (overrides `autocrlf`) — prevents CRLF-over-ssh corruption. Already-CRLF blobs need `git add --renormalize`. (GitHub docs)
13. **`git apply --recount`** ignores drifted `@@` hunk counts and infers them — the fix for header/body mismatch (not for CRLF/truncation). (git-apply docs)
14. **`git commit -F` / `gh pr create --body-file`** keep the body off argv entirely — apostrophes/backticks/`$`/newlines can't break parsing. (gh manual)

## Pre-flight checklist (mental, before issuing a layered/remote command)

1. How many parse layers? (local → ssh → kubectl → sh → python). Each is a re-parse.
2. Payload contains `( ) ' " \` $ | & ; < > *` or non-ASCII, AND ≥2 layers → do NOT inline; use stdin-heredoc / base64 / file.
3. `echo` with a metachar → `printf '%s\n'` or heredoc.
4. Unicode out on Windows → write a UTF-8 file, don't print.
5. Commit/PR body → `-F` / `--body-file`, always.
6. `.sh` over ssh → strip CR / base64. Patch → `--recount`. `.ps1` → ASCII-only.
7. Secret in the command → via env-from-stdin or a 0600 file, never argv (leaks via `ps`/history).

## Latent adjacent risks (not yet hit)

- **Stdin exhaustion:** a heredoc/`bash -s` ties up stdin; an inner `read`, nested `ssh`, or `mysql <` will eat the script. Pass those inputs via a file/arg instead.
- **Heredoc won't terminate** if the closing `EOF` line has trailing whitespace or is indented (unless `<<-` + real tabs).
- **`set -e` over ssh** behaves per the *remote* shell; a trailing pipeline can mask failures — check `$?` explicitly.
- **`kubectl exec` merges stdout/stderr** in `-t` mode and can reorder output — avoid `-t` for machine-parsed output.
- **base64 line-wrap:** some `base64` wrap at 76 cols; decoding is fine, but if you `grep` the encoded blob mid-pipe, unwrap first (`base64 -w0` on GNU; BSD/macOS has no `-w`).

## Canonical safe snippets

```sh
# Remote script (no quoting, no CRLF risk): quoted heredoc on stdin
ssh uap@HOST 'bash -s' <<'EOF'
set -eu
printf '%s\n' "any (meta) chars, apostrophes ' and $vars are literal here"
EOF

# Into a pod (stdin, explicit shell)
kubectl exec -i deploy/app -n ns -c c -- sh -s <<'EOF'
grep -c . /etc/hostname
EOF

# Binary-safe universal escape hatch: base64 a local script → run remote
base64 < local.sh | ssh uap@HOST 'base64 -d | bash -s'

# Commit + PR without inline quoting
git commit -F /tmp/msg.txt
gh pr create --title "t" --body-file /tmp/body.md

# Python that emits non-ASCII: to a file, UTF-8, then Read it
python3 -X utf8 - "$OUT" <<'PY'
import sys; open(sys.argv[1],"w",encoding="utf-8").write("arrows → and — dashes\n")
PY
```
