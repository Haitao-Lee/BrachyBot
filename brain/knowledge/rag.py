"""
RAG Module for BrachyAgent
==========================
Retrieval-Augmented Generation for domain knowledge.
Based on MedAgent-Pro's RAG.py approach.
"""

import os
import json
import hashlib
from typing import List, Dict, Any, Optional


class SimpleRAG:
    """
    Simple RAG implementation for brachytherapy domain knowledge.
    In production, could be connected to a vector database.
    """

    def __init__(self, knowledge_base: Optional[str] = None):
        self.knowledge_base = knowledge_base or self._default_knowledge_base()
        self._cache: Dict[str, Any] = {}

    def _default_knowledge_base(self) -> str:
        kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
        if os.path.exists(kb_path):
            return kb_path
        return ""

    def retrieve(self, query: str, top_k: int = 5) -> List[str]:
        """
        Retrieve relevant knowledge chunks for a query.
        """
        cache_key = hashlib.md5(f"{query}:{top_k}".encode()).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]

        results = []

        if os.path.exists(self.knowledge_base):
            with open(self.knowledge_base, "r", encoding="utf-8") as f:
                kb_data = json.load(f)
                chunks = kb_data.get("chunks", [])
                query_lower = query.lower()
                for chunk in chunks:
                    text = chunk.get("text", "").lower()
                    if any(keyword in text for keyword in query_lower.split()):
                        results.append(chunk.get("text"))
                        if len(results) >= top_k:
                            break

        if not results:
            results = self._default_response(query)

        self._cache[cache_key] = results
        return results

    def _default_response(self, query: str) -> List[str]:
        """Default responses when no specific knowledge found."""
        defaults = {
            "ctv": [
                "CTV (Clinical Target Volume) includes the visible tumor and suspected subclinical spread.",
                "CTV segmentation requires anatomical knowledge and clinical judgment."
            ],
            "oar": [
                "OAR (Organ at Risk) are normal tissues that may be affected by radiation.",
                "OAR constraints are based on clinical tolerance doses (TD5/5, TD50/5)."
            ],
            "dose": [
                "Dose evaluation uses metrics like V100, V150, D90, D2cc for plan assessment.",
                "Prescription dose depends on cancer type and treatment intent."
            ],
            "seed": [
                "Seed placement follows established patterns for uniform dose distribution.",
                "Pd-103 and I-125 are common isotopes for permanent brachytherapy."
            ],
            "trajectory": [
                "Trajectory planning optimizes needle paths to minimize OAR exposure.",
                "Parallel catheters are typically used for uniformity."
            ],
        }

        results = []
        query_lower = query.lower()
        for key, texts in defaults.items():
            if key in query_lower:
                results.extend(texts)
        return results[:3]


class DoseRAG(SimpleRAG):
    """RAG specialized for dose constraints and tolerances."""

    def __init__(self):
        super().__init__()
        self._dose_constraints = {
            "pancreas": {
                "duodenum": {"D0.1cc": 30.0, "D2cc": 18.0, "unit": "Gy"},
                "stomach": {"D0.1cc": 30.0, "D2cc": 18.0, "unit": "Gy"},
                "small_bowel": {"D0.1cc": 30.0, "D2cc": 18.0, "unit": "Gy"},
            },
            "prostate": {
                "rectum": {"D0.1cc": 50.0, "D2cc": 35.0, "D10": 30.0, "unit": "Gy"},
                "bladder": {"D0.1cc": 50.0, "D2cc": 35.0, "D10": 30.0, "unit": "Gy"},
                "urethra": {"D10": 55.0, "D30": 50.0, "unit": "Gy"},
            },
            "lung": {
                "spinal_cord": {"D0.1cc": 10.0, "D1cc": 7.0, "unit": "Gy"},
                "heart": {"D1cc": 30.0, "D2cc": 25.0, "unit": "Gy"},
            }
        }

    def get_constraints(self, anatomy: str) -> Dict[str, Any]:
        """Get dose constraints for a specific anatomy."""
        return self._dose_constraints.get(anatomy.lower(), {})

    def retrieve_dose_constraints(self, anatomy: str, oar_name: str) -> Optional[Dict]:
        """Get specific OAR constraints."""
        constraints = self.get_constraints(anatomy)
        return constraints.get(oar_name.lower())


_rag_instance: Optional[DoseRAG] = None


def get_rag() -> DoseRAG:
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = DoseRAG()
    return _rag_instance
