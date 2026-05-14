#!/usr/bin/env bash
# Setup helper for Knowledge Base Service connection.
#
# Source to export env vars:   source scripts/kb_setup.sh
# Check connectivity:          ./scripts/kb_setup.sh check
# Show current config:         ./scripts/kb_setup.sh config

set -euo pipefail

: "${KB_BASE_URL:=http://localhost:8100}"
: "${KB_TOKEN:=}"
: "${KB_BUSINESS_ID:=default}"

export KB_BASE_URL KB_TOKEN KB_BUSINESS_ID

_show_config() {
    echo "KB_BASE_URL    = ${KB_BASE_URL}"
    echo "KB_TOKEN       = ${KB_TOKEN:+(set)}"
    echo "KB_BUSINESS_ID = ${KB_BUSINESS_ID}"
}

_check_connectivity() {
    local url="${KB_BASE_URL}/api/v1/health"
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer ${KB_TOKEN}" \
        "${url}" 2>/dev/null || echo "000")

    if [ "$http_code" = "200" ]; then
        echo "✓ Knowledge Base Service reachable at ${KB_BASE_URL}"
        return 0
    elif [ "$http_code" = "000" ]; then
        echo "✗ Cannot connect to ${KB_BASE_URL}" >&2
        return 1
    else
        echo "✗ HTTP ${http_code} from ${KB_BASE_URL}" >&2
        return 1
    fi
}

case "${1:-}" in
    check)  _show_config; echo "---"; _check_connectivity ;;
    config) _show_config ;;
esac
