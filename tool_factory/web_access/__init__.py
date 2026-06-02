"""
Unified Web Access System for BrachyBot
========================================

A comprehensive, robust, and fast web access system that combines:
- PubMed API for medical literature (most reliable)
- GitHub API for technical content
- Bing CN for general search
- Direct URL fetching with multiple fallback strategies

Design principles:
1. Evidence-based: All results include source tracking
2. Anti-hallucination: Only present verified information
3. Fast: Use caching and parallel requests
4. Robust: Multiple fallback strategies
5. Transparent: Always show sources

Inspired by:
- Agent-Reach: Multi-platform access, zero API fees
- web-access: CDP browser, site experience
- bb-browser: Real browser integration
- Higress ai-search: Query optimization
"""

import os
import re
import json
import time
import logging
import hashlib
import requests
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse, quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed

from tool_factory import BaseTool, ToolResult
from utils.retry import retry_with_backoff, SEARCH_RETRY_CONFIG

logger = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Evidence directory
EVIDENCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evidence")
os.makedirs(EVIDENCE_DIR, exist_ok=True)

# Cache TTL (1 hour for search, 24 hours for fetches)
SEARCH_CACHE_TTL = 3600
FETCH_CACHE_TTL = 86400


@dataclass
class SearchResult:
    """A single search result with full traceability."""
    title: str
    snippet: str
    url: str
    source: str  # pubmed, github, bing, etc.
    confidence: float = 0.0
    accessed_at: str = ""

    def __post_init__(self):
        if not self.accessed_at:
            self.accessed_at = time.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class EvidenceRecord:
    """Evidence chain record for traceability."""
    query: str
    results: List[SearchResult]
    sources: List[str]
    timestamp: str
    search_type: str
    success: bool
    error: Optional[str] = None


