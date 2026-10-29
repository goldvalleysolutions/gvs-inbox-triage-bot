#!/usr/bin/env bash
# Inbox Assistant walkthrough against a built inbox-assistant-bot image.
# Stub LLM, fake SMTP, MCP. Usage: scripts/inbox-assistant-steps.sh <image> [host-port]
set -euo pipefail

image="${1:?usage: scripts/inbox-assistant-steps.sh <image> [port]}"
port="${2:-18084}"
name="inbox-steps-$(echo "$image" | tr -c 'a-zA-Z0-9' '-')$$"
vol="${name}-data"
smtp_pid=""
here="$(cd "$(dirname "$0")/.." && pwd)"
base="http://127.0.0.1:${port}"
workdir="$(mktemp -d)"
pubkey="${workdir}/gvs_root.pub"
: > "$pubkey"
chmod 666 "$pubkey"

http_py="$here/scripts/inbox_assistant_steps_http.py"
smtp_py="$here/scripts/fakesmtp.py"
[[ -f "$http_py" ]] || { echo "FAIL missing $http_py" >&2; exit 1; }
[[ -f "$smtp_py" ]] || { echo "FAIL missing $smtp_py" >&2; exit 1; }

cleanup() {
  if [[ -n "${smtp_pid}" ]]; then kill "${smtp_pid}" >/dev/null 2>&1 || true; fi
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker volume rm "$vol" >/dev/null 2>&1 || true
  rm -rf "$workdir"
}
trap cleanup EXIT

python3 "$smtp_py" > "${workdir}/smtp.port" &
smtp_pid=$!
for _ in $(seq 1 50); do
  if ! kill -0 "$smtp_pid" 2>/dev/null; then
    echo "FAIL fakesmtp exited" >&2
    exit 1
  fi
  [[ -s "${workdir}/smtp.port" ]] && break
  sleep 0.1
done
smtp_port="$(tr -d '[:space:]' < "${workdir}/smtp.port")"
[[ -n "$smtp_port" ]] || { echo "FAIL fakesmtp did not print a port" >&2; exit 1; }

docker run -d --name "$name" \
  --add-host=host.docker.internal:host-gateway \
  -p "127.0.0.1:${port}:8080" \
  -v "${vol}:/data" \
  -v "${pubkey}:/app/keys/gvs_root.pub" \
  "$image" >/dev/null

start=$(date +%s)
until curl -fsS "${base}/health" >/dev/null; do
  if (( $(date +%s) - start >= 60 )); then
    echo "FAIL /health not up" >&2
    docker logs "$name" >&2 || true
    exit 1
  fi
  sleep 1
done

docker run --rm \
  --network "container:${name}" \
  -e PYTHONPATH=/app \
  -v "$here/scripts:/steps:ro" \
  -v "${vol}:/data" \
  -v "${pubkey}:/app/keys/gvs_root.pub" \
  "$image" python /steps/inbox_assistant_steps_http.py http://127.0.0.1:8080 "$smtp_port"
