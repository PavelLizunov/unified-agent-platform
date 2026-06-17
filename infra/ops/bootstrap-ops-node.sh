#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root, for example: sudo bash $0" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y \
  apt-transport-https \
  ansible \
  ca-certificates \
  curl \
  git \
  gnupg \
  jq \
  make \
  openssh-server \
  openssh-client \
  python3 \
  python3-pip \
  python3-venv \
  qemu-guest-agent \
  rsync \
  sudo \
  unzip \
  age

install -m 0755 -d /etc/apt/keyrings

if [[ ! -f /etc/apt/sources.list.d/tailscale.list ]]; then
  curl -fsSL "https://pkgs.tailscale.com/stable/debian/$(. /etc/os-release && echo "$VERSION_CODENAME").noarmor.gpg" \
    -o /usr/share/keyrings/tailscale-archive-keyring.gpg
  curl -fsSL "https://pkgs.tailscale.com/stable/debian/$(. /etc/os-release && echo "$VERSION_CODENAME").tailscale-keyring.list" \
    -o /etc/apt/sources.list.d/tailscale.list
fi

if [[ ! -f /etc/apt/sources.list.d/opentofu.list ]]; then
  curl -fsSL https://get.opentofu.org/opentofu.gpg -o /etc/apt/keyrings/opentofu.gpg
  curl -fsSL https://packages.opentofu.org/opentofu/tofu/gpgkey |
    gpg --dearmor -o /etc/apt/keyrings/opentofu-repo.gpg
  cat >/etc/apt/sources.list.d/opentofu.list <<'EOF'
deb [signed-by=/etc/apt/keyrings/opentofu.gpg,/etc/apt/keyrings/opentofu-repo.gpg] https://packages.opentofu.org/opentofu/tofu/any/ any main
deb-src [signed-by=/etc/apt/keyrings/opentofu.gpg,/etc/apt/keyrings/opentofu-repo.gpg] https://packages.opentofu.org/opentofu/tofu/any/ any main
EOF
  chmod a+r /etc/apt/sources.list.d/opentofu.list
fi

if [[ ! -f /etc/apt/sources.list.d/kubernetes.list ]]; then
  curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.35/deb/Release.key |
    gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
  echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.35/deb/ /" \
    >/etc/apt/sources.list.d/kubernetes.list
fi

if [[ ! -f /etc/apt/sources.list.d/github-cli.list ]]; then
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    -o /usr/share/keyrings/githubcli-archive-keyring.gpg
  chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    >/etc/apt/sources.list.d/github-cli.list
fi

apt-get update
apt-get install -y tailscale tofu kubectl gh

systemctl enable --now qemu-guest-agent
systemctl enable --now tailscaled

echo "uap ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/90-uap
chmod 0440 /etc/sudoers.d/90-uap

if [[ -f /etc/ssh/sshd_config ]]; then
  sed -i -E 's/^#?[[:space:]]*PasswordAuthentication[[:space:]].*/PasswordAuthentication no/' /etc/ssh/sshd_config
  sed -i -E 's/^#?[[:space:]]*PermitRootLogin[[:space:]].*/PermitRootLogin no/' /etc/ssh/sshd_config
  sshd -t
  systemctl restart ssh
fi

if ! command -v flux >/dev/null 2>&1; then
  curl -s https://fluxcd.io/install.sh | bash
fi

if ! command -v sops >/dev/null 2>&1; then
  curl -fsSL https://github.com/getsops/sops/releases/download/v3.13.1/sops-v3.13.1.linux.amd64 \
    -o /usr/local/bin/sops
  chmod 0755 /usr/local/bin/sops
fi

for command_name in git ansible-playbook tofu kubectl flux sops age gh tailscale jq; do
  command -v "$command_name" >/dev/null
done

echo "uap-ops-bootstrap-ok"
