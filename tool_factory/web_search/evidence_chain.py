"""
Evidence Chain Module
=====================
Provides traceable evidence tracking for all web-sourced information.

Every piece of information from the internet must have:
1. Source URL (permanent link when possible)
2. Access timestamp
3. Source type (PubMed, GitHub, manufacturer, etc.)
4. Confidence level
5. Verification status

This ensures clinical information is always verifiable and auditable.
"""

import os
import json
import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# Evidence storage directory
EVIDENCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evidence")
os.makedirs(EVIDENCE_DIR, exist_ok=True)


@dataclass
class EvidenceRecord:
    """A single piece of evidence with full traceability."""

    # Core identification
    evidence_id: str = ""
    claim: str = ""  # The information/fact being cited
    source_url: str = ""  # Permanent URL to the source
    source_type: str = ""  # pubmed, github, manufacturer, guideline, etc.
    source_title: str = ""  # Title of the source document

    # Timestamps
    accessed_at: str = ""  # When we accessed this source
    published_at: str = ""  # When the source was published (if known)

    # Content
    raw_snippet: str = ""  # Original text from source
    extracted_data: Dict = field(default_factory=dict)  # Structured data extracted

    # Verification
    confidence: float = 0.0  # 0.0 to 1.0
    verification_status: str = "unverified"  # unverified, cross_referenced, verified
    cross_references: List[str] = field(default_factory=list)  # Other evidence IDs that confirm this

    # Metadata
    search_query: str = ""  # What we searched for
    search_type: str = ""  # clinical, equipment, github, etc.
    cache_hit: bool = False  # Whether this came from cache

    def __post_init__(self):
        if not self.evidence_id:
            # Generate unique ID from content
            content = f"{self.claim}:{self.source_url}:{self.accessed_at}"
            self.evidence_id = hashlib.md5(
                content.encode(), usedforsecurity=False
            ).hexdigest()[:12]
        if not self.accessed_at:
            self.accessed_at = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        """Convert to dictionary for storage."""
        return asdict(self)

    def to_citation(self, style: str = "inline") -> str:
        """Generate citation string."""
        if style == "inline":
            source_info = self.source_title or self.source_type or "Web"
            return f"[{source_info}]({self.source_url})" if self.source_url else f"[{source_info}]"

        elif style == "ama":
            # American Medical Association style
            parts = []
            if self.source_title:
                parts.append(self.source_title)
            if self.source_url:
                parts.append(f"Available at: {self.source_url}")
            if self.accessed_at:
                parts.append(f"Accessed: {self.accessed_at[:10]}")
            return ". ".join(parts)

        elif style == "vancouver":
            # Vancouver style (common in medical journals)
            parts = []
            if self.source_title:
                parts.append(self.source_title)
            if self.source_url:
                parts.append(f"Available from: {self.source_url}")
            if self.accessed_at:
                parts.append(f"[cited {self.accessed_at[:10]}]")
            return ". ".join(parts)

        return self.source_url or self.source_title

    def get_permanent_url(self) -> str:
        """
        Get the most permanent URL available.

        Priority:
        1. DOI link (if available)
        2. PubMed permanent link
        3. GitHub permalink (specific commit)
        4. Original URL
        """
        # Check for DOI in source_url
        if "doi.org" in self.source_url:
            return self.source_url

        # PubMed permanent link
        if "pubmed.ncbi.nlm.nih.gov" in self.source_url:
            # Extract PMID and create permanent link
            import re
            pmid_match = re.search(r'/(\d+)/?', self.source_url)
            if pmid_match:
                return f"https://pubmed.ncbi.nlm.nih.gov/{pmid_match.group(1)}/"

        # GitHub permalink
        if "github.com" in self.source_url:
            # For code, try to get permalink to specific commit
            if "/blob/" in self.source_url or "/tree/" in self.source_url:
                return self.source_url  # Already specific

        return self.source_url


