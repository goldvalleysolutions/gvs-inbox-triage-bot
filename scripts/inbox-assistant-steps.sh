#!/usr/bin/env bash
# Inbox Assistant walkthrough against a built inbox-assistant-in-a-box image.
# Stub LLM, fake SMTP, MCP. Usage: scripts/inbox-assistant-steps.sh <image> [host-port]
set -euo pipefail

image="${1:?usage: scripts/inbox-assistant-steps.sh <image> [port]}"
port="${2:-18084}"
name="inbox-steps-$(echo "$image" | tr -c 'a-zA-Z0-9' '-')$$"
vol="${name}-data"
smtp_pid=""
here="$(cd "$(dirname "$0")/.." && pwd)"
base="http://127.0.0.1:${port}"

cleanup() {
  if [[ -n "${smtp_pid}" ]]; then kill "${smtp_pid}" >/dev/null 2>&1 || true; fi
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker volume rm "$vol" >/dev/null 2>&1 || true
  rm -f "/tmp/${name}-smtp.port"
}
trap cleanup EXIT

python3 "$here/tests/fakesmtp.py" > "/tmp/${name}-smtp.port" &
smtp_pid=$!
for _ in $(seq 1 50); do
  [[ -s "/tmp/${name}-smtp.port" ]] && break
  sleep 0.1
done
smtp_port="$(tr -d '[:space:]' < "/tmp/${name}-smtp.port")"
[[ -n "$smtp_port" ]]

docker run -d --name "$name" \
  --add-host=host.docker.internal:host-gateway \
  -p "127.0.0.1:${port}:8080" \
  -v "${vol}:/data" \
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

export PYTHONPATH="$here"
python3 "$here/scripts/inbox_assistant_steps_http.py" "$base" "$smtp_port" "$here" "$name"
