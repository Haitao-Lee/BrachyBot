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
import ipaddress
import logging
import socket
import requests
from typing import Optional
from urllib.parse import urljoin, urlparse

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

    @staticmethod
    def _validate_public_url(url: str) -> tuple[bool, str]:
        """Reject credentials and hosts that resolve outside the public Internet."""
        try:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                return False, "URL must use http:// or https://"
            if parsed.username is not None or parsed.password is not None:
                return False, "Credentials in URLs are not allowed"
            hostname = parsed.hostname
            if not hostname:
                return False, "URL must include a hostname"
            # Accessing parsed.port validates malformed/out-of-range ports.
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            return False, f"Invalid URL: {exc}"

        normalized_host = hostname.rstrip(".").lower()
        if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
            return False, "Local/private URLs are not allowed"

        try:
            literal = ipaddress.ip_address(normalized_host)
            addresses = {literal}
        except ValueError:
            try:
                resolved = socket.getaddrinfo(
                    normalized_host,
                    port,
                    type=socket.SOCK_STREAM,
                )
            except OSError as exc:
                return False, f"Hostname resolution failed: {exc}"
            addresses = set()
            for entry in resolved:
                try:
                    addresses.add(ipaddress.ip_address(entry[4][0]))
                except (IndexError, ValueError):
                    continue

        if not addresses:
            return False, "Hostname did not resolve to an IP address"
        if any(not address.is_global for address in addresses):
            return False, "Local/private URLs are not allowed"
        return True, ""

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
        try:
            max_length = max(256, min(int(kwargs.get("max_length", 5000)), 100_000))
        except (TypeError, ValueError):
            return ToolResult(success=False, message="max_length must be an integer")

        if not url:
            return ToolResult(
                success=False,
                message="No URL provided"
            )

        is_public, reason = self._validate_public_url(url)
        if not is_public:
            return ToolResult(success=False, message=reason)

        logger.info(f"Fetching URL: {url}")

        # Strategy 1: Direct fetch
        result = self._fetch_direct(url, max_length)
        if result.success:
            return result
        direct_failure = result

        # Strategy 2: Try PubMed API for PubMed/Nature URLs
        hostname = (urlparse(url).hostname or "").lower()
        if hostname == 'pubmed.ncbi.nlm.nih.gov' or hostname.endswith('.nature.com') or hostname == 'nature.com':
            result = self._fetch_pubmed_api(url, max_length)
            if result.success:
                return result

        # Strategy 3: Try GitHub API for GitHub URLs
        if hostname == 'github.com' or hostname.endswith('.github.com'):
            result = self._fetch_github_api(url, max_length)
            if result.success:
                return result

        # All strategies failed
        return direct_failure

    def _fetch_direct(self, url: str, max_length: int) -> ToolResult:
        """Direct HTTP fetch."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }

            current_url = url
            response = None
            for _ in range(6):
                is_public, reason = self._validate_public_url(current_url)
                if not is_public:
                    return ToolResult(success=False, message=reason)
                response = requests.get(
                    current_url,
                    headers=headers,
                    timeout=(3.05, 10),
                    allow_redirects=False,
                    stream=True,
                )
                if response.status_code not in {301, 302, 303, 307, 308}:
                    break
                location = response.headers.get('location')
                response.close()
                if not location:
                    return ToolResult(success=False, message="Redirect missing Location header")
                current_url = urljoin(current_url, location)
            else:
                return ToolResult(success=False, message="Too many redirects")

            if response is None:
                return ToolResult(success=False, message="No response received")
            status_code = response.status_code

            if status_code != 200:
                response.close()
                return ToolResult(success=False, message=f"HTTP {status_code}")

            content_type = response.headers.get('content-type', '').lower()
            media_type = content_type.split(';', 1)[0].strip()
            allowed_content = (
                not media_type
                or media_type.startswith('text/')
                or media_type == 'application/json'
                or media_type == 'application/xml'
                or media_type.endswith('+xml')
            )
            if not allowed_content:
                response.close()
                return ToolResult(success=False, message=f"Unsupported content type: {content_type}")

            max_download_bytes = min(max(max_length * 8, 128 * 1024), 2 * 1024 * 1024)
            chunks = []
            downloaded = 0
            for chunk in response.iter_content(chunk_size=16 * 1024):
                if not chunk:
                    continue
                remaining = max_download_bytes - downloaded
                if remaining <= 0:
                    break
                chunks.append(chunk[:remaining])
                downloaded += min(len(chunk), remaining)
                if len(chunk) > remaining or downloaded >= max_download_bytes:
                    break
            raw_content = b''.join(chunks)

            # Fix encoding: requests defaults to ISO-8859-1 when charset not specified
            # which garbles CJK characters. Use apparent_encoding as fallback.
            encoding = response.encoding
            if not encoding or encoding.lower() in ('iso-8859-1', 'latin-1', 'ascii'):
                # apparent_encoding reads response.content, so expose only the
                # bounded payload collected above before consulting it.
                response._content = raw_content
                encoding = response.apparent_encoding or 'utf-8'
            text_content = raw_content.decode(encoding, errors='replace')
            response.close()

            # Handle different content types
            if 'application/json' in content_type:
                text = text_content[:max_length]
                title = "JSON Response"
            elif 'text/plain' in content_type or 'text/markdown' in content_type:
                text = text_content[:max_length]
                title = self._extract_title(text_content) or "Text Document"
            else:
                html = text_content
                title = self._extract_title(html) or "Web Page"
                text = self._html_to_text(html)[:max_length]

            return ToolResult(
                success=True,
                data={"url": current_url, "title": title, "content": text, "status_code": status_code},
                message=f"Fetched: {title}"
            )

        except requests.Timeout:
            if 'response' in locals() and response is not None:
                response.close()
            return ToolResult(success=False, message="Request timed out")
        except Exception as e:
            if 'response' in locals() and response is not None:
                response.close()
            return ToolResult(success=False, message=str(e))

    def _fetch_pubmed_api(self, url: str, max_length: int) -> ToolResult:
        """Fetch PubMed article using API. Supports PubMed URLs and Nature URLs with DOI."""
        import re

        pmid = None
        doi = None

        # Try to extract PMID from URL
        match = re.search(r'/(\d+)/?$', url)
        if match:
            pmid = match.group(1)

        # If no PMID, try to extract DOI from Nature URL
        if not pmid and 'nature.com' in url:
            doi_match = re.search(r'(10\.\d{4,}/[^\s]+)', url)
            if doi_match:
                doi = doi_match.group(1)
            else:
                # Nature article ID format: s41586-025-10097-9
                art_match = re.search(r'articles/(s\d+-\d+-\d+-\d+)', url)
                if art_match:
                    doi = f"10.1038/{art_match.group(1)}"

        if not pmid and not doi:
            return ToolResult(success=False, message="Cannot extract PMID or DOI from URL")

        # If we have DOI but no PMID, look up PMID via DOI
        if doi and not pmid:
            try:
                search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={doi}&retmode=json"
                resp = requests.get(search_url, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    ids = data.get("esearchresult", {}).get("idlist", [])
                    if ids:
                        pmid = ids[0]
            except Exception:
                pass

        if not pmid:
            return ToolResult(success=False, message="Could not find PubMed ID for this article")
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
