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

# Search cache TTL (2 hours for freshness, was 24h causing stale weather results)
CACHE_TTL = 7200


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
        Uses official API if BING_SEARCH_API_KEY is set, otherwise tries cn.bing.com.
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
            # Try cn.bing.com (accessible from China)
            try:
                search_url = f"https://cn.bing.com/search?q={quote_plus(query)}"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                response = requests.get(search_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    text = response.text
                    # Extract results from cn.bing.com
                    # Note: b_algo li tags have extra attributes like data-id, so use flexible pattern
                    result_pattern = r'<li\s+class="b_algo"[^>]*>(.*?)</li>'
                    result_blocks = re.findall(result_pattern, text, re.DOTALL)
                    logger.info(f"Bing CN: found {len(result_blocks)} result blocks")

                    for block in result_blocks[:max_results]:
                        # Extract URL from <a> tag inside <h2>
                        url_match = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>', block, re.DOTALL)
                        if not url_match:
                            url_match = re.search(r'<a[^>]*href="([^"]*)"[^>]*>[^<]*<strong>', block, re.DOTALL)
                        url = url_match.group(1) if url_match else ""

                        # Extract title text (strip HTML tags including <strong>)
                        title_match = re.search(r'<h2[^>]*>(.*?)</h2>', block, re.DOTALL)
                        if title_match:
                            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
                        else:
                            title = ""

                        # Extract snippet from <p> or <div class="b_caption">
                        snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
                        if not snippet_match:
                            snippet_match = re.search(r'<div[^>]*class="b_caption"[^>]*>(.*?)</div>', block, re.DOTALL)
                        snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip() if snippet_match else ""
                        # Clean up HTML entities
                        snippet = snippet.replace('&ensp;', ' ').replace('&#0183;', '·').replace('&nbsp;', ' ')

                        if title and url:
                            results.append({
                                "title": title[:200],
                                "snippet": snippet[:300] if snippet else "",
                                "url": url,
                                "source": "Bing CN"
                            })
                    logger.info(f"Bing CN: extracted {len(results)} results")
            except Exception as e:
                logger.warning(f"Bing CN error: {e}")

        return results[:max_results]

    def _search_baidu(self, query: str, max_results: int = 5) -> List[Dict]:
        """
        Search using Baidu (百度).
        Accessible from China without API key.
        """
        results = []

        try:
            search_url = f"https://www.baidu.com/s?wd={quote_plus(query)}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(search_url, headers=headers, timeout=5)
            if response.status_code == 200:
                text = response.text
                # Extract results from Baidu
                # Baidu uses <div class="result"> for each result
                result_pattern = r'<div class="result[^"]*"[^>]*>(.*?)</div>\s*</div>'
                result_blocks = re.findall(result_pattern, text, re.DOTALL)

                for block in result_blocks[:max_results]:
                    # Extract title
                    title_match = re.search(r'<h3[^>]*><a[^>]*>(.*?)</a></h3>', block, re.DOTALL)
                    if title_match:
                        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()

                        # Extract URL
                        url_match = re.search(r'<h3[^>]*><a[^>]*href="([^"]*)"', block)
                        url = url_match.group(1) if url_match else ""

                        # Extract snippet
                        snippet_match = re.search(r'<span class="content-right_[^"]*">(.*?)</span>', block, re.DOTALL)
                        if not snippet_match:
                            snippet_match = re.search(r'<div class="c-abstract">(.*?)</div>', block, re.DOTALL)
                        snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip() if snippet_match else ""

                        if title:
                            results.append({
                                "title": title[:200],
                                "snippet": snippet[:300] if snippet else "",
                                "url": url,
                                "source": "Baidu"
                            })
        except Exception as e:
            logger.warning(f"Baidu search error: {e}")

        return results[:max_results]

    def _search_pubmed(self, query: str, max_results: int = 3) -> List[Dict]:
        """Search PubMed for clinical literature with abstracts."""
        results = []

        try:
            # Use PubMed E-utilities to search
            search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            params = {
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
                "sort": "relevance"
            }

            response = requests.get(search_url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                ids = data.get("esearchresult", {}).get("idlist", [])

                if ids:
                    # Fetch article details including abstract
                    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
                    fetch_params = {
                        "db": "pubmed",
                        "id": ",".join(ids),
                        "retmode": "json"
                    }

                    fetch_response = requests.get(fetch_url, params=fetch_params, timeout=5)
                    if fetch_response.status_code == 200:
                        summaries = fetch_response.json().get("result", {})

                        # Also fetch abstracts using efetch
                        efetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
                        efetch_params = {
                            "db": "pubmed",
                            "id": ",".join(ids),
                            "rettype": "abstract",
                            "retmode": "text"
                        }
                        abstract_response = requests.get(efetch_url, params=efetch_params, timeout=5)
                        abstracts = {}
                        if abstract_response.status_code == 200:
                            # Parse abstracts from plain text response
                            abstract_text = abstract_response.text
                            # Look for abstract content using common patterns
                            # Abstracts typically start with background/purpose statements
                            abstract_patterns = [
                                r'Rare diseases affect',
                                r'BACKGROUND:',
                                r'PURPOSE:',
                                r'OBJECTIVE:',
                                r'METHODS:',
                                r'RESULTS:',
                                r'CONCLUSIONS:',
                                r'Here we present',
                                r'We present',
                                r'This study',
                            ]

                            for pmid in ids:
                                for pattern in abstract_patterns:
                                    match = re.search(pattern, abstract_text, re.IGNORECASE)
                                    if match:
                                        # Get text from this match to the copyright/DOI
                                        start = match.start()
                                        end = abstract_text.find('©', start)
                                        if end == -1:
                                            end = abstract_text.find('DOI:', start)
                                        if end == -1:
                                            end = len(abstract_text)
                                        abstract = abstract_text[start:end].strip()
                                        # Clean up citation numbers
                                        abstract = re.sub(r'\d+[-–]\d+', '', abstract)
                                        abstract = re.sub(r'\d+,\d+', '', abstract)
                                        abstracts[pmid] = abstract[:500]
                                        break

                        for pmid in ids:
                            article = summaries.get(pmid, {})
                            if article:
                                title = article.get("title", "Unknown")
                                abstract = abstracts.get(pmid, "")
                                snippet = f"PubMed ID: {pmid}. {article.get('sortpubdate', '')}"
                                if abstract:
                                    snippet += f". {abstract}"

                                results.append({
                                    "title": title,
                                    "snippet": snippet[:500],
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

    def _simplify_query(self, query: str) -> str:
        """
        Simplify search query for better results.
        Only remove obvious noise - let LLM handle complex translation.
        """
        # Remove only the most basic noise
        noise_patterns = [
            r'^(你知道|告诉我|介绍一下|什么是|是什么)\s*',
            r'\s*(吗|呢|啊|吧|呀)\??$',
        ]

        simplified = query
        for pattern in noise_patterns:
            simplified = re.sub(pattern, '', simplified, flags=re.IGNORECASE)

        return simplified.strip() if simplified.strip() else query

    def _optimize_search_query(self, query: str, search_type: str = "general") -> str:
        """
        Optimize search query for different search engines.
        Inspired by Higress ai-search plugin.
        """
        # Simplify the query first
        simplified = self._simplify_query(query)

        # For PubMed, add medical context if not present
        if search_type == "clinical":
            medical_terms = ['brachytherapy', 'radiation', 'dose', 'treatment', 'cancer']
            if not any(term in simplified.lower() for term in medical_terms):
                simplified += " brachytherapy"

        # For general search, try to make it more search-friendly
        # Convert questions to keywords
        question_words = ['what', 'who', 'when', 'where', 'why', 'how', 'which']
        words = simplified.split()
        filtered_words = [w for w in words if w.lower() not in question_words]
        if filtered_words:
            simplified = ' '.join(filtered_words)

        return simplified

    def _simplify_for_pubmed(self, query: str) -> str:
        """
        Simplify query specifically for PubMed search.
        Keep only the most distinctive terms for better PubMed results.
        """
        # Very basic stop words for PubMed
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
                      'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                      'should', 'may', 'might', 'can', 'shall', 'to', 'of', 'in', 'for',
                      'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during',
                      'before', 'after', 'above', 'below', 'between', 'out', 'off', 'over',
                      'under', 'again', 'further', 'then', 'once'}

        # Extra words to remove for PubMed (these make queries too specific)
        extra_noise = {'ai', 'system', 'tool', 'platform', 'model', 'software',
                       'technology', 'method', 'approach', 'technique',
                       'medical', 'clinical', 'health', 'healthcare',
                       'meta', 'google', 'microsoft', 'openai', 'deepmind'}

        words = query.split()
        # Keep only non-stop, non-noise words (max 2)
        main_keywords = [w for w in words if w.lower() not in stop_words and w.lower() not in extra_noise][:2]

        return ' '.join(main_keywords) if main_keywords else query

    def _contains_chinese(self, text: str) -> bool:
        """Check if text contains Chinese characters."""
        import re
        return bool(re.search(r'[一-鿿]', text))

    def _extract_search_query(self, user_message: str, llm_response: str = None) -> str:
        """
        Extract the actual search query from user message or LLM response.
        This helps when the LLM translates the query before searching.
        """
        # If LLM provided a translated query, use it
        if llm_response:
            # Look for patterns like "search for '...'" or "query: ..."
            import re
            patterns = [
                r"search for ['\"](.+?)['\"]",
                r"query: ['\"](.+?)['\"]",
                r"search_query: ['\"](.+?)['\"]",
            ]
            for pattern in patterns:
                match = re.search(pattern, llm_response, re.IGNORECASE)
                if match:
                    return match.group(1)

        # Otherwise, extract keywords from user message
        # Remove common question patterns
        cleaned = user_message
        for prefix in ['你知道', '告诉我', '介绍一下', '什么是', '是什么']:
            cleaned = cleaned.replace(prefix, '')

        return cleaned.strip()

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
        pubmed_results = []
        github_results = []
        other_results = []

        for r in results:
            if r.get("url"):
                sources.append(r["url"])
            if r.get("snippet"):
                if r.get("source") == "PubMed":
                    pubmed_results.append(r)
                elif r.get("source") in ["GitHub", "GitHub Repository"]:
                    github_results.append(r)
                else:
                    other_results.append(r)

        # Create a comprehensive answer
        answer_parts = []

        # Add PubMed results
        if pubmed_results:
            answer_parts.append("PubMed results:")
            for i, r in enumerate(pubmed_results[:3], 1):
                answer_parts.append(f"{i}. {r['snippet'][:200]}")

        # Add GitHub results (important for technical topics)
        if github_results:
            answer_parts.append("\nGitHub repositories:")
            for r in github_results[:3]:
                title = r.get("title", "")
                snippet = r.get("snippet", "")[:100]
                answer_parts.append(f"- {title}: {snippet}")

        # Add other results
        if other_results:
            answer_parts.append("\nOther sources:")
            for r in other_results[:2]:
                answer_parts.append(f"- {r['snippet'][:150]}")

        answer = "\n".join(answer_parts) if answer_parts else "Search completed but no clear answer found."

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
                    claim=(result.get("snippet") or "")[:200]
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
                        claim=claim or (result.get("snippet") or "")[:200]
                    )

                cached["evidence_chain_id"] = evidence_chain.response_id
                cached["evidence_summary"] = evidence_chain.get_evidence_summary()

                return ToolResult(
                    success=True,
                    data=cached,
                    message=f"Found {len(cached.get('results', []))} results (cached)"
                )

        # Perform search based on type
        # Priority: PubMed (medical) > GitHub (code) > Bing CN > Baidu > DuckDuckGo
        results = []

        if search_type == "clinical":
            # For clinical queries, search PubMed only (most reliable)
            pubmed_results = self._search_pubmed(query, max_results=max_results)
            results.extend(pubmed_results)
            # Skip other sources for clinical queries

        elif search_type == "equipment":
            # For equipment queries, try Bing CN first, then Baidu
            enhanced_query = f"{query} specifications datasheet"
            results = self._search_bing(enhanced_query, max_results)
            if not results:
                results = self._search_baidu(enhanced_query, max_results)
            # Skip DuckDuckGo - it always times out

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
            # General search: determine if query is clinical or technical
            optimized_query = self._optimize_search_query(query, search_type)
            logger.info(f"Optimized query: '{query}' -> '{optimized_query}'")

            # Detect if query is about clinical/medical topics or technical/AI topics
            clinical_keywords = ['brachytherapy', 'radiation', 'dose', 'treatment', 'cancer',
                                 'tumor', 'therapy', 'clinical', 'patient', 'organ', 'prostate',
                                 'pancreas', 'liver', 'lung', 'cervix', 'implant', 'seed']
            tech_keywords = ['ai', 'model', 'tool', 'software', 'framework', 'library', 'github',
                             'sam', 'segment', 'anything', 'deep', 'learning', 'neural', 'network',
                             'algorithm', 'paper', 'code', 'repository', 'api', 'dataset']
            is_clinical = any(kw in query.lower() for kw in clinical_keywords)
            is_tech = any(kw in query.lower() for kw in tech_keywords)

            if is_clinical and not is_tech:
                # Clinical query: PubMed first
                pubmed_query = self._simplify_for_pubmed(optimized_query)
                logger.info(f"Clinical query, PubMed query: '{pubmed_query}'")
                pubmed_results = self._search_pubmed(pubmed_query, max_results=max_results)
                results.extend(pubmed_results)
                # Also try Bing for broader context
                if not results:
                    results = self._search_bing(optimized_query, max_results)
            elif is_tech:
                # Technical query: Bing + GitHub first (PubMed usually useless for tech topics)
                logger.info(f"Technical query, searching Bing + GitHub")
                bing_results = self._search_bing(optimized_query, max_results)
                results.extend(bing_results)
                github_results = self._search_github(query, max_results=3, search_type="repositories")
                results.extend(github_results)
                # Only try PubMed if nothing found
                if not results:
                    pubmed_query = self._simplify_for_pubmed(optimized_query)
                    pubmed_results = self._search_pubmed(pubmed_query, max_results=2)
                    results.extend(pubmed_results)
            else:
                # Unknown type: try Bing first (most informative snippets), then PubMed
                logger.info(f"General query, searching Bing first")
                bing_results = self._search_bing(optimized_query, max_results)
                results.extend(bing_results)
                if not results:
                    pubmed_query = self._simplify_for_pubmed(optimized_query)
                    pubmed_results = self._search_pubmed(pubmed_query, max_results=max_results)
                    results.extend(pubmed_results)
                if not results:
                    baidu_results = self._search_baidu(optimized_query, max_results)
                    results.extend(baidu_results)

            # Skip DuckDuckGo - it always times out from this network

        # Track evidence for all results
        for result in results:
            # Safely get snippet, handling None values
            snippet = result.get("snippet") or ""
            evidence_chain.create_evidence_from_search(
                result,
                search_query=query,
                search_type=search_type,
                claim=claim or snippet[:200]
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
