"""
Web Search Tool with Evidence Chain
====================================
Provides internet search capability for BrachyBot with full evidence traceability.

CRITICAL: Every piece of information from the internet MUST have:
1. Source URL (permanent link when possible)
2. Access timestamp
3. Source type and confidence level
4. Evidence chain for audit trail

Use cases:
- Recent clinical guidelines or publications
- Specific equipment specifications
- Institutional data not available locally
- Drug pricing or availability
- Historical details about specific procedures
- Code and repository search (GitHub)

Search strategy:
1. First try to answer from knowledge
2. If uncertain, search the web
3. ALWAYS cite sources when using web-sourced information
4. If search doesn't find answer, honestly say "I don't know"

Evidence chain ensures:
- Complete traceability of all sourced information
- Audit trail for compliance
- Cross-referencing for verification
- Confidence scoring for reliability assessment
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
from tool_factory.web_search.evidence_chain import (
    EvidenceChain, EvidenceRecord, EvidenceTracker,
    get_evidence_tracker, start_evidence_chain
)

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
- General medical information sites
- GitHub for code, repositories, and documentation

GitHub Integration:
- Search repositories, code, and issues
- Clone repositories for local analysis
- Search within cloned repositories
- Useful for finding implementation examples, tools, and libraries"""

    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query - be specific and include relevant keywords"
            },
            "search_type": {
                "type": "string",
                "description": "Type of search: clinical, equipment, general, github_repos, github_code, github_issues",
                "enum": ["clinical", "equipment", "general", "github_repos", "github_code", "github_issues"],
                "default": "general"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (1-10)",
                "default": 5
            },
            "clone_repo": {
                "type": "string",
                "description": "GitHub URL to clone (e.g., https://github.com/user/repo)"
            },
            "search_local_repo": {
                "type": "string",
                "description": "Path to local repository to search within"
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
        Falls back to Wikipedia API if DuckDuckGo fails.
        Uses shorter timeouts for faster failure.
        """
        results = []

        # Try DuckDuckGo API first
        try:
            api_url = "https://api.duckduckgo.com/"
            params = {
                "q": query,
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1
            }

            response = requests.get(api_url, params=params, timeout=5)  # 5秒超时
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
                response = requests.get(search_url, headers=headers, timeout=8)  # 8秒超时
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

        # If still no results, try Wikipedia API (very reliable, fast)
        if not results:
            try:
                wiki_url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + quote_plus(query)
                response = requests.get(wiki_url, timeout=3)  # 3秒超时
                if response.status_code == 200:
                    data = response.json()
                    if data.get("extract"):
                        results.append({
                            "title": data.get("title", query),
                            "snippet": data["extract"][:500],
                            "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                            "source": "Wikipedia"
                        })
            except Exception as e:
                logger.warning(f"Wikipedia API error: {e}")

        return results[:max_results]

    def _search_bing(self, query: str, max_results: int = 5) -> List[Dict]:
        """
        Search using Bing.
        Uses official API if BING_SEARCH_API_KEY is set, otherwise uses a simple approach.
        """
        results = []
        api_key = os.environ.get("BING_SEARCH_API_KEY")

        if api_key:
            # Use official Bing API
            try:
                endpoint = "https://api.bing.microsoft.com/v7.0/search"
                headers = {"Ocp-Apim-Subscription-Key": api_key}
                params = {
                    "q": query,
                    "count": max_results,
                    "mkt": "en-US"
                }
                response = requests.get(endpoint, headers=headers, params=params, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    for item in data.get("webPages", {}).get("value", [])[:max_results]:
                        results.append({
                            "title": item.get("name", ""),
                            "snippet": item.get("snippet", ""),
                            "url": item.get("url", ""),
                            "source": "Bing"
                        })
            except Exception as e:
                logger.warning(f"Bing API error: {e}")
        else:
            # No API key - return empty to let other methods handle it
            logger.info("No BING_SEARCH_API_KEY set, skipping Bing search")

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

            response = requests.get(search_url, params=params, timeout=5)  # 5秒超时
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

                    fetch_response = requests.get(fetch_url, params=fetch_params, timeout=5)  # 5秒超时
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

    def _search_github(self, query: str, max_results: int = 5, search_type: str = "repositories") -> List[Dict]:
        """
        Search GitHub for code, repositories, and documentation.

        Args:
            query: Search query
            max_results: Maximum results to return
            search_type: 'repositories', 'code', or 'issues'
        """
        results = []

        try:
            # GitHub Search API (no auth required for basic search)
            api_url = "https://api.github.com/search"

            if search_type == "repositories":
                url = f"{api_url}/repositories"
                params = {
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": max_results
                }
            elif search_type == "code":
                url = f"{api_url}/code"
                params = {
                    "q": query,
                    "per_page": max_results
                }
            else:  # issues
                url = f"{api_url}/issues"
                params = {
                    "q": query,
                    "sort": "relevance",
                    "per_page": max_results
                }

            headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "BrachyBot-Agent"
            }

            # Check for GitHub token in environment
            github_token = os.environ.get("GITHUB_TOKEN")
            if github_token:
                headers["Authorization"] = f"token {github_token}"

            response = requests.get(url, params=params, headers=headers, timeout=15)

            if response.status_code == 200:
                data = response.json()
                items = data.get("items", [])

                for item in items[:max_results]:
                    if search_type == "repositories":
                        results.append({
                            "title": item.get("full_name", ""),
                            "snippet": item.get("description", "No description"),
                            "url": item.get("html_url", ""),
                            "source": "GitHub",
                            "metadata": {
                                "stars": item.get("stargazers_count", 0),
                                "language": item.get("language", ""),
                                "forks": item.get("forks_count", 0),
                                "updated": item.get("updated_at", "")
                            }
                        })
                    elif search_type == "code":
                        repo = item.get("repository", {})
                        results.append({
                            "title": f"{repo.get('full_name', '')}/{item.get('name', '')}",
                            "snippet": item.get("path", ""),
                            "url": item.get("html_url", ""),
                            "source": "GitHub Code"
                        })
                    else:  # issues
                        results.append({
                            "title": item.get("title", ""),
                            "snippet": f"#{item.get('number', '')} in {item.get('repository', {}).get('full_name', '')}",
                            "url": item.get("html_url", ""),
                            "source": "GitHub Issue"
                        })
            else:
                logger.warning(f"GitHub API returned status {response.status_code}")

        except Exception as e:
            logger.warning(f"GitHub search error: {e}")

        return results

    def _clone_github_repo(self, repo_url: str, target_dir: str = None) -> Dict:
        """
        Clone a GitHub repository.

        Args:
            repo_url: GitHub repository URL (e.g., https://github.com/user/repo)
            target_dir: Target directory (optional, defaults to /tmp/brachybot_repos/)

        Returns:
            Dict with success status, path, and message
        """
        import subprocess

        if target_dir is None:
            target_dir = os.path.join("/tmp", "brachybot_repos")

        os.makedirs(target_dir, exist_ok=True)

        # Extract repo name from URL
        repo_name = repo_url.split("/")[-1].replace(".git", "")
        clone_path = os.path.join(target_dir, repo_name)

        # Check if already cloned
        if os.path.exists(clone_path):
            # Pull latest changes
            try:
                subprocess.run(
                    ["git", "-C", clone_path, "pull"],
                    capture_output=True, text=True, timeout=60
                )
                return {
                    "success": True,
                    "path": clone_path,
                    "message": f"Repository updated: {clone_path}"
                }
            except Exception as e:
                logger.warning(f"Git pull failed: {e}")

        # Clone the repository
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, clone_path],
                capture_output=True, text=True, timeout=120
            )

            if result.returncode == 0:
                return {
                    "success": True,
                    "path": clone_path,
                    "message": f"Repository cloned to: {clone_path}"
                }
            else:
                return {
                    "success": False,
                    "error": result.stderr,
                    "message": f"Failed to clone repository: {result.stderr}"
                }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Timeout",
                "message": "Clone operation timed out (120s limit)"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Clone failed: {str(e)}"
            }

    def _search_local_repo(self, repo_path: str, query: str, max_results: int = 5) -> List[Dict]:
        """
        Search within a cloned repository for code and documentation.

        Args:
            repo_path: Path to the cloned repository
            query: Search query (keywords)
            max_results: Maximum results to return
        """
        results = []

        if not os.path.exists(repo_path):
            return results

        try:
            # Search in Python files
            for root, dirs, files in os.walk(repo_path):
                # Skip hidden directories and common non-essential dirs
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'node_modules', '.git']]

                for file in files:
                    if file.endswith(('.py', '.md', '.txt', '.json', '.yaml', '.yml')):
                        file_path = os.path.join(root, file)
                        try:
                            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()

                            # Simple keyword matching
                            query_lower = query.lower()
                            content_lower = content.lower()

                            if query_lower in content_lower:
                                # Find the matching context
                                idx = content_lower.find(query_lower)
                                start = max(0, idx - 100)
                                end = min(len(content), idx + len(query) + 100)
                                snippet = content[start:end].strip()

                                # Get relative path
                                rel_path = os.path.relpath(file_path, repo_path)

                                results.append({
                                    "title": f"{rel_path}",
                                    "snippet": snippet[:200],
                                    "url": f"file://{file_path}",
                                    "source": "Local Repository"
                                })

                                if len(results) >= max_results:
                                    return results

                        except Exception:
                            continue

        except Exception as e:
            logger.warning(f"Local repo search error: {e}")

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
        """Execute web search with evidence tracking."""
        query = kwargs.get("query", "")
        search_type = kwargs.get("search_type", "general")
        max_results = kwargs.get("max_results", 5)
        clone_repo = kwargs.get("clone_repo", "")
        search_local_repo = kwargs.get("search_local_repo", "")
        claim = kwargs.get("claim", "")  # Specific claim being verified

        # Start evidence chain for this search
        evidence_chain = start_evidence_chain(query)

        # Handle GitHub clone request
        if clone_repo:
            logger.info(f"Cloning GitHub repository: {clone_repo}")
            clone_result = self._clone_github_repo(clone_repo)

            # Track evidence for clone
            if clone_result["success"]:
                evidence_chain.create_evidence_from_search(
                    {
                        "title": f"Repository: {clone_repo}",
                        "snippet": clone_result["message"],
                        "url": clone_repo,
                        "source": "GitHub Repository"
                    },
                    search_query=query,
                    search_type="github_clone",
                    claim=f"Repository cloned: {clone_repo}"
                )

            return ToolResult(
                success=clone_result["success"],
                data={
                    **clone_result,
                    "evidence_chain_id": evidence_chain.response_id,
                    "evidence_summary": evidence_chain.get_evidence_summary()
                },
                message=clone_result["message"]
            )

        # Handle local repo search
        if search_local_repo:
            logger.info(f"Searching local repository: {search_local_repo}")
            results = self._search_local_repo(search_local_repo, query, max_results)
            formatted = self._format_results(results, query)

            # Track evidence for local search
            for result in results:
                evidence_chain.create_evidence_from_search(
                    result,
                    search_query=query,
                    search_type="local_repo",
                    claim=result.get("snippet", "")[:200]
                )

            formatted["evidence_chain_id"] = evidence_chain.response_id
            formatted["evidence_summary"] = evidence_chain.get_evidence_summary()

            return ToolResult(
                success=True,
                data=formatted,
                message=f"Found {len(results)} results in local repository"
            )

        if not query:
            return ToolResult(
                success=False,
                message="No search query provided"
            )

        logger.info(f"Web search: {query} (type: {search_type})")

        # Check cache first (don't cache GitHub searches)
        if not search_type.startswith("github"):
            cached = self._get_cached_result(query)
            if cached:
                # Still track evidence from cache
                for result in cached.get("results", []):
                    evidence_chain.create_evidence_from_search(
                        result,
                        search_query=query,
                        search_type=search_type,
                        claim=claim or result.get("snippet", "")[:200]
                    )

                cached["evidence_chain_id"] = evidence_chain.response_id
                cached["evidence_summary"] = evidence_chain.get_evidence_summary()

                return ToolResult(
                    success=True,
                    data=cached,
                    message=f"Found {len(cached.get('results', []))} results (cached)"
                )

        # Perform search based on type
        # Priority: PubMed (medical) > GitHub (code) > Bing > DuckDuckGo > Wikipedia
        results = []

        if search_type == "clinical":
            # For clinical queries, search PubMed first (most reliable for medical content)
            pubmed_results = self._search_pubmed(query, max_results=max_results)
            results.extend(pubmed_results)

        elif search_type == "equipment":
            # For equipment queries, try Bing first, then DuckDuckGo
            enhanced_query = f"{query} specifications datasheet"
            results = self._search_bing(enhanced_query, max_results)
            if not results:
                results = self._search_duckduckgo(enhanced_query, max_results)

        elif search_type == "github_repos":
            # Search GitHub repositories
            results = self._search_github(query, max_results, search_type="repositories")

        elif search_type == "github_code":
            # Search GitHub code
            results = self._search_github(query, max_results, search_type="code")

        elif search_type == "github_issues":
            # Search GitHub issues
            results = self._search_github(query, max_results, search_type="issues")

        else:
            # General search: Try PubMed first (medical context), then Bing, then DuckDuckGo
            # PubMed is most reliable from this network
            pubmed_results = self._search_pubmed(query, max_results=2)
            results.extend(pubmed_results)

            if len(results) < max_results:
                bing_results = self._search_bing(query, max_results=max_results - len(results))
                results.extend(bing_results)

            if len(results) < max_results:
                ddg_results = self._search_duckduckgo(query, max_results=max_results - len(results))
                results.extend(ddg_results)

        # Track evidence for all results
        for result in results:
            evidence_chain.create_evidence_from_search(
                result,
                search_query=query,
                search_type=search_type,
                claim=claim or result.get("snippet", "")[:200]
            )

        # Check for cross-references if multiple results
        if len(results) >= 2:
            evidence_chain.verify_consensus(min_sources=2)

        # Format results
        formatted = self._format_results(results, query)

        # Add evidence chain information
        formatted["evidence_chain_id"] = evidence_chain.response_id
        formatted["evidence_summary"] = evidence_chain.get_evidence_summary()
        formatted["citations"] = evidence_chain.get_citations("inline")

        # Cache results (don't cache GitHub searches)
        if not search_type.startswith("github"):
            self._save_to_cache(query, formatted)

        # Save evidence chain for audit trail
        evidence_chain.save()

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