class UnifiedWebAccess:
    """
    Unified web access system with multiple search engines and fallback strategies.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    # =========================================================================
    # Search Methods
    # =========================================================================

    def search_pubmed(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """
        Search PubMed for medical literature with retry logic.
        Most reliable source for clinical queries.
        """
        results = []

        def _do_search():
            # Search for IDs
            search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            params = {
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
                "sort": "relevance"
            }

            response = self.session.get(search_url, params=params, timeout=5)
            if response.status_code != 200:
                return []

            data = response.json()
            return data.get("esearchresult", {}).get("idlist", [])

        try:
            ids = retry_with_backoff(_do_search, config=SEARCH_RETRY_CONFIG)
        except Exception as e:
            logger.warning(f"PubMed search failed after retries: {e}")
            return results

        if not ids:
            return results

            if not ids:
                return results

            # Fetch summaries
            summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
            summary_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
            summary_resp = self.session.get(summary_url, params=summary_params, timeout=5)

            if summary_resp.status_code != 200:
                return results

            summaries = summary_resp.json().get("result", {})

            # Fetch abstracts
            abstract_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            abstract_params = {"db": "pubmed", "id": ",".join(ids), "rettype": "abstract", "retmode": "text"}
            abstract_resp = self.session.get(abstract_url, params=abstract_params, timeout=5)

            abstracts = {}
            if abstract_resp.status_code == 200:
                # Parse abstracts
                text = abstract_resp.text
                for pmid in ids:
                    # Find abstract using patterns
                    for pattern in [r'BACKGROUND:', r'PURPOSE:', r'RESULTS:', r'Here we present', r'This study']:
                        match = re.search(pattern, text, re.IGNORECASE)
                        if match:
                            start = match.start()
                            end = text.find('©', start)
                            if end == -1:
                                end = text.find('DOI:', start)
                            if end == -1:
                                end = len(text)
                            abstract = text[start:end].strip()
                            abstracts[pmid] = abstract[:500]
                            break

            # Build results
            for pmid in ids:
                article = summaries.get(pmid, {})
                if article:
                    title = article.get("title", "Unknown")
                    abstract = abstracts.get(pmid, "")
                    snippet = f"PubMed ID: {pmid}. {article.get('sortpubdate', '')}"
                    if abstract:
                        snippet += f". {abstract}"

                    results.append(SearchResult(
                        title=title,
                        snippet=snippet[:500],
                        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        source="PubMed",
                        confidence=0.85
                    ))

        except Exception as e:
            logger.warning(f"PubMed search error: {e}")

        return results

    def search_github(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """
        Search GitHub for repositories and code with retry logic.
        Best for technical and AI/ML topics.
        """
        results = []

        def _do_search():
            url = "https://api.github.com/search/repositories"
            params = {"q": query, "sort": "stars", "order": "desc", "per_page": max_results}
            headers = {"Accept": "application/vnd.github.v3+json"}

            response = self.session.get(url, params=params, headers=headers, timeout=5)
            if response.status_code != 200:
                return []

            data = response.json()
            items = []
            for item in data.get("items", [])[:max_results]:
                items.append(SearchResult(
                    title=item.get("full_name", ""),
                    snippet=item.get("description", "")[:300],
                    url=item.get("html_url", ""),
                    source="GitHub",
                    confidence=0.75,
                    metadata={"stars": item.get("stargazers_count", 0)}
                ))
            return items

        try:
            results = retry_with_backoff(_do_search, config=SEARCH_RETRY_CONFIG)
        except Exception as e:
            logger.warning(f"GitHub search failed after retries: {e}")

        return results

    def search_bing_cn(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """
        Search Bing CN for general web content.
        Fallback for non-medical, non-technical queries.
        """
        results = []
        try:
            url = f"https://cn.bing.com/search?q={quote_plus(query)}"
            response = self.session.get(url, timeout=5)

            if response.status_code != 200:
                return results

            # Parse HTML results
            text = response.text
            # Extract result blocks
            pattern = r'<li class="b_algo">(.*?)</li>'
            blocks = re.findall(pattern, text, re.DOTALL)

            for block in blocks[:max_results]:
                # Extract title and URL
                title_match = re.search(r'<h2><a[^>]*href="([^"]*)"[^>]*>(.*?)</a></h2>', block)
                if title_match:
                    url = title_match.group(1)
                    title = re.sub(r'<[^>]+>', '', title_match.group(2)).strip()

                    # Extract snippet
                    snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
                    snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip() if snippet_match else ""

                    if title:
                        results.append(SearchResult(
                            title=title[:200],
                            snippet=snippet[:300],
                            url=url,
                            source="Bing CN",
                            confidence=0.6
                        ))

        except Exception as e:
            logger.warning(f"Bing CN search error: {e}")

        return results

    # =========================================================================
    # Fetch Methods
    # =========================================================================

    def fetch_url(self, url: str, max_length: int = 5000) -> Dict:
        """
        Fetch a URL with multiple fallback strategies.
        Returns dict with title, content, source.
        """
        parsed = urlparse(url)
        hostname = parsed.hostname or ""

        # Strategy 1: Direct fetch
        result = self._fetch_direct(url, max_length)
        if result.get("success"):
            return result

        # Strategy 2: PubMed API for PubMed URLs
        if "pubmed.ncbi.nlm.nih.gov" in hostname:
            result = self._fetch_pubmed_api(url, max_length)
            if result.get("success"):
                return result

        # Strategy 3: GitHub API for GitHub URLs
        if "github.com" in hostname:
            result = self._fetch_github_api(url, max_length)
            if result.get("success"):
                return result

        # All strategies failed
        return {"success": False, "error": "All fetch strategies failed"}

    def _fetch_direct(self, url: str, max_length: int) -> Dict:
        """Direct HTTP fetch."""
        try:
            response = self.session.get(url, timeout=10, allow_redirects=True)
            if response.status_code != 200:
                return {"success": False, "error": f"HTTP {response.status_code}"}

            content_type = response.headers.get('content-type', '')

            if 'application/json' in content_type:
                text = response.text[:max_length]
                title = "JSON Response"
            else:
                html = response.text
                title = self._extract_title(html) or "Web Page"
                text = self._html_to_text(html)[:max_length]

            return {
                "success": True,
                "url": url,
                "title": title,
                "content": text,
                "source": "direct"
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _fetch_pubmed_api(self, url: str, max_length: int) -> Dict:
        """Fetch PubMed article via API."""
        match = re.search(r'/(\d+)/?$', url)
        if not match:
            return {"success": False, "error": "Cannot extract PMID"}

        pmid = match.group(1)
        try:
            api_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&rettype=abstract&retmode=text"
            response = self.session.get(api_url, timeout=10)

            if response.status_code == 200:
                text = response.text[:max_length]
                title_match = re.search(r'\d+\.\s+(.+?)\.', text)
                title = title_match.group(1) if title_match else f"PubMed {pmid}"

                return {
                    "success": True,
                    "url": url,
                    "title": title,
                    "content": text,
                    "source": "PubMed API"
                }

            return {"success": False, "error": "PubMed API failed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _fetch_github_api(self, url: str, max_length: int) -> Dict:
        """Fetch GitHub content via API."""
        match = re.search(r'github\.com/([^/]+)/([^/]+)', url)
        if not match:
            return {"success": False, "error": "Cannot parse GitHub URL"}

        owner, repo = match.group(1), match.group(2)
        try:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
            headers = {'Accept': 'application/vnd.github.v3.raw'}
            response = self.session.get(api_url, headers=headers, timeout=10)

            if response.status_code == 200:
                return {
                    "success": True,
                    "url": url,
                    "title": f"{owner}/{repo} README",
                    "content": response.text[:max_length],
                    "source": "GitHub API"
                }

            return {"success": False, "error": "GitHub API failed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Unified Search
    # =========================================================================

    def search(self, query: str, search_type: str = "general", max_results: int = 5) -> Dict:
        """
        Unified search with automatic source selection.

        Search types:
        - clinical: PubMed only (most reliable for medical)
        - general: PubMed + GitHub + Bing CN
        - technical: GitHub + PubMed
        - github: GitHub only
        """
        start_time = time.time()
        results = []
        evidence = []

        # Add year context for recent information (inspired by OpenCode)
        query = self._add_year_context(query)

        # Optimize query for PubMed
        pubmed_query = self._optimize_for_pubmed(query)

        if search_type == "clinical":
            # Clinical: PubMed only
            results = self.search_pubmed(pubmed_query, max_results)

        elif search_type == "github":
            # GitHub only
            results = self.search_github(query, max_results)

        elif search_type == "technical":
            # Technical: GitHub first, then PubMed
            github_results = self.search_github(query, max_results // 2)
            pubmed_results = self.search_pubmed(pubmed_query, max_results // 2)
            results = github_results + pubmed_results

        else:
            # General: PubMed + GitHub + Bing CN
            # Run searches in parallel for speed
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {
                    executor.submit(self.search_pubmed, pubmed_query, 3): "PubMed",
                    executor.submit(self.search_github, query, 2): "GitHub",
                }

                # Add Bing CN if query might benefit from it
                if not self._is_medical_query(query):
                    futures[executor.submit(self.search_bing_cn, query, 2)] = "Bing CN"

                for future in as_completed(futures, timeout=10):
                    source = futures[future]
                    try:
                        source_results = future.result()
                        results.extend(source_results)
                    except Exception as e:
                        logger.warning(f"{source} search failed: {e}")

        # Build evidence chain
        elapsed = time.time() - start_time
        evidence_record = EvidenceRecord(
            query=query,
            results=results,
            sources=[r.url for r in results if r.url],
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            search_type=search_type,
            success=len(results) > 0
        )

        # Format response
        return self._format_response(results, evidence_record, elapsed)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _optimize_for_pubmed(self, query: str) -> str:
        """Optimize query for PubMed search."""
        # Remove noise words
        noise = {'ai', 'system', 'tool', 'platform', 'model', 'software',
                 'what', 'is', 'the', 'a', 'an', 'are', 'do', 'does',
                 'can', 'you', 'tell', 'me', 'about'}

        words = query.split()
        filtered = [w for w in words if w.lower() not in noise][:3]
        return ' '.join(filtered) if filtered else query

    def _add_year_context(self, query: str) -> str:
        """
        Add current year to query for recent information.
        Inspired by OpenCode's year awareness feature.
        """
        # Check if query seems to ask for recent/current info
        recent_indicators = ['latest', 'recent', 'current', 'new', '2024', '2025', '2026',
                           '最新', '最近', '当前', '新']
        if any(indicator in query.lower() for indicator in recent_indicators):
            current_year = time.strftime("%Y")
            if current_year not in query:
                return f"{query} {current_year}"
        return query

    def _is_medical_query(self, query: str) -> bool:
        """Check if query is medical/clinical."""
        medical_terms = ['dose', 'cancer', 'tumor', 'treatment', 'therapy',
                        'patient', 'clinical', 'medical', 'brachytherapy',
                        'radiation', 'oncology', 'prostate', 'cervical']
        query_lower = query.lower()
        return any(term in query_lower for term in medical_terms)

    def _format_response(self, results: List[SearchResult], evidence: EvidenceRecord, elapsed: float) -> Dict:
        """Format search results into structured response."""
        if not results:
            return {
                "success": True,
                "results": [],
                "answer": f"I searched for '{evidence.query}' but couldn't find specific information.",
                "sources": [],
                "evidence": asdict(evidence),
                "elapsed": round(elapsed, 2)
            }

        # Group by source
        pubmed_results = [r for r in results if r.source == "PubMed"]
        github_results = [r for r in results if r.source == "GitHub"]
        other_results = [r for r in results if r.source not in ["PubMed", "GitHub"]]

        # Build answer
        answer_parts = []

        if pubmed_results:
            answer_parts.append("Medical literature (PubMed):")
            for r in pubmed_results[:3]:
                answer_parts.append(f"- {r.title}: {r.snippet[:150]}")

        if github_results:
            answer_parts.append("\nTechnical resources (GitHub):")
            for r in github_results[:3]:
                answer_parts.append(f"- {r.title}: {r.snippet[:150]}")

        if other_results:
            answer_parts.append("\nOther sources:")
            for r in other_results[:2]:
                answer_parts.append(f"- {r.title}: {r.snippet[:150]}")

        answer = "\n".join(answer_parts)
        sources = [r.url for r in results if r.url]

        return {
            "success": True,
            "results": [asdict(r) for r in results],
            "answer": answer,
            "sources": sources,
            "evidence": asdict(evidence),
            "elapsed": round(elapsed, 2)
        }

    def _html_to_text(self, html: str) -> str:
        """Convert HTML to clean text with markdown-like formatting."""
        # Remove scripts and styles
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)

        # Convert headers to markdown-style
        for i in range(1, 7):
            html = re.sub(rf'<h{i}[^>]*>(.*?)</h{i}>', rf'\n\n{"#" * i} \1\n', html, flags=re.DOTALL | re.IGNORECASE)

        # Convert lists
        html = re.sub(r'<li[^>]*>(.*?)</li>', r'\n- \1', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<ol[^>]*>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'<ul[^>]*>', '\n', html, flags=re.IGNORECASE)

        # Convert links
        html = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r'\2 (\1)', html, flags=re.DOTALL | re.IGNORECASE)

        # Convert paragraphs and breaks
        html = re.sub(r'<p[^>]*>', '\n\n', html, flags=re.IGNORECASE)
        html = re.sub(r'<br[^>]*>', '\n', html, flags=re.IGNORECASE)

        # Remove remaining tags
        html = re.sub(r'<[^>]+>', '', html)

        # Decode entities
        html = html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        html = html.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')

        # Clean whitespace
        html = re.sub(r'\n\s*\n', '\n\n', html)
        html = re.sub(r'[ \t]+', ' ', html)

        return html.strip()

    def _extract_title(self, html: str) -> str:
        """Extract title from HTML."""
        match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if match:
            return re.sub(r'<[^>]+>', '', match.group(1)).strip()
        return ""


# ============================================================================
# Tool Interface
# ============================================================================

class WebAccessTool(BaseTool):
    """Unified web access tool for BrachyBot."""

    name = "web_access"
    description = """Search the internet and fetch web pages with full evidence tracking.

