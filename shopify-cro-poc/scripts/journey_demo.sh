#!/usr/bin/env bash

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
OUTCOME="${OUTCOME:-drop_off}"
RESET_FIRST="${RESET_FIRST:-1}"
LANDING_CONTEXT="${LANDING_CONTEXT:-{\"device_type\":\"mobile\",\"traffic_source\":\"meta\",\"is_returning\":false}}"

usage() {
  printf "Usage: %s [--base-url URL] [--outcome drop_off|convert] [--no-reset] [--context JSON]\n" "$0"
  printf "\n"
  printf "Environment overrides:\n"
  printf "  BASE_URL         API origin (default: http://localhost:8000)\n"
  printf "  OUTCOME          Product-stage outcome: drop_off or convert\n"
  printf "  RESET_FIRST      1 to call /reset first, 0 to skip\n"
  printf "  LANDING_CONTEXT  JSON object used for landing /journey/decide context\n"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --outcome)
      OUTCOME="$2"
      shift 2
      ;;
    --no-reset)
      RESET_FIRST="0"
      shift
      ;;
    --context)
      LANDING_CONTEXT="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf "Unknown argument: %s\n\n" "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "$OUTCOME" != "drop_off" && "$OUTCOME" != "convert" ]]; then
  printf "Invalid OUTCOME '%s'. Expected drop_off or convert.\n" "$OUTCOME" >&2
  exit 1
fi

request_json() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  local response
  local status
  local payload

  if [[ -n "$body" ]]; then
    response="$(curl -sS -w $'\n%{http_code}' -X "$method" "$url" -H "Content-Type: application/json" -d "$body")"
  else
    response="$(curl -sS -w $'\n%{http_code}' -X "$method" "$url")"
  fi

  status="${response##*$'\n'}"
  payload="${response%$'\n'*}"

  if [[ "$status" -lt 200 || "$status" -ge 300 ]]; then
    printf "Request failed: %s %s -> HTTP %s\n" "$method" "$url" "$status" >&2
    printf "%s\n" "$payload" >&2
    exit 1
  fi

  printf "%s" "$payload"
}

if [[ "$RESET_FIRST" == "1" ]]; then
  request_json "POST" "$BASE_URL/reset" "{}" >/dev/null
fi

landing_body="{\"stage\":\"landing\",\"context\":${LANDING_CONTEXT}}"
landing_response="$(request_json "POST" "$BASE_URL/journey/decide" "$landing_body")"

read -r session_id landing_decision_id landing_variant landing_segment <<<"$(python3 - "$landing_response" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
print(payload["session_id"], payload["decision_id"], payload["variant_id"], payload["segment"])
PY
)"

advance_body="{\"decision_id\":\"${landing_decision_id}\",\"event_type\":\"advance\",\"to_stage\":\"product_page\"}"
advance_response="$(request_json "POST" "$BASE_URL/journey/event" "$advance_body")"

product_decide_body="{\"stage\":\"product_page\",\"continue_from_decision_id\":\"${landing_decision_id}\"}"
product_response="$(request_json "POST" "$BASE_URL/journey/decide" "$product_decide_body")"

read -r product_decision_id product_variant product_segment <<<"$(python3 - "$product_response" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
print(payload["decision_id"], payload["variant_id"], payload["segment"])
PY
)"

product_event_body="{\"decision_id\":\"${product_decision_id}\",\"event_type\":\"${OUTCOME}\"}"
product_event_response="$(request_json "POST" "$BASE_URL/journey/event" "$product_event_body")"

metrics_response="$(request_json "GET" "$BASE_URL/journey/metrics")"

python3 - "$landing_response" "$advance_response" "$product_response" "$product_event_response" "$metrics_response" <<'PY'
import json
import sys

landing = json.loads(sys.argv[1])
advance = json.loads(sys.argv[2])
product = json.loads(sys.argv[3])
product_event = json.loads(sys.argv[4])
metrics = json.loads(sys.argv[5])

landing_stats = metrics["stages"]["landing"]
product_stats = metrics["stages"]["product_page"]
sessions = metrics["sessions"]

print("Journey demo complete")
print(f"- session_id: {landing['session_id']}")
print(
    f"- landing: variant={landing['variant_id']} segment={landing['segment']} "
    f"decision_id={landing['decision_id']}"
)
print(
    f"- landing event: {advance['event_type']} -> {advance.get('to_stage')} "
    f"(reward={advance['reward']})"
)
print(
    f"- product_page: variant={product['variant_id']} segment={product['segment']} "
    f"decision_id={product['decision_id']}"
)
print(f"- product event: {product_event['event_type']} (reward={product_event['reward']})")
print("- funnel snapshot:")
print(
    f"  landing: impressions={landing_stats['impressions']} conversions={landing_stats['conversions']} "
    f"drop_offs={landing_stats['drop_offs']} conversion_rate={landing_stats['conversion_rate']:.3f}"
)
print(
    f"  product_page: impressions={product_stats['impressions']} "
    f"conversions={product_stats['conversions']} drop_offs={product_stats['drop_offs']} "
    f"conversion_rate={product_stats['conversion_rate']:.3f}"
)
print(
    f"- sessions: total={sessions['total']} active={sessions['active']} "
    f"closed={sessions['closed']}"
)

top_paths = metrics.get("top_paths", [])
if top_paths:
    print(f"- top path: {top_paths[0]['path']} ({top_paths[0]['sessions']} sessions)")
PY

printf "\nFull metrics JSON: %s/journey/metrics\n" "$BASE_URL"