class EvidenceChain:
    """
    Manages a chain of evidence for a response.

    Tracks all sources used to formulate an answer, ensuring
    complete traceability and auditability.
    """

    def __init__(self, response_id: str = None):
        self.response_id = response_id or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.evidence: List[EvidenceRecord] = []
        self.created_at = datetime.now().isoformat()
        self.query: str = ""
        self.final_answer: str = ""

    def add_evidence(self, record: EvidenceRecord) -> str:
        """
        Add an evidence record to the chain.

        Returns: evidence_id
        """
        self.evidence.append(record)
        logger.info(f"Added evidence: {record.evidence_id} from {record.source_type}")
        return record.evidence_id

    def create_evidence_from_search(self, search_result: Dict, search_query: str,
                                     search_type: str, claim: str = "") -> EvidenceRecord:
        """
        Create an EvidenceRecord from a search result.

        Args:
            search_result: Dict with title, snippet, url, source, metadata
            search_query: The original search query
            search_type: Type of search performed
            claim: The specific claim/fact being cited
        """
        # Safely get snippet, handling None values
        snippet = search_result.get("snippet") or ""

        record = EvidenceRecord(
            claim=claim or snippet[:200],
            source_url=search_result.get("url") or "",
            source_type=search_result.get("source") or search_type,
            source_title=search_result.get("title") or "",
            raw_snippet=snippet,
            extracted_data=search_result.get("metadata") or {},
            search_query=search_query,
            search_type=search_type,
            confidence=self._calculate_confidence(search_result, search_type)
        )

        self.add_evidence(record)
        return record

    def _calculate_confidence(self, result: Dict, search_type: str) -> float:
        """
        Calculate confidence score for a search result.

        Higher confidence for:
        - PubMed peer-reviewed articles
        - Official guidelines (AAPM, ESTRO, NCCN)
        - Manufacturer official documentation
        - High-star GitHub repositories
        """
        base_confidence = 0.5

        source = result.get("source", "").lower()

        # PubMed is peer-reviewed
        if "pubmed" in source:
            base_confidence = 0.85

        # Official guidelines
        elif any(org in source.lower() for org in ["aapm", "estro", "nccn", "icru", "ncrp"]):
            base_confidence = 0.9

        # Manufacturer documentation
        elif any(mfr in source.lower() for mfr in ["varian", "elekta", "nucletron"]):
            base_confidence = 0.8

        # GitHub with many stars
        elif "github" in source:
            stars = result.get("metadata", {}).get("stars", 0)
            if stars > 100:
                base_confidence = 0.75
            elif stars > 10:
                base_confidence = 0.65
            else:
                base_confidence = 0.5

        # General web
        else:
            base_confidence = 0.4

        return base_confidence

    def cross_reference(self, evidence_id: str, other_evidence_id: str):
        """
        Mark two evidence records as cross-referencing each other.

        This increases confidence when multiple sources agree.
        """
        for record in self.evidence:
            if record.evidence_id == evidence_id:
                if other_evidence_id not in record.cross_references:
                    record.cross_references.append(other_evidence_id)
                    # Increase confidence based on cross-references
                    record.confidence = min(1.0, record.confidence + 0.1)
                    record.verification_status = "cross_referenced"

            if record.evidence_id == other_evidence_id:
                if evidence_id not in record.cross_references:
                    record.cross_references.append(evidence_id)
                    record.confidence = min(1.0, record.confidence + 0.1)
                    record.verification_status = "cross_referenced"

    def verify_consensus(self, min_sources: int = 2) -> bool:
        """
        Check if there's consensus among evidence sources.

        Returns True if multiple sources agree on the same claim.
        """
        if len(self.evidence) < min_sources:
            return False

        # Group evidence by similar claims
        claim_groups = {}
        for record in self.evidence:
            # Simple grouping by first 50 chars of claim
            key = record.claim[:50].lower()
            if key not in claim_groups:
                claim_groups[key] = []
            claim_groups[key].append(record)

        # Check if any group has enough sources
        for group in claim_groups.values():
            if len(group) >= min_sources:
                # Mark as verified
                for record in group:
                    record.verification_status = "verified"
                return True

        return False

    def get_citations(self, style: str = "inline") -> List[str]:
        """Get all citations in the specified format."""
        citations = []
        for record in self.evidence:
            if record.source_url:  # Only cite sources with URLs
                citations.append(record.to_citation(style))
        return citations

    def get_evidence_summary(self) -> Dict:
        """Get a summary of all evidence in the chain."""
        return {
            "response_id": self.response_id,
            "query": self.query,
            "created_at": self.created_at,
            "num_sources": len(self.evidence),
            "source_types": list(set(r.source_type for r in self.evidence)),
            "avg_confidence": sum(r.confidence for r in self.evidence) / max(len(self.evidence), 1),
            "verification_status": self._get_overall_verification(),
            "citations": self.get_citations("inline"),
            "evidence": [r.to_dict() for r in self.evidence]
        }

    def _get_overall_verification(self) -> str:
        """Get overall verification status."""
        if any(r.verification_status == "verified" for r in self.evidence):
            return "verified"
        elif any(r.verification_status == "cross_referenced" for r in self.evidence):
            return "cross_referenced"
        else:
            return "unverified"

    def save(self, filepath: str = None):
        """Save evidence chain to file for audit trail."""
        if filepath is None:
            filepath = os.path.join(EVIDENCE_DIR, f"evidence_{self.response_id}.json")

        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.get_evidence_summary(), f, indent=2, ensure_ascii=False)

        logger.info(f"Evidence chain saved to: {filepath}")
        return filepath

    @classmethod
    def load(cls, filepath: str) -> 'EvidenceChain':
        """Load evidence chain from file."""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        chain = cls(response_id=data.get("response_id"))
        chain.query = data.get("query", "")
        chain.created_at = data.get("created_at", "")

        for evidence_data in data.get("evidence", []):
            record = EvidenceRecord(**evidence_data)
            chain.evidence.append(record)

        return chain

    def format_for_response(self) -> str:
        """
        Format evidence chain for inclusion in a response.

        Returns a formatted string with citations that can be
        appended to the response text.
        """
        if not self.evidence:
            return ""

        citations = []
        for i, record in enumerate(self.evidence, 1):
            if record.source_url:
                source_name = record.source_title or record.source_type
                citations.append(f"[{i}] {source_name}: {record.get_permanent_url()}")

        if not citations:
            return ""

        return "\n\n**Sources:**\n" + "\n".join(citations)


