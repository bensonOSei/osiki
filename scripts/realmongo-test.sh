#!/usr/bin/env bash
# Run the real-MongoDB tests (tests/realmongo) against a throwaway single-node
# replica set, since transactions need one. The container binds to 127.0.0.1
# only and is always removed on exit. Exit status is pytest's.
set -euo pipefail

NAME="osiki-realmongo-$$"
TIMEOUT="${REALMONGO_TIMEOUT:-60}"

# shellcheck disable=SC2329  # invoked via trap
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "$(dirname "$0")/.."

# Port 0 on the host side lets Docker pick a free port on 127.0.0.1.
docker run -d --name "$NAME" -p 127.0.0.1::27017 mongo:7 \
  --replSet rs0 --bind_ip_all >/dev/null

port="$(docker port "$NAME" 27017/tcp | head -n 1 | awk -F: '{print $NF}')"
if [ -z "$port" ]; then
  echo "FAIL: could not determine the mapped port" >&2
  exit 1
fi

mongo_eval() {
  docker exec "$NAME" mongosh --quiet --eval "$1"
}

deadline=$((SECONDS + TIMEOUT))
until mongo_eval 'db.adminCommand({ping: 1}).ok' >/dev/null 2>&1; do
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "FAIL: mongod did not start within ${TIMEOUT}s" >&2
    docker logs "$NAME" >&2 || true
    exit 1
  fi
  sleep 1
done

mongo_eval 'rs.initiate({_id: "rs0", members: [{_id: 0, host: "127.0.0.1:27017"}]})' >/dev/null

until [ "$(mongo_eval 'db.hello().isWritablePrimary' 2>/dev/null || true)" = "true" ]; do
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "FAIL: replica set did not reach PRIMARY within ${TIMEOUT}s" >&2
    docker logs "$NAME" >&2 || true
    exit 1
  fi
  sleep 1
done

export OSIKI_TEST_MONGO_URL="mongodb://127.0.0.1:${port}/?replicaSet=rs0&directConnection=true"
poetry run pytest -m realmongo tests/realmongo -v
