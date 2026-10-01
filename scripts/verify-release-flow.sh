#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
evidence=${1:?Pass an output directory for release evidence}
mkdir -p "$evidence"
evidence=$(cd "$evidence" && pwd)
project="autolava-gate-${GITHUB_RUN_ID:-$$}"
proxy="${project}-tls"
legacy_project="${project}-legacy"
legacy_proxy="${legacy_project}-tls"
compose=(docker compose -p "$project" -f "$root/compose.yaml" -f "$root/scripts/release-compose.yaml")
legacy_compose=(docker compose -p "$legacy_project" -f "$root/compose.yaml" -f "$root/scripts/release-compose.yaml")
certs=$(mktemp -d)
export AUTOLAVA_API_IMAGE="autolava-api:$(git -C "$root" rev-parse HEAD)"
export AUTOLAVA_WEB_IMAGE="autolava-web:$(git -C "$root" rev-parse HEAD)"
export AUTOLAVA_WEB_HOST_PORT=127.0.0.1:18080
export AUTOLAVA_COOKIE_SECURE=true
export AUTOLAVA_BOOTSTRAP_USERNAME=release-admin
export AUTOLAVA_BOOTSTRAP_PASSWORD="$(openssl rand -base64 36)"
export AUTOLAVA_JWT_SECRET="$(openssl rand -hex 48)"

cleanup() {
  outcome=$?
  if ! test -s "$evidence/tls-proxy.log"; then docker logs "$proxy" > "$evidence/tls-proxy.log" 2>&1 || true; fi
  docker logs "$legacy_proxy" > "$evidence/legacy-tls-proxy.log" 2>&1 || true
  if ! test -s "$evidence/compose.log"; then "${compose[@]}" logs --no-color > "$evidence/compose.log" 2>&1 || true; fi
  "${legacy_compose[@]}" logs --no-color > "$evidence/legacy-compose.log" 2>&1 || true
  docker rm -f "$proxy" >/dev/null 2>&1 || true
  docker rm -f "$legacy_proxy" >/dev/null 2>&1 || true
  "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  "${legacy_compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  docker volume rm "${legacy_project}_autolava_data" >/dev/null 2>&1 || true
  rm -rf "$certs"
  printf 'release-flow-exit=%s\n' "$outcome" > "$evidence/result.txt"
  exit "$outcome"
}
trap cleanup EXIT
wait_for_health() {
  local port=$1
  for _ in $(seq 1 60); do
    if curl -kfsS "https://127.0.0.1:$port/health" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}
printf 'source=%s\nrunner=%s\napi-cookie-secure=true\nweb=prebuilt-image\ninitial-stores=1\nbrowser-records=1\nlegacy-records=1\nexternal-provider=blocked-local-proxy\n' \
  "$(git -C "$root" rev-parse HEAD)" "${RUNNER_OS:-linux}" > "$evidence/run-context.txt"

# The image builder refuses a dirty source tree, checks lock-selected installed
# packages on the target platform, records image IDs and migrates an empty volume.
bash "$root/scripts/build-release-images.sh" "$evidence/images"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -keyout "$certs/key.pem" -out "$certs/cert.pem" \
  -subj '/CN=localhost' -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1' \
  > /dev/null 2>&1

"${compose[@]}" up -d --no-build
docker run -d --name "$proxy" --network "${project}_default" \
  -p 127.0.0.1:8443:443 \
  -v "$root/scripts/release-https.conf:/etc/nginx/conf.d/default.conf:ro" \
  -v "$certs:/certs:ro" nginx:1.27-alpine >/dev/null

wait_for_health 8443
"${compose[@]}" exec -T autolava-api \
  python -m app.scripts.create_admin >/dev/null
python3 "$root/scripts/release_http.py" setup

(cd "$root/frontend" && npx playwright install --with-deps chromium && \
  RELEASE_PHASE=before npx playwright test -c playwright.release.config.ts)
python3 "$root/scripts/release_http.py" verify

"${compose[@]}" restart autolava-api autolava-web
wait_for_health 8443
python3 "$root/scripts/release_http.py" after
(cd "$root/frontend" && RELEASE_PHASE=after npx playwright test -c playwright.release.config.ts)
"${compose[@]}" exec -T autolava-api \
  alembic current > "$evidence/migration-after-restart.txt"
docker logs "$proxy" > "$evidence/tls-proxy.log" 2>&1
"${compose[@]}" logs --no-color > "$evidence/compose.log" 2>&1
docker rm -f "$proxy" >/dev/null
"${compose[@]}" down -v --remove-orphans >/dev/null

# Upgrade a separate pre-session schema using the exact same candidate API
# image. This volume is created solely for this job and deleted by the trap.
legacy_volume="${legacy_project}_autolava_data"
docker volume create \
  --label "com.docker.compose.project=$legacy_project" \
  --label com.docker.compose.volume=autolava_data "$legacy_volume" >/dev/null
docker run --rm \
  -e AUTOLAVA_ENVIRONMENT=production \
  -e AUTOLAVA_DATABASE_PATH=/data/autolava.sqlite3 \
  -e AUTOLAVA_JWT_SECRET="$AUTOLAVA_JWT_SECRET" \
  -e AUTOLAVA_BOOTSTRAP_USERNAME="$AUTOLAVA_BOOTSTRAP_USERNAME" \
  -e AUTOLAVA_BOOTSTRAP_PASSWORD="$AUTOLAVA_BOOTSTRAP_PASSWORD" \
  -v "$legacy_volume:/data" \
  -v "$root/scripts/release_legacy_seed.py:/seed.py:ro" \
  --entrypoint sh "$AUTOLAVA_API_IMAGE" -c 'alembic upgrade 0015 && python /seed.py' \
  > "$evidence/legacy-seed.log" 2>&1
export AUTOLAVA_WEB_HOST_PORT=127.0.0.1:18081
"${legacy_compose[@]}" up -d --no-build
docker run -d --name "$legacy_proxy" --network "${legacy_project}_default" \
  -p 127.0.0.1:8444:443 \
  -v "$root/scripts/release-https.conf:/etc/nginx/conf.d/default.conf:ro" \
  -v "$certs:/certs:ro" nginx:1.27-alpine >/dev/null
wait_for_health 8444
RELEASE_BASE_URL=https://127.0.0.1:8444 python3 "$root/scripts/release_http.py" legacy
"${legacy_compose[@]}" exec -T autolava-api \
  alembic current > "$evidence/legacy-migration-current.txt"

docker image inspect --format '{{.Id}}' "$AUTOLAVA_API_IMAGE" > "$evidence/api-image-id.txt"
docker image inspect --format '{{.Id}}' "$AUTOLAVA_WEB_IMAGE" > "$evidence/web-image-id.txt"
printf 'source=%s\napi=%s\nweb=%s\n' \
  "$(git -C "$root" rev-parse HEAD)" "$AUTOLAVA_API_IMAGE" "$AUTOLAVA_WEB_IMAGE" \
  > "$evidence/candidate.txt"
