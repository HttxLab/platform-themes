#!/usr/bin/env bash
# Cloud Agent install: Docker, Compose, and the Authentik images used by authentik/compose.yml.
# Idempotent. Leaves the Docker daemon stopped so a disk snapshot does not capture a live engine.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

cd /workspace

install_packages() {
  sudo DEBIAN_FRONTEND=noninteractive apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    -o Dpkg::Options::=--force-confdef \
    -o Dpkg::Options::=--force-confold \
    ca-certificates \
    curl \
    openssl \
    jq \
    python3 \
    postgresql-client \
    docker.io \
    docker-compose-v2 \
    fuse-overlayfs \
    iptables
}

if ! command -v docker >/dev/null 2>&1 \
  || ! docker compose version >/dev/null 2>&1 \
  || ! command -v jq >/dev/null 2>&1 \
  || ! command -v psql >/dev/null 2>&1 \
  || ! command -v fuse-overlayfs >/dev/null 2>&1; then
  install_packages
fi

sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "storage-driver": "fuse-overlayfs",
  "iptables": false,
  "ip6tables": false,
  "live-restore": false
}
EOF

if id ubuntu >/dev/null 2>&1; then
  sudo usermod -aG docker ubuntu || true
fi

# Bridge traffic must not hit the legacy FORWARD DROP rules. systemd does not
# apply sysctl.d here, so start applies the same settings on every boot.
configure_docker_network() {
  sudo sysctl -w net.bridge.bridge-nf-call-iptables=0 >/dev/null
  sudo sysctl -w net.bridge.bridge-nf-call-ip6tables=0 >/dev/null
}

configure_docker_network

docker_ready() {
  if [[ -S /var/run/docker.sock ]]; then
    sudo chmod 666 /var/run/docker.sock 2>/dev/null || true
  fi
  docker info >/dev/null 2>&1
}

start_dockerd() {
  if docker_ready; then
    return 0
  fi
  sudo rm -f /var/run/docker.pid /var/run/docker.sock /tmp/dockerd.log
  # setsid detaches dockerd from this shell so exit does not SIGHUP the daemon.
  # Remove the log first: /tmp is sticky, and the kernel blocks root from
  # truncating a file in /tmp that another user already created.
  sudo sh -c 'setsid dockerd >/tmp/dockerd.log 2>&1 </dev/null &'
  local attempt
  for attempt in $(seq 1 90); do
    if docker_ready; then
      return 0
    fi
    sleep 1
  done
  echo "error: dockerd did not become ready" >&2
  tail -n 80 /tmp/dockerd.log >&2 || true
  return 1
}

stop_dockerd() {
  if [[ -f /var/run/docker.pid ]]; then
    sudo kill "$(cat /var/run/docker.pid)" >/dev/null 2>&1 || true
  fi
  local attempt
  for attempt in $(seq 1 30); do
    if ! pgrep -x dockerd >/dev/null 2>&1; then
      sudo rm -f /var/run/docker.pid /var/run/docker.sock
      return 0
    fi
    sleep 1
  done
  sudo pkill -9 dockerd >/dev/null 2>&1 || true
  sudo rm -f /var/run/docker.pid /var/run/docker.sock
}

pull_image() {
  local image="$1"
  local attempt
  for attempt in 1 2 3; do
    if docker pull "${image}"; then
      return 0
    fi
    sleep 5
  done
  echo "error: failed to pull ${image}" >&2
  return 1
}

start_dockerd
pull_image docker.io/library/postgres:16-alpine
pull_image ghcr.io/goauthentik/server:2026.8.5
driver="$(docker info --format '{{.Driver}}')"
if [[ "${driver}" != "fuse-overlayfs" ]]; then
  echo "error: expected Docker storage driver fuse-overlayfs, got ${driver}" >&2
  exit 1
fi
echo "Docker $(docker --version) / $(docker compose version)"
echo "Images ready: postgres:16-alpine, authentik server 2026.8.5 (${driver})"
stop_dockerd
echo "Install finished. Docker daemon is stopped until start."
