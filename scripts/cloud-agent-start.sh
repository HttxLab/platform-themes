#!/usr/bin/env bash
# Cloud Agent start: bring up Docker, then the Authentik theme loop when this checkout has it.
set -euo pipefail

cd /workspace

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
    echo "Docker daemon is ready ($(docker info --format '{{.Driver}}'))."
    return 0
  fi
  sudo rm -f /var/run/docker.pid /var/run/docker.sock /tmp/dockerd.log
  # setsid detaches dockerd from this shell so exit does not SIGHUP the daemon.
  # Remove the log first: /tmp sticky + fs.protected_regular blocks root from truncating another user's file.
  sudo sh -c 'setsid dockerd >/tmp/dockerd.log 2>&1 </dev/null &'
  local attempt
  for attempt in $(seq 1 90); do
    if docker_ready; then
      echo "Docker daemon is ready ($(docker info --format '{{.Driver}}'))."
      return 0
    fi
    sleep 1
  done
  echo "error: dockerd did not become ready" >&2
  tail -n 80 /tmp/dockerd.log >&2 || true
  return 1
}

start_dockerd

if [[ -x scripts/authentik-deploy.sh && -f authentik/compose.yml && -f authentik/style.css ]]; then
  scripts/authentik-deploy.sh
  echo "Authentik theme environment is ready."
else
  echo "Docker is ready. This checkout has no Authentik compose stack to start."
fi
