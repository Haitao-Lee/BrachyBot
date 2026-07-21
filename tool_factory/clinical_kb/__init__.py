"""
Clinical Knowledge Base Tool
============================
Evidence-backed retrieval for brachytherapy guidelines, source papers,
dose standards, organ tolerances, and treatment protocols.

Design goals:
- Keep the historical JSON API stable for existing agents.
- Index raw markdown source files under clinical_kb/sources at runtime.
- Return clickable source URLs for every retrieved clinical fact.
- Cache disk reads so repeated clinical lookups are cheap.
"""

import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parents[1]
KB_DIR = TOOL_DIR / "data"
SOURCE_ROOT = REPO_ROOT / "clinical_kb" / "sources"
GUIDELINES_PATH = REPO_ROOT / "clinical_kb" / "guidelines_brachytherapy.md"
GUIDELINES_DIR = REPO_ROOT / "clinical_kb" / "guidelines"
# Review proposals are runtime data, not source-controlled KB content.  Keep
# the queue outside the package so an installed/read-only checkout can still
# accept proposals without mutating the clinical corpus.
REVIEW_QUEUE_PATH = Path(
    os.environ.get(
        "BRACHYBOT_KB_REVIEW_QUEUE",
        str(REPO_ROOT / ".runtime" / "clinical_kb_review_queue.json"),
    )
).expanduser()

_GENERIC_QUERY_TERMS = {
    "brachytherapy", "bt", "guideline", "guidelines", "consensus", "review",
    "dose", "doses", "treatment", "therapy", "clinical", "source", "paper",
    "literature", "protocol", "protocols", "cancer", "tumor", "tumour",
    "iodine", "seed", "seeds", "i125", "125i", "permanent", "interstitial",
}


_DEFAULT_KB = {
    "dose_standards": {
        "prostate": {
            "ldr": {
                "target": {"v100_min": 0.95, "d90_min_pct": 1.00, "v150_max": 0.50, "v200_max": 0.35},
                "oar": {"urethra": {"dmax_pct": 1.20}, "rectum": {"d2cc_gy_eqd2": 75}, "bladder": {"d2cc_gy_eqd2": 90}},
                "source": "ABS/AUA/ASTRO 2012 prostate permanent seed consensus",
                "source_urls": ["https://pubmed.ncbi.nlm.nih.gov/22265434/"],
            }
        },
        "cervical": {
            "hdr": {
                "target": {"v100_min": 0.90, "d90_gy_eqd2_min": 85},
                "oar": {"bladder": {"d2cc_gy_eqd2": 90}, "rectum": {"d2cc_gy_eqd2": 75}, "sigmoid": {"d2cc_gy_eqd2": 70}},
                "source": "ABS cervix HDR consensus and ICRU Report 89",
                "source_urls": ["https://pubmed.ncbi.nlm.nih.gov/22265437/", "https://www.icru.org/report/icru-report-89-prescribing-recording-and-reporting-brachytherapy-for-cancer-of-the-cervix/"],
            }
        },
        "pancreatic": {
            "ldr": {
                "target": {"v100_min": 0.90, "d90_min_pct": 1.00, "v200_max": 0.30},
                "oar": {
                    "duodenum": {"d2cc_gy": 55, "dmax_gy": 75},
                    "stomach": {"d2cc_gy": 55, "dmax_gy": 75},
                    "bowel": {"d2cc_gy": 55, "dmax_gy": 75},
                },
                "source": "Chinese pancreatic permanent iodine-125 seed guideline",
                "source_urls": ["https://pubmed.ncbi.nlm.nih.gov/39206973/"],
            }
        },
        "default": {
            "target": {"v100_min": 0.90, "d90_min_pct": 1.00, "v200_max": 0.35},
            "source": "Composite fallback from ABS/GEC-ESTRO/AAPM references",
            "source_urls": ["https://www.americanbrachytherapy.org/spotonbrachy/clinical-guidelines/"],
        },
    },
    "organ_tolerances": {},
    "treatment_protocols": {},
    "plan_quality_benchmarks": {
        "excellent": {"min_score": 90, "v100_min": 0.95, "v200_max": 0.25},
        "good": {"min_score": 80, "v100_min": 0.90, "v200_max": 0.35},
        "acceptable": {"min_score": 70, "v100_min": 0.85, "v200_max": 0.40},
        "marginal": {"min_score": 60, "v100_min": 0.80, "v200_max": 0.45},
    },
}


