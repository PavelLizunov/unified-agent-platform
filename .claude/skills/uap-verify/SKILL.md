---
name: uap-verify
description: Run the UAP validation gate (tests/verify-local.ps1) and interpret its result. Use before handing any change back, and before any commit/push. Knows the success tokens and which failures are EXPECTED on the Windows workstation.
---

# uap-verify

The owner does NOT review code, so this gate is the definition of done.

## Run it

Full (against the live cluster, from a machine that can reach the tailnet):
```powershell
powershell -ExecutionPolicy Bypass -File .\tests\verify-local.ps1
```

Offline / no cluster reachable (static only):
```powershell
powershell -ExecutionPolicy Bypass -File .\tests\verify-local.ps1 -SkipSmoke
```

## Success looks like

- `secret-scan-ok`
- `iac-static-ok`
- smoke tests pass against `100.106.223.120` and `100.94.228.67` (omitted with -SkipSmoke)
- `verify-local-ok`  ← the final token; absence of it = the gate did not complete

## EXPECTED failures on the Windows workstation (do NOT chase these)

- `-IncludeReadiness` reports `git-remote-missing` and `s3-env-missing` — the origin + S3 creds live on uap-ops-1 and in SOPS, not on Windows.
- tofu/terraform/ansible CLI checks are skipped — those tools are not installed on the workstation.

## If you changed hermes/ code

The default gate does NOT run the hermes tests yet. Until verify-local.ps1 wires them in, also run:
```powershell
python -m unittest discover -s hermes/tests -p 'test_*.py'
```
(use `test_*.py`, not `*.py` — the latter also imports reliability.py / run_integration.py, which run module-level code that needs a live cluster/LITELLM_BASE and will fail at import. Plain `python -m unittest` from hermes/ finds 0 tests — `discover -s` is required.)

Authoritative reference: runbooks/validation-matrix.md, CLAUDE.md -> Validation Command.
