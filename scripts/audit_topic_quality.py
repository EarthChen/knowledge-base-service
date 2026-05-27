#!/usr/bin/env python3
"""Deep audit of wiki topic pages from audit JSON export."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Reuse project guards when available
try:
    from wiki.content_guards import compute_cn_ratio, detect_hallucination_flags
except ImportError:

    def compute_cn_ratio(content: str) -> float:
        text = re.sub(r"```[\s\S]*?```", "", content or "")
        if not text:
            return 0.0
        cn = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        return round(cn / len(text), 4)

    def detect_hallucination_flags(content: str) -> list[str]:
        flags = []
        text = re.sub(r"```[\s\S]*?```", "", content or "")
        for pat, desc in [
            (r"\d+\.\d+%", "fabricated percentage"),
            (r"\b\d{2,3}%", "fabricated round percentage"),
            (r"≤\d+s|≥\d+\.\d+", "fabricated SLA"),
            (r"P\d{2}\s*[<≤]\s*\d+", "fabricated latency SLA"),
        ]:
            if re.search(pat, text):
                flags.append(desc)
        return flags


CODE_BLOCK_RE = re.compile(r"```(\w*)\n([\s\S]*?)```", re.MULTILINE)
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
H1_RE = re.compile(r"^# [^#].+$", re.MULTILINE)
H2_RE = re.compile(r"^## (.+)$", re.MULTILINE)
LLM_TRACE_PATTERNS = [
    re.compile(p, re.IGNORECASE | re.MULTILINE)
    for p in [
        r"\bNote:\s",
        r"\bI need to\b",
        r"\bLet me\b",
        r"\bIn summary\b",
        r"\bI'll\b.*(?:analyze|check|review)",
    ]
]
META_SECTION_PATTERNS = [
    re.compile(r"^##\s*章节导航", re.MULTILINE),
    re.compile(r"^##\s*待完善项", re.MULTILINE),
    re.compile(r"^##\s*References\b", re.MULTILINE),
    re.compile(r"^>\s*\*\*说明\*\*：为提升中文读者理解"),
    re.compile(r"^>\s*术语说明：为提升中文读者理解"),
    re.compile(r"^>\s*本页内容已强化中文表达"),
    re.compile(r"^>\s*\*\*补充说明\*\*"),
]
GENERIC_SLUGS = {"family", "system", "service", "task", "management", "operation"}
PINYIN_SLUG_RE = re.compile(r"^[a-z]+(-[a-z]+)+$")
MODULE_PATH_SLUG_RE = re.compile(r"ultronultron-", re.IGNORECASE)
TRUNCATION_MARKERS = [
    re.compile(r"\.\.\.\s*\n\s*```"),
    re.compile(r"\.\.\.\s*$", re.MULTILINE),
    re.compile(r"EcIn\s*\n\s*```"),
    re.compile(r"EsUse\s*\n\s*```"),
    re.compile(r"PropHandler\s*\n\s*```"),
    re.compile(r"Ha\s*\n\s*ndler"),
]
UNBALANCED_BRACE_RE = re.compile(r"```(?:\w*\n)?([\s\S]*?)```")
PSEUDO_CODE_MARKERS = [
    re.compile(r"//\s*(?:TODO|FIXME|placeholder)", re.IGNORECASE),
    re.compile(r"\bExampleService\b"),
    re.compile(r"\bMockService\b"),
    re.compile(r"\bfake[A-Z]\w+"),
    re.compile(r"source://.*@KafkaListener", re.MULTILINE),  # fabricated kafka snippet
]
VAGUE_H2 = {"概述", "相关主题", "关键实现", "架构设计", "核心流程"}


@dataclass
class TopicAudit:
    title: str
    path: str
    domain: str
    slug: str
    content_length: int
    cn_ratio: float
    code_block_count: int
    h2_count: int
    h2_list: list[str]
    issues: list[tuple[str, str, str]] = field(default_factory=list)  # severity, category, detail
    score: float = 100.0

    def add(self, severity: str, category: str, detail: str, penalty: float = 0) -> None:
        self.issues.append((severity, category, detail))
        self.score -= penalty


def extract_domain(path: str) -> str:
    m = re.search(r"/__domains__/([^/]+)/", path)
    return m.group(1) if m else ""


def extract_slug(path: str) -> str:
    m = re.search(r"/__domains__/[^/]+/([^/]+)/_topic", path)
    return m.group(1) if m else ""


def check_code_truncation(code: str) -> list[str]:
    problems = []
    if re.search(r"\.\.\.\s*$", code.rstrip(), re.MULTILINE):
        problems.append("ends with ...")
    if re.search(r"EcIn\s*$", code):
        problems.append("truncated identifier EcIn")
    if re.search(r"EsUse\s*$", code):
        problems.append("truncated identifier EsUse")
    # unbalanced braces in java-like blocks
    if "{" in code or "}" in code:
        opens = code.count("{")
        closes = code.count("}")
        if opens != closes and abs(opens - closes) >= 1:
            problems.append(f"unbalanced braces ({opens} vs {closes})")
    # incomplete method call
    lines = [ln.rstrip() for ln in code.strip().split("\n") if ln.strip()]
    if lines:
        last = lines[-1]
        if last.endswith(",") or last.endswith("(") or re.search(r"\.\.\.$", last):
            problems.append("incomplete last line")
        if re.search(r"\w+\s*$", last) and not last.endswith(";") and not last.endswith("{") and not last.endswith("}"):
            if "java" in code.lower() or "public " in code or "private " in code:
                if not last.endswith(")") and not last.endswith("*/"):
                    problems.append(f"suspicious truncated line: {last[:40]}")
    return problems


def check_lang_tag(lang: str, code: str) -> str | None:
    lang = (lang or "").lower()
    if not lang:
        if re.search(r"\b(public|private|class|void|import)\b", code):
            return "missing lang tag (looks like java)"
        if re.search(r"^flowchart|^sequenceDiagram|^graph ", code, re.MULTILINE):
            return "missing lang tag (looks like mermaid)"
        return "missing lang tag"
    if lang == "java" and re.search(r"^flowchart|^sequenceDiagram", code, re.MULTILINE):
        return f"wrong lang '{lang}' for mermaid content"
    if lang == "mermaid" and re.search(r"\bpublic\s+(class|void)\b", code):
        return f"wrong lang '{lang}' for java content"
    return None


def slug_issues(slug: str, title: str, domain: str) -> list[str]:
    issues = []
    if MODULE_PATH_SLUG_RE.search(slug):
        issues.append(f"module-path slug corruption: {slug}")
    if slug in GENERIC_SLUGS:
        issues.append(f"overly generic slug: {slug}")
    # pinyin slug check
    if PINYIN_SLUG_RE.match(slug) and not slug.startswith(domain.split("-")[0]):
        # heuristic: long hyphenated ascii without domain prefix
        if any(part in slug for part in ["zhi-you", "shu-ju", "chengyuan", "guan-xi"]):
            issues.append(f"pinyin slug: {slug}")
    # title consistency
    title_slug_map = {
        "relation-management": "挚友关系管理",
        "zhi-you-pei-zhi-yu-kuo-zhan": "挚友配置与扩展",
        "zhi-you-ye-wu-fu-wu": "挚友业务服务",
        "family": "家族榜单展示",
        "family-task": "家族",
        "family-square": "家族广场核心服务",
        "family-operation": "家族运营支持",
        "family-member-management": "家族成员管理",
        "family-management": "家族创建与配额管理",
        "family-task-system": "家族任务体系",
        "family-relation-member-management": "家族关系与成员管理",
        "intimacy-relation-task-system": "亲密关系任务体系",
        "shu-ju-lei-xing-yu-ji-chu-zhi-chi": "数据类型与基础支持",
    }
    if slug in title_slug_map and title_slug_map[slug] not in title:
        issues.append(f"slug/title mismatch: slug={slug}, title={title}")
    if slug.startswith("ultronultron"):
        issues.append(f"concatenated module slug: {slug}")
    if "Part" in title and "ultronultron" in slug:
        issues.append(f"Part topic with module slug instead of semantic slug")
    return issues


def audit_topic(page: dict[str, Any], all_titles: set[str], overview_wikilinks: dict[str, list[str]]) -> TopicAudit:
    content = page.get("content") or ""
    path = page.get("path") or ""
    title = page.get("title") or ""
    domain = extract_domain(path)
    slug = extract_slug(path)
    h2_list = re.findall(r"^## (.+)$", content, re.MULTILINE)

    audit = TopicAudit(
        title=title,
        path=path,
        domain=domain,
        slug=slug,
        content_length=len(content),
        cn_ratio=page.get("cn_ratio") or compute_cn_ratio(content),
        code_block_count=0,
        h2_count=len(h2_list),
        h2_list=h2_list,
    )

    # 1. Content length
    if audit.content_length < 1000:
        audit.add("P1", "content_length", f"thin content ({audit.content_length} chars)", 8)
    if audit.content_length > 8000:
        audit.add("P2", "content_length", f"overlong content ({audit.content_length} chars)", 3)

    # 2. Code blocks
    blocks = CODE_BLOCK_RE.findall(content)
    audit.code_block_count = len(blocks)
    if audit.code_block_count == 0:
        audit.add("P0", "code_blocks", "zero code blocks — topic must have code examples", 20)

    seen_blocks: dict[str, int] = {}
    for lang, code in blocks:
        normalized = code.strip()
        if normalized in seen_blocks:
            audit.add("P1", "code_blocks", f"duplicate code block (appears {seen_blocks[normalized]+1}x)", 6)
        seen_blocks[normalized] = seen_blocks.get(normalized, 0) + 1

        trunc = check_code_truncation(code)
        if trunc:
            audit.add("P0", "code_truncation", "; ".join(trunc), 12)

        lang_issue = check_lang_tag(lang, code)
        if lang_issue:
            audit.add("P2", "code_lang", lang_issue, 2)

        for pat in PSEUDO_CODE_MARKERS:
            if pat.search(code):
                audit.add("P0", "pseudo_code", f"suspected fabricated code: {pat.pattern[:40]}", 15)
                break

    # 3. Chinese quality
    if audit.cn_ratio < 0.3:
        audit.add("P1", "cn_ratio", f"low cn_ratio={audit.cn_ratio:.4f}", 10)

    for pat in LLM_TRACE_PATTERNS:
        m = pat.search(content)
        if m:
            audit.add("P1", "llm_trace", f"English LLM trace: {m.group()[:50]}", 8)

    for pat in META_SECTION_PATTERNS:
        if pat.search(content):
            audit.add("P1", "meta_section", f"meta section residue: {pat.pattern[:40]}", 6)

    if H1_RE.search(content):
        audit.add("P1", "h1_leak", "H1 title leaked into body", 5)

    for flag in page.get("hallucination_flags") or detect_hallucination_flags(content):
        audit.add("P0", "hallucination", flag, 12)

    # 4. Structure
    substantive_h2 = [h for h in h2_list if h not in {"相关主题", "章节导航", "待完善项"}]
    if len(substantive_h2) <= 1:
        audit.add("P1", "structure", f"fragmented — only {len(substantive_h2)} substantive H2", 8)

    vague_only = all(any(v in h for v in VAGUE_H2) for h in substantive_h2[:3]) if substantive_h2 else False
    if vague_only and len(substantive_h2) <= 3:
        audit.add("P2", "structure", "H2 headings are mostly generic template sections", 3)

    # Part topics with empty sections
    if re.search(r"^## .+\n\s*$", content, re.MULTILINE):
        audit.add("P1", "structure", "empty H2 section detected", 5)

    # 5. Slug
    for si in slug_issues(slug, title, domain):
        sev = "P0" if "ultronultron" in si or "corruption" in si else "P1"
        audit.add(sev, "slug", si, 10 if sev == "P0" else 5)

    # 6. Wikilinks
    wikilinks = WIKILINK_RE.findall(content)
    for link in wikilinks:
        target = link.strip()
        if not target:
            audit.add("P1", "wikilink", "empty wikilink", 5)
        elif target not in all_titles and not any(target in t for t in all_titles):
            audit.add("P1", "wikilink", f"dangling wikilink: [[{target}]]", 6)

    # overview reference
    ov_links = overview_wikilinks.get(domain, [])
    if title not in ov_links and not any(title in lk for lk in ov_links):
        # check if overview mentions this topic via wikilink
        audit.add("P2", "wikilink", f"not referenced in domain overview wikilinks", 3)

    # 7. Domain match — cross-domain mentions
    all_domains = set(re.findall(r"/__domains__/([^/]+)/", content))
    foreign = all_domains - {domain}
    if foreign:
        audit.add("P2", "domain_match", f"mentions other domains in paths: {foreign}", 3)

    # Count references to other domain names in prose
    domain_keywords = {
        "closed-friend-system": ["挚友系统", "closed-friend-system"],
        "closed-friend-task": ["挚友任务", "closed-friend-task"],
        "family-operation": ["家族运营", "family-operation"],
        "family-square": ["家族广场", "family-square"],
        "family-power-rank": ["家族榜单", "family-power-rank"],
        "intimacy-relationship": ["亲密度", "intimacy-relationship"],
        "relation-rank-service": ["关系榜单", "relation-rank"],
        "user-profile-service": ["用户资料", "user-profile"],
        "user-vip-level": ["用户等级", "vip-level"],
    }
    other_domain_hits = 0
    for other_dom, kws in domain_keywords.items():
        if other_dom == domain:
            continue
        for kw in kws:
            if kw in content and kw not in title:
                other_domain_hits += content.count(kw)
    if other_domain_hits > 5:
        audit.add("P2", "domain_match", f"possible cross-domain content overflow ({other_domain_hits} refs)", 4)

    audit.score = max(0, audit.score)
    return audit


def main() -> None:
    json_path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/wiki-audit-v22.json")
    data = json.loads(json_path.read_text())
    pages = data["pages"]
    topics = [p for p in pages if p.get("page_type") == "topic"]
    overviews = [p for p in pages if p.get("page_type") == "domain_overview"]
    all_titles = {p.get("title", "") for p in pages}

    overview_wikilinks: dict[str, list[str]] = {}
    for ov in overviews:
        dom = extract_domain(ov.get("path", ""))
        links = WIKILINK_RE.findall(ov.get("content") or "")
        overview_wikilinks[dom] = links

    audits = [audit_topic(t, all_titles, overview_wikilinks) for t in topics]

    # Domain coverage
    all_domains = {extract_domain(o["path"]) for o in overviews}
    domains_with_topics = {a.domain for a in audits}
    domains_zero = sorted(all_domains - domains_with_topics)
    topic_per_domain = Counter(a.domain for a in audits)

    # Aggregate stats
    lengths = [a.content_length for a in audits]
    cn_ratios = [a.cn_ratio for a in audits]
    code_counts = [a.code_block_count for a in audits]
    thin = [a for a in audits if a.content_length < 1000]
    overlong = [a for a in audits if a.content_length > 8000]
    zero_code = [a for a in audits if a.code_block_count == 0]
    low_cn = [a for a in audits if a.cn_ratio < 0.3]
    truncated = [a for a in audits if any(c == "code_truncation" for _, c, _ in a.issues)]
    dup_code = [a for a in audits if any(c == "code_blocks" and "duplicate" in d for _, c, d in a.issues)]
    slug_bad = [a for a in audits if any(c == "slug" for _, c, _ in a.issues)]
    dangling = [a for a in audits if any(c == "wikilink" and "dangling" in d for _, c, d in a.issues)]
    llm_trace = [a for a in audits if any(c == "llm_trace" for _, c, _ in a.issues)]
    meta = [a for a in audits if any(c == "meta_section" for _, c, _ in a.issues)]
    h1_leak = [a for a in audits if any(c == "h1_leak" for _, c, _ in a.issues)]
    fragmented = [a for a in audits if any(c == "structure" and "fragmented" in d for _, c, d in a.issues)]
    pseudo = [a for a in audits if any(c == "pseudo_code" for _, c, _ in a.issues)]

    # All issues flat
    all_issues: list[tuple[str, str, str, str]] = []
    for a in audits:
        for sev, cat, detail in a.issues:
            all_issues.append((sev, a.title, cat, detail))
    sev_order = {"P0": 0, "P1": 1, "P2": 2}
    all_issues.sort(key=lambda x: (sev_order.get(x[0], 9), x[2], x[1]))

    worst = sorted(audits, key=lambda a: a.score)[:5]
    best = sorted(audits, key=lambda a: -a.score)[:5]

    report = {
        "summary_stats": {
            "topic_count": len(topics),
            "domain_count": len(all_domains),
            "domains_with_topics": len(domains_with_topics),
            "domains_zero_topics": len(domains_zero),
            "avg_topics_per_domain": round(len(topics) / len(all_domains), 2),
            "avg_content_length": round(sum(lengths) / len(lengths)),
            "min_content_length": min(lengths),
            "max_content_length": max(lengths),
            "thin_content_count_lt_1000": len(thin),
            "overlong_count_gt_8000": len(overlong),
            "avg_cn_ratio": round(sum(cn_ratios) / len(cn_ratios), 4),
            "low_cn_ratio_lt_0.3": len(low_cn),
            "avg_code_blocks": round(sum(code_counts) / len(code_counts), 1),
            "zero_code_topics": len(zero_code),
            "truncated_code_topics": len(truncated),
            "duplicate_code_topics": len(dup_code),
            "slug_issue_topics": len(slug_bad),
            "dangling_wikilink_topics": len(dangling),
            "llm_trace_topics": len(llm_trace),
            "meta_section_topics": len(meta),
            "h1_leak_topics": len(h1_leak),
            "fragmented_structure_topics": len(fragmented),
            "pseudo_code_topics": len(pseudo),
        },
        "domains_zero_topics": domains_zero,
        "topics_per_domain": dict(topic_per_domain),
        "all_issues": all_issues,
        "worst_topics": [
            {"title": a.title, "score": a.score, "issues": a.issues, "path": a.path} for a in worst
        ],
        "best_topics": [
            {"title": a.title, "score": a.score, "content_length": a.content_length, "code_blocks": a.code_block_count, "path": a.path}
            for a in best
        ],
        "slug_details": [],
        "topic_details": [
            {
                "title": a.title,
                "domain": a.domain,
                "slug": a.slug,
                "content_length": a.content_length,
                "cn_ratio": a.cn_ratio,
                "code_blocks": a.code_block_count,
                "h2_count": a.h2_count,
                "score": a.score,
                "issues": a.issues,
            }
            for a in sorted(audits, key=lambda x: x.score)
        ],
    }

    # Fix slug_details
    report["slug_details"] = []
    for a in audits:
        slug_issues_list = [d for _, cat, d in a.issues if cat == "slug"]
        if slug_issues_list:
            report["slug_details"].append({"title": a.title, "slug": a.slug, "domain": a.domain, "issues": slug_issues_list})

    out_path = json_path.with_name(json_path.stem + "-topic-audit.json")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
