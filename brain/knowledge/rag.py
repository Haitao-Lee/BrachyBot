"""Lightweight retrieval over BrachyBot's authoritative clinical KB."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


_REPO_ROOT = Path(__file__).resolve().parents[2]
_AUTHORITATIVE_KB = (
    _REPO_ROOT / "tool_factory" / "clinical_kb" / "data" / "knowledge_base.json"
)


def _tokens(text: str) -> List[str]:
    lowered = str(text).lower()
    tokens = re.findall(r"[a-z0-9][a-z0-9_.-]*", lowered)
    for sequence in re.findall(r"[\u3400-\u9fff]+", lowered):
        tokens.extend(
            [sequence] if len(sequence) == 1
            else [sequence[i:i + 2] for i in range(len(sequence) - 1)]
        )
    return tokens


def _urls(value: Any) -> List[str]:
    found: List[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"source_url", "url", "doi_url"} and isinstance(item, str):
                if item.startswith("http"):
                    found.append(item)
            elif key in {"source_urls", "sources"} and isinstance(item, list):
                found.extend(str(url) for url in item if str(url).startswith("http"))
            else:
                found.extend(_urls(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_urls(item))
    return list(dict.fromkeys(found))


class SimpleRAG:
    """Dependency-free BM25 retrieval with citation-bearing output chunks."""

    def __init__(self, knowledge_base: Optional[str] = None):
        self.knowledge_base = Path(knowledge_base) if knowledge_base else _AUTHORITATIVE_KB
        self._cache: Dict[str, List[str]] = {}
        self._documents: Optional[List[Dict[str, Any]]] = None

    def _load(self) -> Dict[str, Any]:
        if not self.knowledge_base.exists():
            return {}
        return json.loads(self.knowledge_base.read_text(encoding="utf-8"))

    def _build_documents(self) -> List[Dict[str, Any]]:
        data = self._load()
        documents: List[Dict[str, Any]] = []

        for site, site_data in (data.get("dose_standards") or {}).items():
            modalities = site_data if isinstance(site_data, dict) else {}
            if any(key in modalities for key in ("target", "oar", "source")):
                modalities = {"unspecified": modalities}
            for modality, standard in modalities.items():
                if not isinstance(standard, dict):
                    continue
                links = _urls(standard)
                documents.append({
                    "title": f"{site} {modality} dose standard",
                    "body": json.dumps(standard, ensure_ascii=False, sort_keys=True),
                    "urls": links,
                })

        for source_id, source in (data.get("evidence_sources") or {}).items():
            if not isinstance(source, dict):
                continue
            documents.append({
                "title": str(source.get("title") or source_id),
                "body": json.dumps(source, ensure_ascii=False, sort_keys=True),
                "urls": _urls(source),
            })

        for section in ("organ_tolerances", "treatment_protocols"):
            for name, entry in (data.get(section) or {}).items():
                documents.append({
                    "title": f"{section.replace('_', ' ')}: {name}",
                    "body": json.dumps(entry, ensure_ascii=False, sort_keys=True),
                    "urls": _urls(entry),
                })

        for document in documents:
            document["tokens"] = _tokens(document["title"] + " " + document["body"])
        return documents

    def retrieve(self, query: str, top_k: int = 5) -> List[str]:
        cache_key = hashlib.sha256(f"{query}:{top_k}".encode("utf-8")).hexdigest()
        if cache_key in self._cache:
            return list(self._cache[cache_key])

        if self._documents is None:
            self._documents = self._build_documents()
        query_terms = _tokens(query)
        if not query_terms or not self._documents:
            return []

        doc_freq = Counter()
        for document in self._documents:
            doc_freq.update(set(document["tokens"]))
        avg_len = sum(len(d["tokens"]) for d in self._documents) / len(self._documents)
        scored = []
        for document in self._documents:
            frequencies = Counter(document["tokens"])
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                idf = math.log(1 + (len(self._documents) - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
                denominator = frequency + 1.2 * (
                    1 - 0.75 + 0.75 * len(document["tokens"]) / max(avg_len, 1)
                )
                score += idf * frequency * 2.2 / denominator
            if score:
                scored.append((score, document))

        results: List[str] = []
        for _, document in sorted(scored, key=lambda item: item[0], reverse=True)[:top_k]:
            citations = " ".join(f"[{url}]({url})" for url in document["urls"])
            suffix = f" Sources: {citations}" if citations else " Source link unavailable; do not use as a clinical limit."
            results.append(f"{document['title']}: {document['body']}{suffix}")
        self._cache[cache_key] = results
        return list(results)


class DoseRAG(SimpleRAG):
    """Compatibility API backed by the same source-traceable KB."""

    _ALIASES = {"pancreas": "pancreatic", "cervix": "cervical"}

    def get_constraints(self, anatomy: str) -> Dict[str, Any]:
        data = self._load().get("dose_standards", {})
        site = self._ALIASES.get(str(anatomy).lower(), str(anatomy).lower())
        site_data = data.get(site, {})
        if not isinstance(site_data, dict):
            return {}
        if "oar" in site_data:
            return dict(site_data.get("oar") or {})
        for modality in ("ldr", "hdr", "apbi"):
            standard = site_data.get(modality)
            if isinstance(standard, dict):
                result = dict(standard.get("oar") or {})
                result["_source"] = {
                    "title": standard.get("source", ""),
                    "urls": standard.get("source_urls", []),
                    "modality": modality,
                }
                return result
        return {}

    def retrieve_dose_constraints(self, anatomy: str,
                                    oar_name: str) -> Optional[Dict[str, Any]]:
        constraints = self.get_constraints(anatomy)
        return constraints.get(str(oar_name).lower())


_rag_instance: Optional[DoseRAG] = None


def get_rag() -> DoseRAG:
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = DoseRAG()
    return _rag_instance
