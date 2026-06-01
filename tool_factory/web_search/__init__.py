"""
Web Search Tool
===============
Provides internet search capability for BrachyBot to find information
that is not in its training data or local knowledge base.

Use cases:
- Recent clinical guidelines or publications
- Specific equipment specifications
- Institutional data not available locally
- Drug pricing or availability
- Historical details about specific procedures

Search strategy:
1. First try to answer from knowledge
2. If uncertain, search the web
3. If search doesn't find answer, honestly say "I don't know"
"""

import os
import json
import logging
import re
import time
from typing import Dict, Any, Optional, List
from urllib.parse import quote_plus

import requests

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Cache directory for search results
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Search cache TTL (24 hours)
CACHE_TTL = 86400


class WebSearchTool(BaseTool):
    """Search the internet for clinical and technical information."""

    name = "web_search"
    description = """Search the internet for information not available in local knowledge.
Use this when:
- User asks about specific equipment specifications (e.g., Varian, Elekta, Nucletron)
- User asks about recent clinical trials or publications
- User asks about drug pricing or availability
- User asks about institutional-specific data
- User asks about historical details you're not certain about
- You need to verify a fact you're unsure about

Do NOT use this when:
- Answering basic clinical questions you know well (dose constraints, protocols)
- The information is in the clinical_kb tool
- User is asking about system capabilities

Search sources:
- PubMed for clinical literature
- AAPM/ESTRO guidelines
- Manufacturer websites for equipment specs
- General medical information sites"""

    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query - be specific and include relevant keywords"
            },
            "search_type": {
                "type": "string",
                "description": "Type of search: clinical, equipment, general",
                "enum": ["clinical", "equipment", "general"],
                "default": "general"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (1-10)",
                "default": 5
            }
        },
        "required": ["query"]
    }

    output_schema = {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "results": {"type": "array", "items": {"type": "object"}},
            "answer": {"type": "string"},
            "sources": {"type": "array", "items": {"type": "string"}}
        }
    }

    def _get_cache_path(self, query: str) -> str:
        """Get cache file path for a query."""
        # Create safe filename from query
        safe_name = re.sub(r'[^\w\s-]', '', query.lower())
        safe_name = re.sub(r'[-\s]+', '_', safe_name)[:100]
        return os.path.join(CACHE_DIR, f"{safe_name}.json")

    def _get_cached_result(self, query: str) -> Optional[Dict]:
        """Get cached search result if available and not expired."""
        cache_path = self._get_cache_path(query)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                # Check if cache is still valid
                if time.time() - cached.get("timestamp", 0) < CACHE_TTL:
                    logger.info(f"Cache hit for query: {query[:50]}...")
                    return cached.get("result")
            except Exception as e:
                logger.warning(f"Cache read error: {e}")
        return None

    def _save_to_cache(self, query: str, result: Dict):
        """Save search result to cache."""
        cache_path = self._get_cache_path(query)
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "query": query,
                    "timestamp": time.time(),
                    "result": result
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Cache write error: {e}")

    def _search_duckduckgo(self, query: str, max_results: int = 5) -> List[Dict]:
        """
        Search using DuckDuckGo Instant Answer API.
        Falls back to HTML scraping if API doesn't return results.
        """
        results = []

        try:
            # Try DuckDuckGo Instant Answer API first
            api_url = "https://api.duckduckgo.com/"
            params = {
                "q": query,
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1
            }

            response = requests.get(api_url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()

                # Check for abstract
                if data.get("Abstract"):
                    results.append({
                        "title": data.get("Heading", "DuckDuckGo Result"),
                        "snippet": data["Abstract"],
                        "url": data.get("AbstractURL", ""),
                        "source": data.get("AbstractSource", "DuckDuckGo")
                    })

                # Check for related topics
                for topic in data.get("RelatedTopics", [])[:max_results]:
                    if isinstance(topic, dict) and topic.get("Text"):
                        results.append({
                            "title": topic.get("Text", "")[:100],
                            "snippet": topic.get("Text", ""),
                            "url": topic.get("FirstURL", ""),
                            "source": "DuckDuckGo"
                        })

        except Exception as e:
            logger.warning(f"DuckDuckGo API error: {e}")

        # If no results from API, try a simple web search
        if not results:
            try:
                # Use a simple search approach
                search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                response = requests.get(search_url, headers=headers, timeout=15)
                if response.status_code == 200:
                    # Simple extraction of results
                    text = response.text
                    # Look for result snippets
                    snippet_pattern = r'class="result__snippet">(.*?)</a>'
                    snippets = re.findall(snippet_pattern, text, re.DOTALL)

                    for i, snippet in enumerate(snippets[:max_results]):
                        # Clean HTML tags
                        clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                        if clean_snippet:
                            results.append({
                                "title": f"Search Result {i+1}",
                                "snippet": clean_snippet,
                                "url": "",
                                "source": "Web Search"
                            })

            except Exception as e:
                logger.warning(f"Web search fallback error: {e}")

        return results[:max_results]

    def _search_pubmed(self, query: str, max_results: int = 3) -> List[Dict]:
        """Search PubMed for clinical literature."""
        results = []

        try:
            # Use PubMed E-utilities
            search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            params = {
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
                "sort": "relevance"
            }

            response = requests.get(search_url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                ids = data.get("esearchresult", {}).get("idlist", [])

                if ids:
                    # Fetch article details
                    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
                    fetch_params = {
                        "db": "pubmed",
                        "id": ",".join(ids),
                        "retmode": "json"
                    }

                    fetch_response = requests.get(fetch_url, params=fetch_params, timeout=10)
                    if fetch_response.status_code == 200:
                        summaries = fetch_response.json().get("result", {})
                        for pmid in ids:
                            article = summaries.get(pmid, {})
                            if article:
                                results.append({
                                    "title": article.get("title", "Unknown"),
                                    "snippet": f"PubMed ID: {pmid}. {article.get('sortpubdate', '')}",
                                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                                    "source": "PubMed"
                                })

        except Exception as e:
            logger.warning(f"PubMed search error: {e}")

        return results

    def _format_results(self, results: List[Dict], query: str) -> Dict:
        """Format search results into a structured response."""
        if not results:
            return {
                "success": True,
                "results": [],
                "answer": f"I searched for '{query}' but couldn't find specific information. "
                          "This may be a question that requires specialized knowledge or "
                          "access to specific databases I don't have.",
                "sources": []
            }

        # Extract key information
        sources = []
        snippets = []

        for r in results:
            if r.get("url"):
                sources.append(r["url"])
            if r.get("snippet"):
                snippets.append(r["snippet"])

        # Create a summary answer
        if len(snippets) == 1:
            answer = f"Based on search results: {snippets[0]}"
        elif len(snippets) > 1:
            answer = "Based on search results:\n"
            for i, snippet in enumerate(snippets[:3], 1):
                answer += f"{i}. {snippet[:200]}\n"
        else:
            answer = "Search completed but no clear answer found."

        return {
            "success": True,
            "results": results,
            "answer": answer,
            "sources": sources
        }

    def _execute(self, **kwargs) -> ToolResult:
        """Execute web search."""
        query = kwargs.get("query", "")
        search_type = kwargs.get("search_type", "general")
        max_results = kwargs.get("max_results", 5)

        if not query:
            return ToolResult(
                success=False,
                message="No search query provided"
            )

        logger.info(f"Web search: {query} (type: {search_type})")

        # Check cache first
        cached = self._get_cached_result(query)
        if cached:
            return ToolResult(
                success=True,
                data=cached,
                message=f"Found {len(cached.get('results', []))} results (cached)"
            )

        # Perform search based on type
        results = []

        if search_type == "clinical":
            # For clinical queries, search PubMed first
            pubmed_results = self._search_pubmed(query, max_results=3)
            results.extend(pubmed_results)

            # Also search general web
            if len(results) < max_results:
                web_results = self._search_duckduckgo(
                    query, max_results=max_results - len(results)
                )
                results.extend(web_results)

        elif search_type == "equipment":
            # For equipment queries, search manufacturer sites
            enhanced_query = f"{query} specifications datasheet"
            results = self._search_duckduckgo(enhanced_query, max_results)

        else:
            # General search
            results = self._search_duckduckgo(query, max_results)

        # Format results
        formatted = self._format_results(results, query)

        # Cache results
        self._save_to_cache(query, formatted)

        return ToolResult(
            success=True,
            data=formatted,
            message=f"Found {len(results)} results for '{query}'"
        )


# Convenience function for direct use
def search_web(query: str, search_type: str = "general", max_results: int = 5) -> Dict:
    """Convenience function to search the web."""
    tool = WebSearchTool()
    result = tool.execute(query=query, search_type=search_type, max_results=max_results)
    return result.data if result.success else {"success": False, "error": result.error}
