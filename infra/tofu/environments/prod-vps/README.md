# Future VPS Environment

This directory is reserved for the future remote VPS provider configuration.

Do not add a fake provider before a VPS vendor is selected. When the vendor is known, add a small module that creates:

- Debian 12 or newer VM.
- SSH key access for user `uap`.
- Minimal firewall rules for SSH and Tailscale bootstrap.
- Outputs with public IP, tailnet name placeholder, and intended k3s role.

Keep k3s installation in Ansible, not in OpenTofu.
