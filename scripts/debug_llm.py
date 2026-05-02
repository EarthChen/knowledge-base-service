"""Debug script to analyze LLM prompt sizes for domain classification."""

import asyncio
import json
import time
import os

async def main():
    from store.falkordb_store import FalkorDBStore
    from core.config import get_settings
    import httpx

    cfg = get_settings()
    store = FalkorDBStore(cfg.falkordb)
    await store.connect()

    for repo in ["ultron/user-moa", "ultron/ultron-composite"]:
        modules = await store.list_repository_modules(repo)
        print(f"\n{'='*60}")
        print(f"Repository: {repo}")
        print(f"Module count: {len(modules)}")

        metadata = []
        for m in modules:
            name = m.properties.get("name")
            if not isinstance(name, str) or not name:
                continue
            summary = m.properties.get("business_summary")
            path = m.properties.get("path")
            metadata.append({
                "name": name,
                "business_summary": summary if isinstance(summary, str) else "",
                "path": str(path) if path is not None else name,
            })

        prompt = (
            "Classify the following repository modules into business domains.\n"
            "Use short, human-readable domain names (e.g. product areas).\n"
            'Place shared utilities under "__infrastructure__".\n\n'
            f"Repository: {repo}\n\n"
            f"Modules:\n{json.dumps(metadata, indent=2, ensure_ascii=False)}\n\n"
            "Return ONLY valid JSON."
        )
        print(f"Prompt length: {len(prompt)} chars (~{len(prompt)//4} tokens)")
        print(f"Metadata entries: {len(metadata)}")
        if metadata:
            avg_entry = len(json.dumps(metadata, ensure_ascii=False)) / len(metadata)
            print(f"Avg entry size: {avg_entry:.0f} chars")

    api_key = cfg.llm.api_key
    client = httpx.AsyncClient(
        base_url=cfg.llm.base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=httpx.Timeout(120),
    )

    print(f"\n{'='*60}")
    print("Testing LLM with increasing prompt sizes...")
    for size in [100, 500, 2000, 5000, 10000, 20000]:
        content = "X " * size
        t0 = time.time()
        try:
            resp = await client.post("/chat/completions", json={
                "model": cfg.llm.model,
                "messages": [{"role": "user", "content": f"Repeat: {content[:size]}"}],
                "temperature": 0.1,
                "max_tokens": 10,
            })
            elapsed = time.time() - t0
            if resp.status_code == 200:
                data = resp.json()
                usage = data.get("usage", {})
                print(f"  {size:>6} chars: OK {elapsed:.1f}s, prompt_tokens={usage.get('prompt_tokens')}")
            else:
                print(f"  {size:>6} chars: HTTP {resp.status_code} {elapsed:.1f}s - {resp.text[:100]}")
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  {size:>6} chars: ERROR {elapsed:.1f}s - {type(e).__name__}: {e}")

    await client.aclose()

asyncio.run(main())
