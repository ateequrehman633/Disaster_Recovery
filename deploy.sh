#!/usr/bin/env bash
# One-command Ubuntu ECS deployment. All secrets are generated locally, never committed.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [ "$(id -u)" -ne 0 ]; then echo 'Run: sudo bash deploy.sh'; exit 1; fi
if ! grep -qi '^ID=ubuntu' /etc/os-release; then
  echo 'This installer supports Ubuntu 22.04 / 24.04 (x86_64/arm64). Other distributions are not tested.'; exit 1
fi
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo '[1/5] Installing Docker Engine and Docker Compose plugin from the official Docker repository...'
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg unzip openssl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL --retry 3 https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  ARCH="$(dpkg --print-architecture)"
  CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
  printf 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' "$CODENAME" "$ARCH" > /etc/apt/sources.list.d/docker.sources
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
else
  echo '[1/5] Docker and Docker Compose already installed.'
fi
if ! docker info >/dev/null 2>&1; then echo 'ERROR: Docker daemon is not responding. Check: systemctl status docker'; exit 1; fi
if [ ! -f .env ]; then
  echo '[2/5] Generating unique installation credentials...'
  umask 077
  cat > .env <<EOF
LAB_SECRET=$(openssl rand -hex 32)
LAB_PASSWORD=$(openssl rand -hex 16)
POSTGRES_PASSWORD=$(openssl rand -hex 22)
REDIS_PASSWORD=$(openssl rand -hex 22)
GRAFANA_PASSWORD=$(openssl rand -hex 16)
EOF
  chmod 600 .env
else
  echo '[2/5] Keeping existing .env credentials and persistent Docker volumes.'
fi
set -a; . ./.env; set +a
printf 'App login: password only\nApp password: %s\nGrafana username: admin\nGrafana password: %s\n' "$LAB_PASSWORD" "$GRAFANA_PASSWORD" > .lab-credentials
chmod 600 .lab-credentials
mkdir -p certs
if [ -f /usr/bin/df ]; then df -h . | tail -1 || true; fi
echo '[3/5] Pulling prebuilt containers, building lab app (requires outbound HTTPS access)...'
docker compose -f compose.yaml pull --ignore-buildable || { echo 'Container download failed. Check ECS outbound Internet/DNS, then rerun sudo bash deploy.sh'; exit 1; }
docker compose -f compose.yaml build app || { echo 'Application build failed. Inspect Docker output and rerun.'; exit 1; }
echo '[4/5] Starting PostgreSQL, Redis, exporters, Prometheus, Grafana and the training app...'
docker compose -f compose.yaml up -d --remove-orphans
printf '[5/5] Health check'
PASS=0
for i in $(seq 1 45); do
  if curl -fsS --max-time 3 http://127.0.0.1:8080/healthz >/dev/null 2>&1; then PASS=1; break; fi
  printf '.'; sleep 3
done
printf '\n'
if [ "$PASS" != '1' ]; then
  echo 'App failed health check. Run: sudo docker compose logs --tail=100 app'
  exit 2
fi
PRIVATE_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ''
echo '================== CLOUDLAB IS RUNNING =================='
echo "Web lab:     http://YOUR_ECS_PUBLIC_IP:8080  (local ECS IP: ${PRIVATE_IP:-unknown})"
echo "Grafana:     http://YOUR_ECS_PUBLIC_IP:3000"
echo "Prometheus:  localhost:9090 only (SSH tunnel if needed)"
echo "App password: $LAB_PASSWORD"
echo "Grafana:      admin / $GRAFANA_PASSWORD"
echo 'Credentials file: .lab-credentials (root only)'
echo 'Restrict inbound TCP 8080 and 3000 to YOUR IP in Huawei ECS security group.'
echo 'Never expose PostgreSQL 5432 or Redis 6379 to the Internet.'
echo 'Do NOT run docker compose down -v unless deleting all databases and evidence.'
echo '=========================================================='
echo ''
docker compose -f compose.yaml ps
