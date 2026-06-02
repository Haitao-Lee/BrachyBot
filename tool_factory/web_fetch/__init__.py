"""
Web Fetch Tool
==============
Fetches web pages and converts HTML to plain text.
Inspired by ZeroClaw's web_fetch implementation.

Use cases:
- Fetch PubMed article pages directly
- Fetch GitHub README files
- Fetch any URL the user provides
- Get detailed information from known URLs
"""

import os
import re
import logging
import requests
from typing import Optional
from urllib.parse import urlparse

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class WebFetchTool(BaseTool):
    """Fetch web pages and return content as clean text."""

    name = "web_fetch"
    description = """Fetch a web page and return its content as clean plain text.
Use this when:
- You have a specific URL to fetch (PubMed, GitHub, etc.)
- User provides a link to read
- You need detailed information from a known page
- Search results include a URL you want to read

Do NOT use this for:
- Searching for information (use web_search instead)
- Fetching binary files (images, PDFs, etc.)
- Accessing private/authenticated pages

The tool will:
- Convert HTML to readable text
- Follow redirects (up to 5)
- Truncate very long responses
- Handle common encoding issues"""

    input_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch (must start with http:// or https://)"
            },
            "max_length": {
                "type": "integer",
                "description": "Maximum length of returned text (default: 5000)",
                "default": 5000
            }
        },
        "required": ["url"]
    }

    output_schema = {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "url": {"type": "string"},
            "title": {"type": "string"},
            "content": {"type": "string"},
            "status_code": {"type": "integer"}
        }
    }

    def _html_to_text(self, html: str) -> str:
        """Convert HTML to clean plain text."""
        # Remove script and style elements
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove HTML comments
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)

        # Block elements - add newlines
        html = re.sub(r'<(br|hr|p|div|h[1-6]|li|tr|td|th)[^>]*>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</(p|div|h[1-6]|li|tr|td|th)>', '\n', html, flags=re.IGNORECASE)

        # Remove remaining tags
        html = re.sub(r'<[^>]+>', '', html)

        # Decode HTML entities
        html = html.replace('&amp;', '&')
        html = html.replace('&lt;', '<')
        html = html.replace('&gt;', '>')
        html = html.replace('&quot;', '"')
        html = html.replace('&#39;', "'")
        html = html.replace('&nbsp;', ' ')

        # Clean up whitespace
        html = re.sub(r'\n\s*\n', '\n\n', html)
        html = re.sub(r'[ \t]+', ' ', html)
        html = html.strip()

        return html

    def _extract_title(self, html: str) -> str:
        """Extract title from HTML."""
        match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if match:
            return re.sub(r'<[^>]+>', '', match.group(1)).strip()
        return ""

    def _execute(self, **kwargs):
        """Execute web fetch with multiple strategies."""
        url = kwargs.get("url", "")
        max_length = kwargs.get("max_length", 5000)

        if not url:
            return ToolResult(
                success=False,
                message="No URL provided"
            )

        # Validate URL
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return ToolResult(
                success=False,
                message="URL must start with http:// or https://"
            )

        # Check for blocked domains (security)
        blocked_domains = ['localhost', '127.0.0.1', '0.0.0.0', '10.', '192.168.', '172.16.']
        hostname = parsed.hostname or ""
        for blocked in blocked_domains:
            if hostname.startswith(blocked):
                return ToolResult(
                    success=False,
                    message="Cannot fetch local/private URLs"
                )

        logger.info(f"Fetching URL: {url}")

        # Strategy 1: Direct fetch
        result = self._fetch_direct(url, max_length)
        if result.success:
            return result

        # Strategy 2: Try PubMed API for PubMed URLs
        if 'pubmed.ncbi.nlm.nih.gov' in url:
            result = self._fetch_pubmed_api(url, max_length)
            if result.success:
                return result

        # Strategy 3: Try GitHub API for GitHub URLs
        if 'github.com' in url:
            result = self._fetch_github_api(url, max_length)
            if result.success:
                return result

        # All strategies failed
        return ToolResult(
            success=False,
            message=f"Failed to fetch URL after trying multiple strategies"
        )

    def _fetch_direct(self, url: str, max_length: int) -> ToolResult:
        """Direct HTTP fetch."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }

            response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
            status_code = response.status_code

            if status_code != 200:
                return ToolResult(success=False, message=f"HTTP {status_code}")

            content_type = response.headers.get('content-type', '')

            # Handle different content types
            if 'application/json' in content_type:
                text = response.text[:max_length]
                title = "JSON Response"
            elif 'text/plain' in content_type or 'text/markdown' in content_type:
                text = response.text[:max_length]
                title = self._extract_title(response.text) or "Text Document"
            else:
                html = response.text
                title = self._extract_title(html) or "Web Page"
                text = self._html_to_text(html)[:max_length]

            return ToolResult(
                success=True,
                data={"url": url, "title": title, "content": text, "status_code": status_code},
                message=f"Fetched: {title}"
            )

        except requests.Timeout:
            return ToolResult(success=False, message="Request timed out")
        except Exception as e:
            return ToolResult(success=False, message=str(e))

    def _fetch_pubmed_api(self, url: str, max_length: int) -> ToolResult:
        """Fetch PubMed article using API."""
        import re
        # Extract PMID from URL
        match = re.search(r'/(\d+)/?$', url)
        if not match:
            return ToolResult(success=False, message="Cannot extract PMID from URL")

        pmid = match.group(1)
        try:
            # Use PubMed E-utilities API
            api_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&rettype=abstract&retmode=text"
            response = requests.get(api_url, timeout=10)

            if response.status_code == 200:
                text = response.text[:max_length]
                # Extract title
                title_match = re.search(r'\d+\.\s+(.+?)\.', text)
                title = title_match.group(1) if title_match else f"PubMed {pmid}"

                return ToolResult(
                    success=True,
                    data={"url": url, "title": title, "content": text, "status_code": 200, "source": "PubMed API"},
                    message=f"Fetched PubMed article: {pmid}"
                )

            return ToolResult(success=False, message="PubMed API failed")
        except Exception as e:
            return ToolResult(success=False, message=str(e))

    def _fetch_github_api(self, url: str, max_length: int) -> ToolResult:
        """Fetch GitHub content using API."""
        import re
        # Extract owner/repo from URL
        match = re.search(r'github\.com/([^/]+)/([^/]+)', url)
        if not match:
            return ToolResult(success=False, message="Cannot parse GitHub URL")

        owner, repo = match.group(1), match.group(2)
        try:
            # Get README via API
            api_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
            headers = {'Accept': 'application/vnd.github.v3.raw'}
            response = requests.get(api_url, headers=headers, timeout=10)

            if response.status_code == 200:
                text = response.text[:max_length]
                return ToolResult(
                    success=True,
                    data={"url": url, "title": f"{owner}/{repo} README", "content": text, "status_code": 200, "source": "GitHub API"},
                    message=f"Fetched GitHub README: {owner}/{repo}"
                )

            return ToolResult(success=False, message="GitHub API failed")
        except Exception as e:
            return ToolResult(success=False, message=str(e))
