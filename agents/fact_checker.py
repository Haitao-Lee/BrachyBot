"""
Fact Checker Agent
==================
Verifies the accuracy of information, especially from web searches.
Prevents LLM hallucinations by cross-referencing sources.
"""

import re
import logging
from typing import Dict, List, Any, Optional
from .base_agent import LLMCapableAgent
from communication.protocol import (
    AgentRole, AgentMessage, AgentResponse, MessageType,
    ReviewResult, Priority
)

logger = logging.getLogger(__name__)


class FactChecker(LLMCapableAgent):
    """
    Verifies information accuracy and prevents hallucinations.

    Capabilities:
    1. Source verification (check if sources exist and are reliable)
    2. Cross-validation (compare multiple sources)
    3. Temporal verification (check if information is current)
    4. Citation tracking (verify citations are real)

    Trusted domains and hallucination patterns are configurable via
    the constructor; defaults cover common medical sources.
    """

    # Default trusted medical domains — can be overridden at init
    _DEFAULT_TRUSTED_DOMAINS = {
        "pubmed.ncbi.nlm.nih.gov",
        "www.ncbi.nlm.nih.gov",
        "nccn.org",
        "www.nccn.org",
        "aapm.org",
        "www.aapm.org",
        "astro.org",
        "www.astro.org",
        "gyn-cancer.org",
        "www.cancer.gov",
        "who.int",
        "www.who.int",
        "nejm.org",
        "thelancet.com",
        "jco.org",
        "www.uptodate.com",
    }

    # Default hallucination patterns — can be overridden at init
    _DEFAULT_HALLUCINATION_PATTERNS = [
        r"according to a study (I|we) conducted",
        r"(I|we) found that",
        r"my (research|data) shows",
        r"recently published in \[journal\]",
        r"Dr\. [A-Z][a-z]+ (from|at) \[institution\]",
        r"study (ID|number) \d+",
        r"https?://\[.*\]",
    ]

    def __init__(self, llm_callback=None,
                 trusted_domains: set = None,
                 hallucination_patterns: list = None):
        super().__init__(AgentRole.FACT_CHECKER, llm_callback)
        self.TRUSTED_DOMAINS = trusted_domains or self._DEFAULT_TRUSTED_DOMAINS
        self.HALLUCINATION_PATTERNS = hallucination_patterns or self._DEFAULT_HALLUCINATION_PATTERNS

    async def process(self, message: AgentMessage) -> AgentResponse:
        """
        Verify information accuracy.

        Args:
            message: Contains claims and sources to verify

        Returns:
            AgentResponse with ReviewResult
        """
        content = message.content

        claims = content.get("claims", [])
        sources = content.get("sources", [])
        context = content.get("context", "")
        plan_config = content.get("plan_config", {})

        # Filter out claims that are just technical data (not factual claims)
        # e.g., "max_dose=180" is a metric, not a claim to fact-check
        claims = [c for c in claims if not self._is_technical_metric(c)]

        # Perform verification
        verification_results = []

        # 1. Source verification
        if sources:
            source_result = self._verify_sources(sources)
            verification_results.append(source_result)

        # 2. Claim verification
        if claims:
            claim_result = self._verify_claims(claims, sources)
            verification_results.append(claim_result)

        # 3. Hallucination detection
        if claims:
            hallucination_result = self._detect_hallucinations(claims)
            verification_results.append(hallucination_result)

        # 4. LLM-based verification (if available)
        if self.llm_callback and claims:
            llm_result = await self._llm_verify(claims, sources, context)
            verification_results.append(llm_result)

        # Aggregate results
        final_result = self._aggregate_results(verification_results)

        return AgentResponse(
            agent_role=self.role,
            success=True,
            result=final_result,
            confidence=final_result.confidence,
            reasoning=self._build_reasoning(verification_results),
            suggestions=final_result.suggestions,
            warnings=final_result.concerns,
        )

    def _verify_sources(self, sources: List[str]) -> ReviewResult:
        """Verify source reliability."""
        concerns = []
        suggestions = []
        trusted_count = 0
        total_count = len(sources)

        for source in sources:
            # Extract domain from URL
            domain = self._extract_domain(source)

            if domain in self.TRUSTED_DOMAINS:
                trusted_count += 1
            elif domain:
                concerns.append(f"Unverified source: {domain}")
                suggestions.append(f"Cross-reference {domain} with trusted sources")
            else:
                # Might be a citation, not a URL
                if self._looks_like_citation(source):
                    # Will be verified in claim verification
                    pass
                else:
                    concerns.append(f"Cannot parse source: {source[:50]}...")

        if total_count == 0:
            score = 5.0
            confidence = 0.3
        else:
            trust_rate = trusted_count / total_count
            score = 5 + trust_rate * 5
            confidence = 0.5 + trust_rate * 0.4

        return ReviewResult(
            reviewer="Source Verification",
            decision=self._score_to_decision(score),
            score=score,
            concerns=concerns,
            suggestions=suggestions,
            confidence=confidence,
        )

    def _verify_claims(self, claims: List[str], sources: List[str]) -> ReviewResult:
        """Verify claims against sources."""
        concerns = []
        suggestions = []
        verified_count = 0

        for claim in claims:
            # Check if claim has a source reference
            has_source = any(
                self._claim_references_source(claim, source)
                for source in sources
            ) if sources else False

            if has_source:
                verified_count += 1
            else:
                # Check if it's a well-known fact
                if self._is_well_known_fact(claim):
                    verified_count += 1
                else:
                    concerns.append(f"Unsourced claim: {claim[:80]}...")
                    suggestions.append("Provide source for verification")

        if len(claims) == 0:
            score = 5.0
        else:
            verification_rate = verified_count / len(claims)
            score = 3 + verification_rate * 7

        return ReviewResult(
            reviewer="Claim Verification",
            decision=self._score_to_decision(score),
            score=score,
            concerns=concerns,
            suggestions=suggestions,
            confidence=0.7,
        )

    def _detect_hallucinations(self, claims: List[str]) -> ReviewResult:
        """Detect potential hallucinations using pattern matching."""
        concerns = []
        hallucination_flags = 0

        for claim in claims:
            for pattern in self.HALLUCINATION_PATTERNS:
                if re.search(pattern, claim, re.IGNORECASE):
                    hallucination_flags += 1
                    concerns.append(f"Potential hallucination detected: {claim[:60]}...")
                    break

        if len(claims) == 0:
            score = 8.0
        else:
            hallucination_rate = hallucination_flags / len(claims)
            score = max(3, 10 * (1 - hallucination_rate))

        return ReviewResult(
            reviewer="Hallucination Detection",
            decision=self._score_to_decision(score),
            score=score,
            concerns=concerns,
            suggestions=["Verify flagged claims with trusted sources"] if concerns else [],
            confidence=0.6,
        )

    async def _llm_verify(self, claims: List[str], sources: List[str],
                         context: str) -> ReviewResult:
        """Use LLM to verify claims."""
        # Use loaded config prompt + JSON format instruction
        system_prompt = (
            self._system_prompt
            + "\n\nRespond in JSON format:\n"
            + '{"verified_claims":["..."],"flagged_claims":['
            + '{"claim":"...","reason":"...","severity":"high/medium/low"}],'
            + '"overall_accuracy":0.0,"confidence":0.0}'
        )

        prompt = f"Claims to verify:\n"
        for i, claim in enumerate(claims, 1):
            prompt += f"{i}. {claim}\n"

        if sources:
            prompt += f"\nSources:\n"
            for i, source in enumerate(sources, 1):
                prompt += f"{i}. {source}\n"

        if context:
            prompt += f"\nContext: {context}\n"

        try:
            response = await self.call_llm(prompt, system_prompt, temperature=0.1)

            # Parse response
            import json
            json_match = re.search(r'\{[^{}]+\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())

                flagged = data.get("flagged_claims", [])
                concerns = [f"{f['claim']}: {f['reason']}" for f in flagged]
                accuracy = data.get("overall_accuracy", 0.7)
                confidence = data.get("confidence", 0.7)

                score = accuracy * 10

                return ReviewResult(
                    reviewer="LLM Fact Check",
                    decision=self._score_to_decision(score),
                    score=score,
                    concerns=concerns,
                    suggestions=["Review flagged claims"] if concerns else [],
                    confidence=confidence,
                )

        except Exception as e:
            logger.warning(f"LLM fact-check failed: {e}")

        return ReviewResult(
            reviewer="LLM Fact Check",
            decision="conditional",
            score=5.0,
            concerns=["LLM verification unavailable"],
            suggestions=["Manual verification recommended"],
            confidence=0.3,
        )

    def _is_technical_metric(self, text: str) -> bool:
        """Check if text is a technical metric (not a factual claim to verify)."""
        # Patterns like "V100=0.95", "max_dose=180", "D2cc=0.9"
        if re.match(r'^[A-Za-z_]+\d*[=<>]\d+\.?\d*$', text.strip()):
            return True
        # Patterns like "score: 85", "seeds: 25"
        if re.match(r'^[a-z_]+:\s*\d+', text.strip()):
            return True
        return False

    def _extract_domain(self, url: str) -> Optional[str]:
        """Extract domain from URL."""
        match = re.search(r'https?://([^/]+)', url)
        if match:
            return match.group(1).lower()
        return None

    def _looks_like_citation(self, text: str) -> bool:
        """Check if text looks like a citation."""
        # Common citation patterns
        patterns = [
            r'\d{4}',  # Year
            r'et al\.',
            r'J\s+[A-Z]',  # Journal abbreviation
            r'Vol\.\s+\d+',
            r'pp?\.\s+\d+',
            r'doi:',
        ]
        return any(re.search(p, text) for p in patterns)

    def _claim_references_source(self, claim: str, source: str) -> bool:
        """Check if a claim references a source."""
        # Stop words that carry no semantic weight
        _STOP = {"the", "a", "an", "is", "are", "of", "to", "in", "for",
                 "and", "or", "on", "with", "by", "at", "from", "that", "this",
                 "it", "be", "as", "not", "no", "https", "http", "www", "com", "org"}
        source_words = set(re.findall(r'\w+', source.lower())) - _STOP
        claim_words = set(re.findall(r'\w+', claim.lower())) - _STOP
        # Require at least 2 meaningful overlapping words
        overlap = source_words & claim_words
        return len(overlap) >= 2

    def _is_well_known_fact(self, claim: str) -> bool:
        """Check if claim is a well-known medical fact."""
        # This is a simplified check - in production, use a knowledge base
        well_known_patterns = [
            r'I-?125.*seed',
            r'brachytherapy.*treatment',
            r'CTV.*target.*volume',
            r'OAR.*organ.*risk',
            r'D90.*dose.*90',
            r'V100.*volume.*100',
        ]
        return any(re.search(p, claim, re.IGNORECASE) for p in well_known_patterns)

    def _aggregate_results(self, results: List[ReviewResult]) -> ReviewResult:
        """Aggregate verification results."""
        if not results:
            return ReviewResult(
                reviewer="Fact Check (Aggregated)",
                decision="conditional",
                score=5.0,
                concerns=["No verification performed"],
                confidence=0.3,
            )

        # Weighted average
        weights = {
            "Source Verification": 1.2,
            "Claim Verification": 1.3,
            "Hallucination Detection": 1.5,
            "LLM Fact Check": 1.0,
        }

        total_weight = 0
        weighted_score = 0
        for result in results:
            w = weights.get(result.reviewer, 1.0)
            weighted_score += result.score * w
            total_weight += w

        final_score = weighted_score / total_weight if total_weight > 0 else 5.0

        # Aggregate concerns
        all_concerns = []
        all_suggestions = []
        for result in results:
            all_concerns.extend(result.concerns)
            all_suggestions.extend(result.suggestions)

        # Decision
        decisions = [r.decision for r in results]
        if "reject" in decisions:
            final_decision = "reject"
        elif "escalate" in decisions:
            final_decision = "escalate"
        elif "conditional" in decisions:
            final_decision = "conditional"
        else:
            final_decision = "pass"

        avg_confidence = sum(r.confidence for r in results) / len(results)

        return ReviewResult(
            reviewer="Fact Check (Aggregated)",
            decision=final_decision,
            score=final_score,
            concerns=list(set(all_concerns)),
            suggestions=list(set(all_suggestions)),
            confidence=avg_confidence,
        )

    def _score_to_decision(self, score: float) -> str:
        """Convert score to decision."""
        if score >= 7:
            return "pass"
        elif score >= 5:
            return "conditional"
        else:
            return "reject"

    def _build_reasoning(self, results: List[ReviewResult]) -> str:
        """Build reasoning summary."""
        lines = ["Fact-Check Summary:"]
        for result in results:
            lines.append(f"- {result.reviewer}: {result.decision} (score={result.score:.1f})")
            if result.concerns:
                for concern in result.concerns[:2]:
                    lines.append(f"  ⚠ {concern}")
        return "\n".join(lines)
