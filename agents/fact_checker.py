"""
Fact Checker Agent
==================
Dual-layer source reliability checker with GLOBAL CONTEXT AWARENESS.

Layer 1 (deterministic): domain whitelist + hallucination regex. Cannot be wrong.
Layer 2 (LLM, optional): verify claims WITH full clinical context (user question,
                         cancer type, planning state) and medical safety rules.

The LLM layer is optional — if it fails, only deterministic results are used.

SUB-AGENT GLOBAL VIEW: This agent reads the full context passed by the orchestrator
(including user_message, conversation_state, patient_info) to make informed judgments.
A bystander with full information gives better advice than one with partial information.
"""

import json
import re
import logging
import os
from typing import Dict, List, Any, Optional
from .base_agent import LLMCapableAgent
from communication.protocol import (
    AgentRole, AgentMessage, AgentResponse, MessageType,
    ReviewResult, Priority
)

logger = logging.getLogger(__name__)

# Load system-level medical prompts once at module level for domain expertise
def _load_medical_prompts():
    """Load medical safety + clinical KB prompts."""
    prompts_dir = os.path.join(os.path.dirname(__file__), '..', 'config', 'prompts')
    parts = []
    for fname in ['medical_safety.md', 'clinical_kb.md']:
        fpath = os.path.join(prompts_dir, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    parts.append(f.read())
            except Exception as e:
                logger.debug(f"Failed to load {fname}: {e}")
    return "\n\n---\n\n".join(parts) if parts else ""

_MEDICAL_SYSTEM_PROMPT = _load_medical_prompts()


class FactChecker(LLMCapableAgent):
    """
    Dual-layer source reliability checker.

    Layer 1 (deterministic):
    - Domain whitelist: PubMed, NCCN, AAPM, etc.
    - Hallucination regex: fabricated PMIDs, placeholder URLs
    - These results are ALWAYS included, cannot be overridden

    Layer 2 (LLM, optional):
    - "Does this claim appear to be supported by these sources?"
    - Very conservative: only flags obvious mismatches
    - If LLM fails, only Layer 1 results are returned
    """

    TRUSTED_DOMAINS = {
        "pubmed.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov",
        "nccn.org", "www.nccn.org",
        "aapm.org", "www.aapm.org",
        "astro.org", "www.astro.org",
        "www.cancer.gov", "who.int", "www.who.int",
        "nejm.org", "thelancet.com", "jco.org",
        "www.uptodate.com", "cochranelibrary.com",
        "clinicaltrials.gov", "europepmc.org",
        "semanticscholar.org", "crossref.org",
        "radiopaedia.org", "icru.org",
    }

    HALLUCINATION_PATTERNS = [
        (r'according to a study (I|we) conducted', 'Fabricated personal study'),
        (r'(I|we) found that', 'Fabricated personal finding'),
        (r'my (research|data) shows', 'Fabricated personal research'),
        (r'recently published in \[journal\]', 'Placeholder journal name'),
        (r'Dr\. [A-Z][a-z]+ (from|at) \[institution\]', 'Placeholder institution'),
        (r'study (ID|number) \d{5,}', 'Suspiciously specific study ID'),
        (r'https?://\[.*\]', 'Placeholder URL'),
        (r'PMID:\s*\d{8,}', 'Suspiciously long PMID'),
    ]

    # LLM prompt for claim verification
    _CLAIM_PROMPT = """You are a medical fact-checker. Given claims from a search result and the sources cited, check if the claims are SUPPORTED by the sources.

## Claims
{claims}

## Sources
{sources}

## Rules
- Only flag claims that are CLEARLY unsupported or contradicted by the sources
- Do NOT flag claims that are plausible medical knowledge even if not directly cited
- Do NOT flag standard clinical terms (V100, D90, D2cc) as suspicious
- Be CONSERVATIVE: when in doubt, mark as "supported"
- Focus on: fabricated statistics, made-up study references, impossible claims

## Output Format (JSON)
{{
    "verified_claims": ["claim1 that is supported"],
    "flagged_claims": [
        {{"claim": "...", "reason": "why it's suspicious", "severity": "high|medium|low"}}
    ],
    "overall_confidence": 0.0-1.0
}}"""

    def __init__(self, llm_callback=None, **kwargs):
        super().__init__(AgentRole.FACT_CHECKER, llm_callback)

    async def process(self, message: AgentMessage) -> AgentResponse:
        content = message.content
        claims = content.get("claims", [])
        sources = content.get("sources", [])

        # ── GLOBAL CONTEXT: read full situational awareness ──────────
        # As a bystander/observer, we need full information to give good advice.
        # The orchestrator passes these via _build_agent_context().
        self._user_message = content.get("user_message", "")
        self._conversation_state = content.get("conversation_state", {})
        self._patient_info = content.get("patient_info", {})
        self._segmentation = content.get("segmentation", {})
        self._planning = content.get("planning", {})
        self._distilled_context = content.get("distilled_context", "")

        # Filter out technical metrics
        claims = [c for c in claims if not self._is_technical_metric(c)]

        # ── Layer 1: Deterministic checks ──────────────────────────
        det_results = self._deterministic_checks(claims, sources)

        # ── Layer 2: LLM claim verification with FULL CONTEXT ───────
        llm_results = await self._llm_verify_claims(claims, sources, content)

        # ── Merge ──────────────────────────────────────────────────
        merged = self._merge_results(det_results, llm_results)

        return AgentResponse(
            agent_role=self.role,
            success=True,
            result=merged,
            confidence=merged.confidence,
            reasoning=self._build_reasoning(det_results, llm_results),
            suggestions=merged.suggestions,
            warnings=merged.concerns,
        )

    def _deterministic_checks(self, claims: list, sources: list) -> dict:
        """Layer 1: Domain whitelist + hallucination regex."""
        concerns = []
        trusted_count = 0
        unknown_domains = []

        for source in sources:
            domain = self._extract_domain(source)
            if domain in self.TRUSTED_DOMAINS:
                trusted_count += 1
            elif domain:
                unknown_domains.append(domain)

        if unknown_domains:
            concerns.append(f"Unverified sources: {', '.join(unknown_domains[:3])}")

        # Hallucination pattern detection
        hallucination_flags = []
        for claim in claims:
            for pattern, desc in self.HALLUCINATION_PATTERNS:
                if re.search(pattern, claim, re.IGNORECASE):
                    hallucination_flags.append({"claim": claim[:60], "reason": desc})
                    break

        return {
            "trusted_count": trusted_count,
            "unknown_domains": unknown_domains,
            "hallucination_flags": hallucination_flags,
            "concerns": concerns,
        }

    async def _llm_verify_claims(self, claims: list, sources: list,
                                   full_context: dict = None) -> Optional[dict]:
        """Layer 2: LLM claim verification with FULL GLOBAL CONTEXT.

        As a bystander/observer, this agent uses all available information
        to make informed judgments about claim accuracy and relevance.
        """
        if not self.llm_callback or not claims:
            return None

        claims_text = "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims[:7]))
        sources_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sources[:5])) or "No sources provided"

        # ── Build global context section ──────────────────────────────
        ctx = full_context or {}
        context_sections = []

        # User's original question (critical for relevance check)
        user_q = ctx.get("user_message", "") or getattr(self, '_user_message', '')
        if user_q:
            context_sections.append(f"## User's Original Question\n{user_q}")

        # Distilled context from orchestrator (if available)
        distilled = ctx.get("distilled_context", "") or getattr(self, '_distilled_context', '')
        if distilled:
            context_sections.append(f"## Distilled Context\n{distilled}")

        # Conversation state (what's been done so far)
        conv_state = ctx.get("conversation_state", {}) or getattr(self, '_conversation_state', {})
        if conv_state:
            state_items = []
            if conv_state.get('ctv_segmented'):
                state_items.append("CTV segmented ✓")
            if conv_state.get('oar_segmented'):
                state_items.append("OAR segmented ✓")
            if conv_state.get('planning_completed'):
                state_items.append("Planning completed ✓")
            if state_items:
                context_sections.append(f"## Current State\n{', '.join(state_items)}")

        # Patient/planning info (cancer type, organ)
        patient = ctx.get("patient_info", {}) or getattr(self, '_patient_info', {})
        planning = ctx.get("planning", {}) or getattr(self, '_planning', {})
        clinical_info = []
        if patient.get('cancer_type'):
            clinical_info.append(f"Cancer type: {patient['cancer_type']}")
        if patient.get('organ'):
            clinical_info.append(f"Organ: {patient['organ']}")
        if planning.get('mode'):
            clinical_info.append(f"Planning mode: {planning['mode']}")
        if clinical_info:
            context_sections.append(f"## Clinical Context\n" + "\n".join(clinical_info))

        context_block = "\n\n".join(context_sections) if context_sections else ""

        # ── Build the full prompt with medical domain expertise ───────
        base_prompt = self._CLAIM_PROMPT.format(claims=claims_text, sources=sources_text)

        # Add medical safety rules as domain expertise
        medical_block = ""
        if _MEDICAL_SYSTEM_PROMPT:
            medical_block = f"\n\n## Medical Domain Rules (for reference)\n{_MEDICAL_SYSTEM_PROMPT[:2000]}"

        prompt = base_prompt
        if context_block:
            prompt += f"\n\n{context_block}"
        if medical_block:
            prompt += medical_block

        try:
            response = await self.call_llm(prompt, temperature=0.1)
            json_match = re.search(r'\{[^{}]+\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.debug(f"LLM fact-check failed (using deterministic only): {e}")

        return None

    def _merge_results(self, det_results: dict, llm_results: Optional[dict]) -> ReviewResult:
        """Merge deterministic facts with LLM judgment."""
        concerns = list(det_results["concerns"])
        suggestions = []

        # Add hallucination flags from deterministic check
        for flag in det_results["hallucination_flags"]:
            concerns.append(f"{flag['reason']}: {flag['claim']}")

        # Add LLM-flagged claims if available
        if llm_results:
            for flag in llm_results.get("flagged_claims", []):
                claim = flag.get("claim", "")[:60]
                reason = flag.get("reason", "suspicious")
                # Don't duplicate deterministic flags
                if not any(claim[:30] in c for c in concerns):
                    concerns.append(f"LLM flagged: {claim} — {reason}")

        # Suggestions
        if det_results["unknown_domains"]:
            suggestions.append("Cross-reference with trusted medical sources")
        if det_results["hallucination_flags"]:
            suggestions.append("Verify flagged claims against PubMed/NCCN")

        # Score. Deterministic hallucination patterns are stronger evidence
        # than an unknown source domain, so a single fabricated-study pattern
        # must not be reported as a clean pass.
        unknown_penalty = len(det_results["unknown_domains"]) * 1.0
        hallucination_penalty = len(det_results["hallucination_flags"]) * 2.5
        llm_penalty = len(llm_results.get("flagged_claims", [])) * 1.5 if llm_results else 0.0
        score = max(4.0, 10.0 - unknown_penalty - hallucination_penalty - llm_penalty)

        # Decision: FactChecker is advisory — format_as_source_summary() only
        # reads concerns, and the quality gate runs in APPEND-ONLY mode (never
        # blocks). So decision carries no runtime effect. We still set it
        # semantically for logging/inspection.
        if det_results["hallucination_flags"]:
            decision = "conditional" if score >= 5.0 else "reject"
        elif score >= 8.0:
            decision = "pass"
        elif score >= 6.0:
            decision = "conditional"
        else:
            decision = "reject"

        return ReviewResult(
            reviewer="Source Reliability",
            decision=decision,
            score=score,
            concerns=concerns[:5],
            suggestions=suggestions[:3],
            confidence=0.85 if not llm_results else 0.9,
        )

    def _is_technical_metric(self, text: str) -> bool:
        if re.match(r'^[A-Za-z_]+\d*[=<>]\d+\.?\d*$', text.strip()):
            return True
        if re.match(r'^[a-z_]+:\s*\d+', text.strip()):
            return True
        return False

    def _extract_domain(self, url: str) -> Optional[str]:
        match = re.search(r'https?://([^/]+)', url)
        return match.group(1).lower() if match else None

    def _build_reasoning(self, det_results: dict, llm_results: Optional[dict]) -> str:
        lines = [f"Trusted sources: {det_results['trusted_count']}"]
        lines.append(f"Unknown domains: {len(det_results['unknown_domains'])}")
        lines.append(f"Hallucination flags: {len(det_results['hallucination_flags'])}")
        if llm_results:
            lines.append(f"LLM flagged: {len(llm_results.get('flagged_claims', []))}")
        return "\n".join(lines)

    def format_as_source_summary(self, result: ReviewResult, lang: str = "en") -> str:
        """Format as source reliability note. Empty if no issues."""
        if not result or not result.concerns:
            return ""

        if lang == "zh":
            lines = ["📌 **来源提示**"]
            for concern in result.concerns[:3]:
                lines.append(f"- {concern}")
        else:
            lines = ["📌 **Source Notes**"]
            for concern in result.concerns[:3]:
                lines.append(f"- {concern}")

        return "\n".join(lines)
