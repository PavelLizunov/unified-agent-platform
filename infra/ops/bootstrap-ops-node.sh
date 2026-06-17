#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root, for example: sudo bash $0" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
KUBECTL_VERSION="${KUBECTL_VERSION:-v1.35.6}"
TOFU_VERSION="${TOFU_VERSION:-1.12.2}"
FLUX_VERSION="${FLUX_VERSION:-2.8.8}"
SOPS_VERSION="${SOPS_VERSION:-3.13.1}"

cat >/etc/apt/apt.conf.d/80uap-retries <<'EOF'
Acquire::Retries "5";
Acquire::http::Timeout "30";
Acquire::https::Timeout "30";
EOF

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
apt-get install -y tailscale gh

if ! command -v kubectl >/dev/null 2>&1; then
  if ! apt-get install -y kubectl; then
    tmp="$(mktemp)"
    curl -fL --retry 5 --retry-delay 3 --connect-timeout 20 \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
      -o "$tmp"
    install -m 0755 "$tmp" /usr/local/bin/kubectl
    rm -f "$tmp"
  fi
fi

if ! command -v tofu >/dev/null 2>&1; then
  if ! apt-get install -y tofu; then
    tmpdir="$(mktemp -d)"
    artifact="/tmp/tofu_${TOFU_VERSION}_linux_amd64.zip"
    if [[ ! -f "$artifact" ]]; then
      curl -fL --retry 5 --retry-delay 3 --connect-timeout 20 \
        "https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION}/tofu_${TOFU_VERSION}_linux_amd64.zip" \
        -o "$artifact"
    fi
    unzip -q "$artifact" -d "$tmpdir"
    install -m 0755 "$tmpdir/tofu" /usr/local/bin/tofu
    rm -rf "$tmpdir"
  fi
fi

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
  tmpdir="$(mktemp -d)"
  artifact="/tmp/flux_${FLUX_VERSION}_linux_amd64.tar.gz"
  if [[ ! -f "$artifact" ]]; then
    curl -fL --retry 5 --retry-delay 3 --connect-timeout 20 \
      "https://github.com/fluxcd/flux2/releases/download/v${FLUX_VERSION}/flux_${FLUX_VERSION}_linux_amd64.tar.gz" \
      -o "$artifact"
  fi
  tar -xzf "$artifact" -C "$tmpdir"
  install -m 0755 "$tmpdir/flux" /usr/local/bin/flux
  rm -rf "$tmpdir"
fi

if ! command -v sops >/dev/null 2>&1; then
  artifact="/tmp/sops-v${SOPS_VERSION}.linux.amd64"
  if [[ ! -f "$artifact" ]]; then
    curl -fL --retry 5 --retry-delay 3 --connect-timeout 20 \
      "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.amd64" \
      -o "$artifact"
  fi
  install -m 0755 "$artifact" /usr/local/bin/sops
fi

for command_name in git ansible-playbook tofu kubectl flux sops age gh tailscale jq; do
  command -v "$command_name" >/dev/null
done

echo "uap-ops-bootstrap-ok"
