#!/usr/bin/env bash
# Build the engine image, start it against a throwaway MongoDB on a private
# docker network, and wait for GET /health to return 200. No host ports are
# published. Exit 0 on success, 1 otherwise.
set -euo pipefail

IMAGE="osiki-engine:smoke"
SUFFIX="$$"
NET="osiki-smoke-net-${SUFFIX}"
MONGO="osiki-smoke-mongo-${SUFFIX}"
ENGINE="osiki-smoke-engine-${SUFFIX}"
TIMEOUT="${SMOKE_TIMEOUT:-30}"

# shellcheck disable=SC2329  # invoked via trap
cleanup() {
  docker rm -f "$ENGINE" "$MONGO" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "$(dirname "$0")/.."

docker build -t "$IMAGE" .
docker network create "$NET" >/dev/null
docker run -d --name "$MONGO" --network "$NET" mongo:7 >/dev/null
docker run -d --name "$ENGINE" --network "$NET" \
  -e "MONGODB_URL=mongodb://${MONGO}:27017" \
  -e "MONGODB_DATABASE=smoke" \
  "$IMAGE" >/dev/null

probe='import urllib.request,sys; sys.exit(0 if urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2).status == 200 else 1)'

deadline=$((SECONDS + TIMEOUT))
while [ "$SECONDS" -lt "$deadline" ]; do
  if [ "$(docker inspect -f '{{.State.Running}}' "$ENGINE" 2>/dev/null)" != "true" ]; then
    echo "FAIL: engine container exited" >&2
    docker logs "$ENGINE" >&2 || true
    exit 1
  fi
  if docker exec "$ENGINE" python -c "$probe" >/dev/null 2>&1; then
    echo "OK: /health returned 200"
    exit 0
  fi
  sleep 1
done

echo "FAIL: /health not ready after ${TIMEOUT}s" >&2
docker logs "$ENGINE" >&2 || true
exit 1
