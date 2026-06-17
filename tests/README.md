# Tests

Use `verify-local.ps1` as the normal local gate before committing infrastructure changes:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\verify-local.ps1
```

Default behavior:

- Git whitespace check.
- Secret scan.
- Static IaC checks.
- Smoke tests against the current tailnet nodes.

Optional checks:

```powershell
# Validate OpenTofu/Terraform and run a real plan when local credentials exist.
powershell -ExecutionPolicy Bypass -File .\tests\verify-local.ps1 -IncludeTofuPlan

# Run Ansible twice against real hosts and require the second run to report changed=0.
powershell -ExecutionPolicy Bypass -File .\tests\verify-local.ps1 -IncludeAnsibleIdempotency

# Also check whether Git remote and S3 environment are ready.
powershell -ExecutionPolicy Bypass -File .\tests\verify-local.ps1 -IncludeReadiness -GitUrl "ssh://git@example.com/owner/repo.git"
```

`-IncludeAnsibleIdempotency` mutates real hosts on the first run. Use it only when you intend to reconcile the hosts.

Readiness helpers:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\git\check-git-remote.ps1 -GitUrl "ssh://git@example.com/owner/repo.git"
powershell -ExecutionPolicy Bypass -File .\tests\s3\check-s3-env.ps1
```