class EvidenceTracker:
    """
    Global evidence tracker that manages evidence chains across a session.

    Provides methods to:
    - Create and manage evidence chains
    - Query evidence history
    - Export evidence for compliance/audit
    """

    def __init__(self, session_id: str = None):
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.chains: Dict[str, EvidenceChain] = {}
        self.current_chain: Optional[EvidenceChain] = None

    def start_new_chain(self, query: str = "") -> EvidenceChain:
        """Start a new evidence chain for a response."""
        chain = EvidenceChain()
        chain.query = query
        self.current_chain = chain
        self.chains[chain.response_id] = chain
        return chain

    def get_current_chain(self) -> Optional[EvidenceChain]:
        """Get the current evidence chain."""
        return self.current_chain

    def save_all(self):
        """Save all evidence chains to files."""
        for chain in self.chains.values():
            chain.save()

    def get_session_summary(self) -> Dict:
        """Get summary of all evidence in this session."""
        return {
            "session_id": self.session_id,
            "num_queries": len(self.chains),
            "total_sources": sum(len(c.evidence) for c in self.chains.values()),
            "chains": [c.get_evidence_summary() for c in self.chains.values()]
        }

    def export_for_audit(self, filepath: str = None) -> str:
        """Export all evidence for compliance/audit purposes."""
        if filepath is None:
            filepath = os.path.join(EVIDENCE_DIR, f"audit_{self.session_id}.json")

        summary = self.get_session_summary()

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        logger.info(f"Audit export saved to: {filepath}")
        return filepath


# Global tracker instance
_global_tracker: Optional[EvidenceTracker] = None


def get_evidence_tracker() -> EvidenceTracker:
    """Get or create the global evidence tracker."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = EvidenceTracker()
    return _global_tracker


def start_evidence_chain(query: str) -> EvidenceChain:
    """Convenience function to start a new evidence chain."""
    return get_evidence_tracker().start_new_chain(query)


def save_evidence_for_audit() -> str:
    """Convenience function to save all evidence for audit."""
    return get_evidence_tracker().export_for_audit()