def _ensure_default_kb() -> None:
    kb_file = KB_DIR / "knowledge_base.json"
    if not kb_file.exists():
        kb_file.write_text(json.dumps(_DEFAULT_KB, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Initialized default clinical knowledge base")
        return
    try:
        json.loads(kb_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        backup = kb_file.with_suffix(".invalid.json")
        kb_file.replace(backup)
        kb_file.write_text(json.dumps(_DEFAULT_KB, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.warning("Reinitialized corrupt clinical knowledge base; backup saved to %s: %s", backup, exc)


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _norm(text)).strip("_")


def _yaml_scalar(value: str) -> Any:
    value = value.strip().strip('"').strip("'")
    if value in {"N/A", "n/a", "NA", ""}:
        return value
    return value


def _extract_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        return {}, text
    meta: Dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = _yaml_scalar(value)
    return meta, text[match.end():]


def _strip_markdown(text: str, limit: int = 700) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _canonical_source_url(meta: Dict[str, Any]) -> str:
    """Prefer stable exact links over generic search URLs."""
    pmid = str(meta.get("pmid") or "").strip()
    doi = str(meta.get("doi") or "").strip()
    url = str(meta.get("url") or "").strip()

    if pmid and pmid != "N/A" and pmid.isdigit():
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    if doi and doi != "N/A":
        return f"https://doi.org/{doi}"
    if url.startswith("http"):
        return url
    return ""


def _collect_urls(obj: Any) -> List[str]:
    urls: List[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in {"source_url", "url"} and isinstance(value, str) and value.startswith("http"):
                urls.append(value)
            elif key in {"source_urls", "sources"} and isinstance(value, list):
                urls.extend([u for u in value if isinstance(u, str) and u.startswith("http")])
            else:
                urls.extend(_collect_urls(value))
    elif isinstance(obj, list):
        for item in obj:
            urls.extend(_collect_urls(item))

    seen = set()
    deduped = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def _guideline_paths() -> List[Path]:
    """Return the stable guideline index plus split topic files in search order."""
    paths: List[Path] = []
    if GUIDELINES_PATH.exists():
        paths.append(GUIDELINES_PATH)
    if GUIDELINES_DIR.exists():
        paths.extend(sorted(GUIDELINES_DIR.glob("*.md")))
    return paths


class ClinicalKnowledgeBaseTool(BaseTool):
    """Query clinical guidelines, dose constraints, and treatment protocols."""

    name = "clinical_kb"
    description = """Evidence-backed clinical knowledge base for brachytherapy.
Actions:
- standards: site-specific dose standards with citations
- constraints: organ or disease dose constraints
- tolerance: organ tolerance limits
- protocol: treatment protocol summaries
- benchmark: plan quality classification
- search: combined JSON + raw source search
- guidelines: authoritative guideline/source search
- source_search: raw source-only retrieval
- add: add a JSON entry"""

    input_schema = {
        "action": {
            "type": "string",
            "description": "Action to run",
            "enum": [
                "standards", "constraints", "tolerance", "protocol", "benchmark",
                "search", "guidelines", "source_search", "add",
            ],
        },
        "organ": {"type": "string", "description": "Organ or cancer site name"},
        "keyword": {"type": "string", "description": "Search keyword"},
        "data": {"type": "object", "description": "Data payload for benchmark/add"},
    }
    output_schema = {"success": {"type": "boolean"}, "data": {"type": "object"}}

    def __init__(self) -> None:
        self._kb_cache: Optional[Dict[str, Any]] = None
        self._kb_mtime: float = -1
        self._source_cache: Optional[List[Dict[str, Any]]] = None
        self._source_mtime: float = -1

    def _load_kb(self) -> Dict[str, Any]:
        kb_file = KB_DIR / "knowledge_base.json"
        if not kb_file.exists():
            logger.warning("Clinical KB file is missing; using the in-memory fallback")
            return _DEFAULT_KB
        try:
            mtime = kb_file.stat().st_mtime
            if self._kb_cache is not None and mtime == self._kb_mtime:
                return self._kb_cache
            self._kb_cache = json.loads(kb_file.read_text(encoding="utf-8"))
            self._kb_mtime = mtime
            return self._kb_cache
        except Exception as exc:
            logger.warning("Failed to load clinical KB JSON: %s", exc)
            return _DEFAULT_KB

    def _save_kb(self, kb: Dict[str, Any]) -> None:
        KB_DIR.mkdir(parents=True, exist_ok=True)
        kb_file = KB_DIR / "knowledge_base.json"
        kb_file.write_text(json.dumps(kb, indent=2, ensure_ascii=False), encoding="utf-8")
        self._kb_cache = kb
        self._kb_mtime = kb_file.stat().st_mtime

    def _source_tree_mtime(self) -> float:
        if not SOURCE_ROOT.exists():
            return -1
        latest = SOURCE_ROOT.stat().st_mtime
        for path in SOURCE_ROOT.glob("**/raw/*.md"):
            try:
                latest = max(latest, path.stat().st_mtime)
            except OSError:
                continue
        return latest

    def _load_source_index(self) -> List[Dict[str, Any]]:
        latest = self._source_tree_mtime()
        if self._source_cache is not None and latest == self._source_mtime:
            return self._source_cache

        entries: List[Dict[str, Any]] = []
        if not SOURCE_ROOT.exists():
            self._source_cache = entries
            self._source_mtime = latest
            return entries

        for path in SOURCE_ROOT.glob("**/raw/*.md"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta, body = _extract_frontmatter(text)
            title = str(meta.get("title") or path.stem)
            url = _canonical_source_url(meta)
            relative = path.relative_to(SOURCE_ROOT).as_posix()
            raw_blob = " ".join(
                str(meta.get(k) or "")
                for k in ("title", "authors", "journal", "doc_type", "category", "priority", "doi", "pmid", "url")
            )
            entry = {
                "id": _slug(relative.replace("/raw/", "/").replace(".md", "")),
                "title": title,
                "category": str(meta.get("category") or path.parts[-3]),
                "doc_type": str(meta.get("doc_type") or ""),
                "priority": str(meta.get("priority") or "P2"),
                "year": str(meta.get("year") or ""),
                "journal": str(meta.get("journal") or ""),
                "doi": str(meta.get("doi") or ""),
                "pmid": str(meta.get("pmid") or ""),
                "url": url,
                "source_file": str(path),
                "source_path": relative,
                "fetch_method": str(meta.get("fetch_method") or ""),
                "verification_status": "verified_link" if url else "no_exact_link",
                "search_text": _norm(raw_blob + " " + body),
                "excerpt": _strip_markdown(body),
            }
            entries.append(entry)

        self._source_cache = entries
        self._source_mtime = latest
        return entries

    def _rank_source(self, entry: Dict[str, Any], terms: List[str], organ: str = "") -> int:
        text = entry.get("search_text", "")
        title = _norm(entry.get("title", ""))
        score = 0
        for term in terms:
            if not term:
                continue
            if term in title:
                score += 45
            if term in text:
                score += min(30, text.count(term) * 6)
        organ_norm = _norm(organ)
        if organ_norm and organ_norm in text:
            score += 35
        priority = entry.get("priority")
        score += {"P0": 18, "P1": 8, "P2": 2}.get(priority, 0)
        doc_type = _norm(entry.get("doc_type"))
        if any(x in doc_type for x in ("guideline", "consensus", "task_group", "report")):
            score += 15
        if entry.get("verification_status") == "verified_link":
            score += 8
        if entry.get("fetch_method") == "metadata-stub" and not entry.get("pmid") and not entry.get("doi"):
            score -= 25
        return score

    def _search_sources(self, keyword: str, organ: str = "", limit: int = 8) -> List[Dict[str, Any]]:
        terms = [_norm(t) for t in re.split(r"[\s,;/|]+", keyword or "") if _norm(t)]
        if not terms and organ:
            terms = [_norm(organ)]
        if not terms:
            return []
        specific_terms = [t for t in terms if t not in _GENERIC_QUERY_TERMS and len(t) >= 3]

        ranked: List[Tuple[int, Dict[str, Any]]] = []
        for entry in self._load_source_index():
            haystack = entry.get("search_text", "")
            if specific_terms and not any(term in haystack for term in specific_terms):
                continue
            score = self._rank_source(entry, terms, organ)
            if score > 0:
                ranked.append((score, entry))
        ranked.sort(key=lambda item: item[0], reverse=True)

        results = []
        for score, entry in ranked[:limit]:
            public = {k: entry[k] for k in (
                "id", "title", "category", "doc_type", "priority", "year",
                "journal", "doi", "pmid", "url", "source_path",
                "verification_status", "excerpt",
            )}
            public["score"] = score
            results.append(public)
        return results

    def _result(
        self,
        *,
        success: bool,
        data: Optional[Dict[str, Any]] = None,
        message: str = "",
        sources: Optional[List[str]] = None,
        error: Optional[str] = None,
    ) -> ToolResult:
        data = dict(data or {})
        sources = [u for u in (sources or _collect_urls(data)) if isinstance(u, str) and u.startswith("http")]
        seen = set()
        deduped = []
        for url in sources:
            if url not in seen:
                seen.add(url)
                deduped.append(url)
        if deduped:
            data["sources"] = deduped
            if "Sources:" not in message:
                message = f"{message}\nSources: {', '.join(deduped[:5])}".strip()
        return ToolResult(
            success=success,
            data=data,
            message=message,
            display=message,
            metadata={"sources": deduped} if deduped else {},
            error=error,
        )

    def _get_constraints(self, organ: str) -> ToolResult:
        kb = self._load_kb()
        organ_lower = _slug(organ)
        constraints = kb.get("dose_constraints", {}) or kb.get("legacy_dose_constraints", {})
        result = constraints.get(organ_lower)
        if result:
            sources = _collect_urls(result)
            return self._result(data={"organ": organ, "constraints": result}, message=f"Dose constraints for {organ}", sources=sources, success=True)

        matches = {k: v for k, v in constraints.items() if organ_lower and (organ_lower in k or k in organ_lower)}
        if matches:
            return self._result(data={"organ": organ, "matches": matches}, message=f"Found {len(matches)} matching constraint set(s)", sources=_collect_urls(matches), success=True)

        source_hits = self._search_sources(f"{organ} dose constraint tolerance", organ=organ, limit=5)
        return self._result(
            success=True,
            data={"organ": organ, "constraints": None, "source_results": source_hits, "available": list(constraints.keys())},
            message=f"No structured constraint table for '{organ}'. Returned source matches instead.",
            sources=[r.get("url", "") for r in source_hits],
        )

    def _get_tolerance(self, organ: str) -> ToolResult:
        kb = self._load_kb()
        organ_lower = _slug(organ)
        tolerances = kb.get("organ_tolerances", {})
        result = tolerances.get(organ_lower)
        if result:
            return self._result(success=True, data={"organ": organ, "tolerance": result}, message=f"Tolerance for {organ}", sources=_collect_urls(result))

        matches = {k: v for k, v in tolerances.items() if organ_lower and (organ_lower in k or k in organ_lower)}
        if matches:
            return self._result(success=True, data={"organ": organ, "matches": matches}, message=f"Found {len(matches)} tolerance match(es)", sources=_collect_urls(matches))

        source_hits = self._search_sources(f"{organ} organ tolerance D2cc max dose", organ=organ, limit=5)
        return self._result(
            success=True,
            data={"organ": organ, "tolerance": None, "source_results": source_hits, "available": list(tolerances.keys())},
            message=f"No structured tolerance row for '{organ}'. Returned source matches instead.",
            sources=[r.get("url", "") for r in source_hits],
        )

    def _get_protocol(self, protocol_name: str) -> ToolResult:
        kb = self._load_kb()
        protocols = kb.get("treatment_protocols", {})
        name_lower = _slug(protocol_name)
        if name_lower:
            result = protocols.get(name_lower)
            if result:
                return self._result(success=True, data={"protocol": protocol_name, "details": result}, message=f"Protocol: {protocol_name}", sources=_collect_urls(result))
            matches = {k: v for k, v in protocols.items() if name_lower in k or k in name_lower}
            if matches:
                return self._result(success=True, data={"matches": matches}, message=f"Found {len(matches)} protocol(s)", sources=_collect_urls(matches))

        source_hits = self._search_sources(f"{protocol_name} protocol guideline", limit=5) if protocol_name else []
        return self._result(
            success=True,
            data={"protocols": {k: v.get("description", "") for k, v in protocols.items()}, "source_results": source_hits},
            message=f"Available protocols: {', '.join(protocols.keys())}",
            sources=[r.get("url", "") for r in source_hits] or _collect_urls(protocols),
        )

    def _check_benchmark(self, metrics: Dict[str, Any]) -> ToolResult:
        kb = self._load_kb()
        benchmarks = kb.get("plan_quality_benchmarks", {})
        score = metrics.get("plan_score", 0)
        v100 = metrics.get("v100", 0)
        v200 = metrics.get("v200", 0)

        rating = "poor"
        for level, criteria in sorted(benchmarks.items(), key=lambda x: x[1].get("min_score", 0), reverse=True):
            if score >= criteria["min_score"] and v100 >= criteria["v100_min"] and v200 <= criteria["v200_max"]:
                rating = level
                break

        suggestions = []
        target = benchmarks.get("acceptable") or next(iter(benchmarks.values()), {})
        v100_min = target.get("v100_min")
        v200_max = target.get("v200_max")
        min_score = target.get("min_score")
        if v100_min is not None and v100 < v100_min:
            suggestions.append(f"V100 below KB benchmark {v100_min:.0%}: increase seed count or adjust positions")
        if v200_max is not None and v200 > v200_max:
            suggestions.append(f"V200 above KB benchmark {v200_max:.0%}: reduce seed density in high-dose regions")
        if min_score is not None and score < min_score:
            suggestions.append(f"Plan score below KB benchmark {min_score:.0f}: consider full re-optimization")

        return self._result(
            success=True,
            data={"rating": rating, "score": score, "v100": v100, "v200": v200, "suggestions": suggestions},
            message=f"Plan rated as '{rating}' (score: {score})",
            sources=_collect_urls(kb.get("dose_standards", {})),
        )

    def _search_kb(self, keyword: str) -> ToolResult:
        kb = self._load_kb()
        keyword_lower = _norm(keyword)
        json_results = []

        def search_dict(d: Dict[str, Any], path: str = "") -> None:
            for key, value in d.items():
                current_path = f"{path}.{key}" if path else key
                if isinstance(value, dict):
                    if keyword_lower and keyword_lower in _norm(key):
                        json_results.append({"path": current_path, "key": key, "value": {"summary": "container match"}})
                    search_dict(value, current_path)
                else:
                    haystack = _norm(key) + " " + _norm(value)
                    if keyword_lower and keyword_lower in haystack:
                        json_results.append({"path": current_path, "key": key, "value": value})

        if keyword_lower:
            search_dict(kb)
        source_results = self._search_sources(keyword, limit=10)
        sources = _collect_urls(json_results) + [r.get("url", "") for r in source_results]
        total = len(json_results) + len(source_results)
        return self._result(
            success=True,
            data={"keyword": keyword, "json_results": json_results[:20], "source_results": source_results, "total": total},
            message=f"Found {total} clinical KB match(es) for '{keyword}'",
            sources=sources,
        )

    def _add_entry(self, data: Dict[str, Any]) -> ToolResult:
        if not data or "category" not in data or "key" not in data:
            return self._result(success=False, error="Need category and key", message="Provide category, key, and value")
        kb = self._load_kb()
        category = data["category"]
        key = data["key"]
        value = data.get("value", {})
        kb.setdefault(category, {})[key] = value
        self._save_kb(kb)
        return self._result(success=True, data={"category": category, "key": key}, message=f"Added '{key}' to '{category}'", sources=_collect_urls(value))

    def _review_queue(self) -> List[Dict[str, Any]]:
        """Read the human-review queue; queued entries never affect retrieval."""
        try:
            payload = json.loads(REVIEW_QUEUE_PATH.read_text(encoding="utf-8"))
            return payload if isinstance(payload, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_review_queue(self, entries: List[Dict[str, Any]]) -> None:
        REVIEW_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = REVIEW_QUEUE_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(entries[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, REVIEW_QUEUE_PATH)

    def _propose_entry(self, data: Dict[str, Any]) -> ToolResult:
        """Queue a contribution instead of silently changing clinical evidence."""
        category = str(data.get("category") or "").strip()
        key = str(data.get("key") or "").strip()
        value = data.get("value", {})
        urls = _collect_urls(value)
        if not category or not key or not isinstance(value, (dict, list, str, int, float, bool)):
            return self._result(success=False, error="Need category, key, and JSON-compatible value")
        if not urls:
            return self._result(success=False, error="Every clinical contribution needs at least one source URL")
        entry = {
            "id": uuid.uuid4().hex,
            "status": "pending_review",
            "created_at": time.time(),
            "category": category,
            "key": key[:160],
            "value": value,
            "source_urls": urls[:20],
        }
        queue = self._review_queue()
        queue.append(entry)
        self._save_review_queue(queue)
        return self._result(
            success=True,
            data={"proposal": entry},
            message="Contribution queued for human review. It is not used for clinical retrieval until approved.",
            sources=urls,
        )

    def _refresh_source_manifest(self, data: Dict[str, Any]) -> ToolResult:
        """Create reviewable source candidates without auto-importing claims."""
        urls = data.get("urls") if isinstance(data.get("urls"), list) else []
        urls = [str(url).strip() for url in urls if str(url).strip()]
        if not urls:
            return self._result(success=False, error="Provide one or more source URLs to review")
        candidates = []
        for url in urls[:50]:
            is_http = url.startswith("https://") or url.startswith("http://")
            candidates.append({
                "url": url,
                "status": "candidate" if is_http else "rejected",
                "reason": "Awaiting content and citation verification" if is_http else "Only HTTP(S) sources are accepted",
            })
        return self._result(
            success=True,
            data={"candidates": candidates, "policy": "No source is added automatically; approve after independent citation and content review."},
            message=f"Prepared {sum(item['status'] == 'candidate' for item in candidates)} source candidate(s) for review.",
            sources=[item["url"] for item in candidates if item["status"] == "candidate"],
        )

    def _search_guidelines(self, keyword: str, organ: str = "") -> ToolResult:
        source_results = self._search_sources(keyword or organ, organ=organ, limit=8)

        section_matches = []
        for guideline_path in _guideline_paths():
            content = guideline_path.read_text(encoding="utf-8", errors="replace")
            parts = re.split(r"\n(?=## )", content)
            keyword_lower = _norm(keyword)
            organ_lower = _norm(organ)
            for section in parts:
                section_lower = _norm(section)
                if keyword_lower and keyword_lower not in section_lower:
                    continue
                if organ_lower and organ_lower not in section_lower:
                    continue
                if section.strip().startswith("## "):
                    urls = re.findall(r"https?://[^\s)]+", section)
                    section_matches.append({
                        "excerpt": section[:3000],
                        "urls": urls[:5],
                        "source_path": str(guideline_path.relative_to(REPO_ROOT)),
                    })
                if len(section_matches) >= 3:
                    break
            if len(section_matches) >= 3:
                break

        sources = [r.get("url", "") for r in source_results]
        for section in section_matches:
            sources.extend(section.get("urls", []))

        total = len(source_results) + len(section_matches)
        if total == 0:
            return self._result(success=True, data={"keyword": keyword, "organ": organ, "results": []}, message=f"No guideline/source sections match '{keyword}'")

        return self._result(
            success=True,
            data={
                "keyword": keyword,
                "organ": organ,
                "source_results": source_results,
                "section_results": section_matches,
                "total": total,
            },
            message=f"Found {total} guideline/source match(es) for '{keyword or organ}'",
            sources=sources,
        )

    def _get_standards(self, organ: str) -> ToolResult:
        kb = self._load_kb()
        standards = kb.get("dose_standards", {})
        organ_lower = _slug(organ)

        result = standards.get(organ_lower)
        site = organ_lower
        if not result:
            for key in standards:
                if organ_lower and (key in organ_lower or organ_lower in key):
                    result = standards[key]
                    site = key
                    break
        if not result:
            common_map = {
                "nnunet_pancreatic": "pancreatic",
                "pancreas": "pancreatic",
                "cervix": "cervical",
                "cervical": "cervical",
                "prostate": "prostate",
                "breast": "breast",
                "lung": "lung",
                "liver": "liver",
                "head_neck": "head_neck",
            }
            for pattern, mapped_site in common_map.items():
                if pattern in organ_lower:
                    result = standards.get(mapped_site)
                    site = mapped_site
                    break
        if not result:
            result = standards.get("default", {})
            site = "default"

        sources = _collect_urls(result)
        if not sources:
            source_text = f"{site} {result.get('source', '')}" if isinstance(result, dict) else site
            source_hits = self._search_sources(source_text, organ=site, limit=5)
            sources = [r.get("url", "") for r in source_hits]
        else:
            source_hits = []

        return self._result(
            success=True,
            data={"site": site, "standards": result, "source_results": source_hits},
            message=f"Dose standards for {site}",
            sources=sources,
        )

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "")
        if not action:
            return self._result(success=False, error="No action", message="Specify: standards, constraints, tolerance, protocol, benchmark, search, guidelines, source_search, add, propose, review_queue, refresh_sources")

        if action == "standards":
            return self._get_standards(kwargs.get("organ", ""))
        if action == "constraints":
            return self._get_constraints(kwargs.get("organ", ""))
        if action == "tolerance":
            return self._get_tolerance(kwargs.get("organ", ""))
        if action == "protocol":
            return self._get_protocol(kwargs.get("organ", ""))
        if action == "benchmark":
            return self._check_benchmark(kwargs.get("data", {}))
        if action == "search":
            return self._search_kb(kwargs.get("keyword", ""))
        if action == "guidelines":
            return self._search_guidelines(kwargs.get("keyword", ""), kwargs.get("organ", ""))
        if action == "source_search":
            keyword = kwargs.get("keyword", "") or kwargs.get("organ", "")
            results = self._search_sources(keyword, kwargs.get("organ", ""), limit=12)
            return self._result(
                success=True,
                data={"keyword": keyword, "source_results": results, "total": len(results)},
                message=f"Found {len(results)} source match(es) for '{keyword}'",
                sources=[r.get("url", "") for r in results],
            )
        if action == "add":
            return self._add_entry(kwargs.get("data", {}))
        if action == "propose":
            return self._propose_entry(kwargs.get("data", {}))
        if action == "review_queue":
            return self._result(success=True, data={"entries": self._review_queue()}, message="Returned pending clinical KB contributions for human review.")
        if action == "refresh_sources":
            return self._refresh_source_manifest(kwargs)
        return self._result(success=False, error=f"Unknown action: {action}", message="Valid: standards, constraints, tolerance, protocol, benchmark, search, guidelines, source_search, add, propose, review_queue, refresh_sources")
