#!/usr/bin/env bash
# Quick setup helper for Knowledge Base Service connection.
# Source this file or run it to verify connectivity:
#   source scripts/kb_setup.sh
#   ./scripts/kb_setup.sh check

set -euo pipefail

: "${KB_BASE_URL:=http://localhost:8100}"
: "${KB_TOKEN:=}"
: "${KB_BUSINESS_ID:=default}"

export KB_BASE_URL KB_TOKEN KB_BUSINESS_ID

_check_connectivity() {
    local url="${KB_BASE_URL}/api/v1/mcp/tools"
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer ${KB_TOKEN}" \
        -H "X-Business-Id: ${KB_BUSINESS_ID}" \
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

if [ "${1:-}" = "check" ]; then
    _check_connectivity
fi
