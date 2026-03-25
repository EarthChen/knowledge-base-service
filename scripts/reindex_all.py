#!/usr/bin/env python3
"""Re-index all ultron-* projects with memory/CPU monitoring."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import urllib.request

API = "http://localhost:8100/api/v1"
PROJECTS_DIR = "/Users/earthchen/work/momo/amar"
PID = None


def get_pid() -> int | None:
    result = subprocess.run(
        ["lsof", "-ti:8100"], capture_output=True, text=True,
    )
    pids = result.stdout.strip().split("\n")
    for pid in pids:
        pid = pid.strip()
        if pid:
            return int(pid)
    return None


def get_memory_cpu(pid: int) -> dict:
    result = subprocess.run(
        ["ps", "-o", "rss=,vsz=,%mem=,%cpu=", "-p", str(pid)],
        capture_output=True, text=True,
    )
    parts = result.stdout.strip().split()
    if len(parts) >= 4:
        return {
            "rss_mb": int(parts[0]) / 1024,
            "vsz_mb": int(parts[1]) / 1024,
            "mem_pct": float(parts[2]),
            "cpu_pct": float(parts[3]),
        }
    return {"rss_mb": 0, "vsz_mb": 0, "mem_pct": 0, "cpu_pct": 0}


def api_call(method: str, path: str, data: dict | None = None) -> dict:
    url = f"{API}{path}"
    if data:
        payload = json.dumps(data).encode()
        req = urllib.request.Request(url, data=payload, method=method)
        req.add_header("Content-Type", "application/json")
    else:
        req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=1800) as resp:
        return json.loads(resp.read())


def main() -> None:
    pid = get_pid()
    if not pid:
        print("ERROR: KB service not running on port 8100")
        return

    print(f"Service PID: {pid}")
    baseline = get_memory_cpu(pid)
    print(f"Baseline: RSS={baseline['rss_mb']:.0f}MB, CPU={baseline['cpu_pct']:.0f}%")

    repos = api_call("GET", "/repositories")
    for repo in repos.get("repositories", []):
        name = repo["repository"]
        print(f"  Deleting old index: {name} ({repo['nodes']} nodes)")
        api_call("DELETE", f"/index/{name}")

    print(f"\nCleared. Stats after delete:")
    stats = api_call("GET", "/stats")
    print(f"  Nodes: F={stats['function_count']} C={stats['class_count']} M={stats['module_count']} D={stats['document_count']}")

    projects = sorted(Path(PROJECTS_DIR).glob("ultron-*"))
    print(f"\nFound {len(projects)} ultron-* projects to index")
    print("=" * 70)

    total_stats = {"files": 0, "nodes": 0, "edges": 0, "embeds": 0}
    peak_rss = baseline["rss_mb"]

    for i, proj in enumerate(projects, 1):
        if not proj.is_dir():
            continue

        name = proj.name
        print(f"\n[{i}/{len(projects)}] Indexing: {name}")

        mem_before = get_memory_cpu(pid)
        t0 = time.time()

        try:
            result = api_call("POST", "/index", {
                "directory": str(proj),
                "mode": "full",
                "repository": name,
            })
            elapsed = time.time() - t0
            mem_after = get_memory_cpu(pid)
            peak_rss = max(peak_rss, mem_after["rss_mb"])

            s = result.get("stats", {})
            total_stats["nodes"] += s.get("nodes", 0) + s.get("doc_nodes", 0)
            total_stats["edges"] += s.get("edges", 0) + s.get("doc_edges", 0)
            total_stats["embeds"] += s.get("embeddings", 0) + s.get("doc_embeddings", 0)
            total_stats["files"] += 1

            print(f"  Done in {elapsed:.1f}s | "
                  f"nodes={s.get('nodes', 0)} edges={s.get('edges', 0)} "
                  f"embeds={s.get('embeddings', 0)} "
                  f"inherits={s.get('inherits', 0)} imports={s.get('imports', 0)}")
            print(f"  Memory: RSS={mem_after['rss_mb']:.0f}MB "
                  f"(delta={mem_after['rss_mb']-mem_before['rss_mb']:+.0f}MB) "
                  f"CPU={mem_after['cpu_pct']:.0f}%")

        except Exception as exc:
            print(f"  ERROR: {exc}")

    print("\n" + "=" * 70)
    print(f"INDEXING COMPLETE")
    print(f"  Projects: {total_stats['files']}")
    print(f"  Total nodes: {total_stats['nodes']}")
    print(f"  Total edges: {total_stats['edges']}")
    print(f"  Total embeddings: {total_stats['embeds']}")
    print(f"  Peak RSS: {peak_rss:.0f}MB")

    final_mem = get_memory_cpu(pid)
    print(f"  Final RSS: {final_mem['rss_mb']:.0f}MB")
    print(f"  Baseline: {baseline['rss_mb']:.0f}MB")

    print("\nFinal graph stats:")
    stats = api_call("GET", "/stats")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
