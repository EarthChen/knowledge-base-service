#!/bin/bash
# Knowledge Base Query Tool
# Usage:
#   ./kb-query.sh search "用户认证流程"                    # Semantic search
#   ./kb-query.sh search "AuthService" --type class        # Search by entity type
#   ./kb-query.sh graph stats                              # Graph statistics
#   ./kb-query.sh graph call_chain --name handleRequest    # Call chain query
#   ./kb-query.sh graph class_methods --name AuthService   # Class methods
#   ./kb-query.sh graph inheritance_tree --name BaseService # Inheritance tree
#   ./kb-query.sh graph file_entities --file src/main.py   # File entities
#   ./kb-query.sh graph find_entity --name AuthService     # Find entity
#   ./kb-query.sh hybrid "API 错误处理"                     # Hybrid search
#   ./kb-query.sh index /path/to/repo                      # Incremental index
#   ./kb-query.sh index /path/to/repo --mode full          # Full index
#
# Environment variables:
#   KB_URL    - Knowledge base API URL (default: http://localhost:8100/api/v1)
#   KB_TOKEN  - API authentication token (required)

set -euo pipefail

KB_URL="${KB_URL:-http://localhost:8100/api/v1}"
KB_TOKEN="${KB_TOKEN:-}"

if [[ -z "$KB_TOKEN" ]]; then
    echo "Error: KB_TOKEN environment variable is required" >&2
    echo "Usage: KB_TOKEN=your-token $0 <command> [args...]" >&2
    exit 1
fi

_curl() {
    curl -s -X POST "$1" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $KB_TOKEN" \
        -d "$2"
}

_curl_get() {
    curl -s "$1" -H "Authorization: Bearer $KB_TOKEN"
}

cmd_search() {
    local query="$1"
    shift
    local k=5
    local entity_type="all"

    while [[ $# -gt 0 ]]; do
        case $1 in
            --type) entity_type="$2"; shift 2 ;;
            --k) k="$2"; shift 2 ;;
            *) echo "Unknown option: $1" >&2; exit 1 ;;
        esac
    done

    _curl "$KB_URL/search" \
        "{\"query\": \"$query\", \"k\": $k, \"entity_type\": \"$entity_type\"}"
}

cmd_graph() {
    local query_type="$1"
    shift

    if [[ "$query_type" == "stats" ]]; then
        _curl "$KB_URL/graph" '{"query_type": "graph_stats"}'
        return
    fi

    local name="" file="" depth=3 direction="downstream" entity_type="any"

    while [[ $# -gt 0 ]]; do
        case $1 in
            --name) name="$2"; shift 2 ;;
            --file) file="$2"; shift 2 ;;
            --depth) depth="$2"; shift 2 ;;
            --direction) direction="$2"; shift 2 ;;
            --entity-type) entity_type="$2"; shift 2 ;;
            *) echo "Unknown option: $1" >&2; exit 1 ;;
        esac
    done

    case "$query_type" in
        call_chain)
            _curl "$KB_URL/graph" \
                "{\"query_type\": \"call_chain\", \"name\": \"$name\", \"depth\": $depth, \"direction\": \"$direction\"}"
            ;;
        class_methods)
            _curl "$KB_URL/graph" \
                "{\"query_type\": \"class_methods\", \"name\": \"$name\"}"
            ;;
        inheritance_tree|inheritance)
            _curl "$KB_URL/graph" \
                "{\"query_type\": \"inheritance\", \"name\": \"$name\"}"
            ;;
        file_entities)
            _curl "$KB_URL/graph" \
                "{\"query_type\": \"file_entities\", \"file\": \"$file\"}"
            ;;
        find_entity)
            _curl "$KB_URL/graph" \
                "{\"query_type\": \"find_entity\", \"name\": \"$name\", \"entity_type\": \"$entity_type\"}"
            ;;
        module_deps)
            _curl "$KB_URL/graph" \
                "{\"query_type\": \"module_deps\", \"name\": \"$name\"}"
            ;;
        *)
            echo "Unknown graph query type: $query_type" >&2
            echo "Available: stats, call_chain, class_methods, inheritance_tree, file_entities, find_entity, module_deps" >&2
            exit 1
            ;;
    esac
}

cmd_hybrid() {
    local query="$1"
    shift
    local k=5
    local expand_depth=2

    while [[ $# -gt 0 ]]; do
        case $1 in
            --k) k="$2"; shift 2 ;;
            --expand-depth) expand_depth="$2"; shift 2 ;;
            *) echo "Unknown option: $1" >&2; exit 1 ;;
        esac
    done

    _curl "$KB_URL/hybrid" \
        "{\"query\": \"$query\", \"k\": $k, \"expand_depth\": $expand_depth}"
}

cmd_index() {
    local directory="$1"
    shift
    local mode="incremental"

    while [[ $# -gt 0 ]]; do
        case $1 in
            --mode) mode="$2"; shift 2 ;;
            *) echo "Unknown option: $1" >&2; exit 1 ;;
        esac
    done

    _curl "$KB_URL/index" \
        "{\"directory\": \"$directory\", \"mode\": \"$mode\"}"
}

cmd_repos() {
    _curl_get "$KB_URL/repositories"
}

show_usage() {
    cat <<'USAGE'
Knowledge Base Query Tool

Commands:
  search <query> [--type class|function|document|all] [--k N]
  graph stats
  graph call_chain --name <name> [--depth N] [--direction upstream|downstream]
  graph class_methods --name <name>
  graph inheritance_tree --name <name>
  graph file_entities --file <path>
  graph find_entity --name <name> [--entity-type function|class|any]
  graph module_deps --name <name>
  hybrid <query> [--k N] [--expand-depth N]
  index <directory> [--mode full|incremental]
  repos

Environment:
  KB_URL    API base URL (default: http://localhost:8100/api/v1)
  KB_TOKEN  API token (required)
USAGE
}

case "${1:-}" in
    search)  shift; cmd_search "$@" ;;
    graph)   shift; cmd_graph "$@" ;;
    hybrid)  shift; cmd_hybrid "$@" ;;
    index)   shift; cmd_index "$@" ;;
    repos)   cmd_repos ;;
    help|-h|--help) show_usage ;;
    *)
        echo "Error: Unknown command '${1:-}'" >&2
        show_usage >&2
        exit 1
        ;;
esac
