#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
if test -n "$(git -C "$root" status --porcelain)"; then
  echo 'Commit the source before building release images.' >&2
  exit 1
fi
revision=$(git -C "$root" rev-parse HEAD)
output=${1:-"${TMPDIR:-/tmp}/autolava-release-$revision"}
mkdir -p "$output"

api_image="autolava-api:$revision"
web_image="autolava-web:$revision"
docker build --build-arg "SOURCE_REVISION=$revision" -t "$api_image" "$root/backend"
(cd "$root/frontend" && npm ci && npm run build)
docker build --build-arg "SOURCE_REVISION=$revision" -f "$root/frontend/Dockerfile.prebuilt" -t "$web_image" "$root/frontend"

for image in "$api_image" "$web_image"; do
  actual=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image")
  test "$actual" = "$revision"
done

container="autolava-release-check-$$"
volume="autolava-release-check-$$"
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker volume create "$volume" >/dev/null
docker run -d --name "$container" \
  -e AUTOLAVA_ENVIRONMENT=production \
  -e AUTOLAVA_DATABASE_PATH=/data/autolava.sqlite3 \
  -e AUTOLAVA_BACKUP_DIRECTORY=/data/backups \
  -e AUTOLAVA_JWT_SECRET=release-check-only-secret-with-at-least-32-bytes \
  -e AUTOLAVA_COOKIE_SECURE=false \
  -v "$volume:/data" "$api_image" >/dev/null

ready=false
for _ in $(seq 1 30); do
  if docker exec "$container" python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2)' >/dev/null 2>&1; then
    ready=true
    break
  fi
  if test "$(docker inspect --format '{{.State.Running}}' "$container")" != true; then
    docker logs "$container" >&2
    exit 1
  fi
  sleep 1
done
if test "$ready" != true; then
  docker logs "$container" >&2
  exit 1
fi

docker exec "$container" alembic current > "$output/migration-current.txt"
docker exec "$container" alembic heads > "$output/migration-heads.txt"
diff -u <(cut -d' ' -f1 "$output/migration-heads.txt") <(cut -d' ' -f1 "$output/migration-current.txt")
docker exec "$container" python -c 'from importlib.metadata import distributions
for package in sorted(distributions(), key=lambda item: item.metadata["Name"].lower()):
    name = package.metadata["Name"]
    print(f"{name}=={package.version}")' > "$output/api-installed.txt"
docker cp "$container:/app/selected-dependencies.txt" "$output/api-lock-selected.txt"
python3 - "$output/api-lock-selected.txt" "$output/api-installed.txt" <<'PY'
import re
import sys
from pathlib import Path

def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()

selected = Path(sys.argv[1]).read_text()
installed = Path(sys.argv[2]).read_text()
expected = {
    normalize(name): version
    for name, version in (line.split("==", 1) for line in selected.splitlines())
}
actual = {
    normalize(name): version
    for name, version in (line.split("==", 1) for line in installed.splitlines())
}
if not expected or expected != actual:
    raise SystemExit(f"Target lock selection differs from installed packages: expected={expected}, actual={actual}")
PY
docker exec "$container" python -c 'from importlib.metadata import distribution, PackageNotFoundError
for name in ("pytest", "pytest-cov", "pytest-xdist", "ruff", "respx", "tzdata"):
    try:
        distribution(name)
    except PackageNotFoundError:
        continue
    raise SystemExit(f"Unexpected production package: {name}")'
printf '%s\n' "$revision" > "$output/source-revision.txt"
sha256sum "$root/backend/uv.lock" "$root/frontend/package-lock.json" > "$output/lockfile-sha256.txt"
docker image inspect --format '{{.Id}}' "$api_image" > "$output/api-image-id.txt"
docker image inspect --format '{{.Id}}' "$web_image" > "$output/web-image-id.txt"
printf 'Verified API startup, disposable-volume migration and target installed packages for %s\n' "$revision"