Use this for:
- Medical literature searches (PubMed)
- Technical/code searches (GitHub)
- General web searches
- Fetching specific URLs

The tool automatically selects the best search source and maintains
an evidence chain for all results."""

    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action: 'search' or 'fetch'",
                "enum": ["search", "fetch"]
            },
            "query": {
                "type": "string",
                "description": "Search query (for search action)"
            },
            "url": {
                "type": "string",
                "description": "URL to fetch (for fetch action)"
            },
            "search_type": {
                "type": "string",
                "description": "Search type: general, clinical, technical, github",
                "enum": ["general", "clinical", "technical", "github"],
                "default": "general"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum results (1-10)",
                "default": 5
            }
        },
        "required": ["action"]
    }

    def __init__(self):
        self.web_access = UnifiedWebAccess()

    def _execute(self, **kwargs) -> ToolResult:
        """Execute web access operation."""
        action = kwargs.get("action", "search")

        if action == "search":
            query = kwargs.get("query", "")
            if not query:
                return ToolResult(success=False, message="No query provided")

            search_type = kwargs.get("search_type", "general")
            max_results = kwargs.get("max_results", 5)

            result = self.web_access.search(query, search_type, max_results)

            return ToolResult(
                success=result["success"],
                data=result,
                message=result.get("answer", "Search completed")[:200]
            )

        elif action == "fetch":
            url = kwargs.get("url", "")
            if not url:
                return ToolResult(success=False, message="No URL provided")

            result = self.web_access.fetch_url(url)

            return ToolResult(
                success=result.get("success", False),
                data=result,
                message=f"Fetched: {result.get('title', 'Unknown')}" if result.get("success") else result.get("error", "Fetch failed")
            )

        else:
            return ToolResult(success=False, message=f"Unknown action: {action}")
