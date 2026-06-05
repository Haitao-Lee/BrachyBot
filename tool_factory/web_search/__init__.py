"""
Web Search Tool — Systemic Redesign
====================================
Multi-engine search with intelligent query processing, result validation,
language-aware fallback, and proper caching.

Architecture:
    User query → QueryProcessor → SearchEngine(s) → ResultValidator → Response
                   │                    │                  │
              expand/translate    parallel backends    score/filter
              detect intent       fallback chain       deduplicate
              add context         language routing      quality label

Search Engines (priority order):
    1. Bing API (if API key set) — best quality
    2. cn.bing.com — accessible from China, good for English queries
    3. Sogou — good for Chinese queries
    4. PubMed — clinical literature
    5. GitHub — code/repositories

Query Processing:
    - Detect query intent (factual, navigational, research, realtime)
    - Generate language variants (English + Chinese)
    - Preserve key terms (names, numbers, specific terms)
    - Add temporal context for time-sensitive queries

Result Validation:
    - Relevance scoring (key term matching)
    - Source quality weighting (academic > news > blog)
    - Deduplication across engines
    - Quality label: good / partial / poor
"""

import json
import os
import re
import time
import hashlib
import logging
import requests
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import quote_plus
from datetime import datetime, timedelta

from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)


# ============================================================
# Query Processor
# ============================================================

class QueryProcessor:
    """Intelligent query preprocessing with intent detection and language handling."""

    # Intent patterns
    INTENT_PATTERNS = {
        'factual': [
            r'(what|who|when|where|是什么|什么是|哪个|谁|什么时候|在哪里)',
            r'(define|definition|定义|含义)',
        ],
        'research': [
            r'(paper|publication|journal|论文|期刊|研究)',
            r'(impact factor|影响因子|cite score|JCR)',
            r'(review|survey|综述)',
        ],
        'realtime': [
            r'(latest|recent|new|最新|最近|新闻)',
            r'(today|yesterday|this week|今天|昨天|本周)',
            r'(weather|temperature|天气|气温)',
            r'(stock|price|股价|价格)',
        ],
        'navigational': [
            r'(official website|官网|官方网站)',
            r'(download|下载|login|登录)',
        ],
    }

    # Time-sensitive keywords that need current year
    TIME_KEYWORDS = [
        'impact factor', '影响因子', 'cite score', 'JCR',
        'latest', '最新', 'recent', '最近',
        'price', '价格', 'stock', '股价',
        'weather', '天气', 'temperature', '气温',
        'version', '版本', 'release', '发布',
        'ranking', '排名', 'score', '分数',
    ]

    # English → Chinese keyword mapping for better Chinese search results
    EN_TO_ZH = {
        'impact factor': '影响因子',
        'ranking': '排名',
        'journal': '期刊',
        'publication': '论文',
        'guideline': '指南',
        'protocol': '规范',
        'dose': '剂量',
        'treatment': '治疗',
        'diagnosis': '诊断',
    }

    @staticmethod
    def detect_intent(query: str) -> str:
        """Detect query intent: factual, research, realtime, navigational."""
        q = query.lower()
        for intent, patterns in QueryProcessor.INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, q, re.IGNORECASE):
                    return intent
        return 'factual'

    # Common long name → short name mappings
    SHORT_NAMES = {
        'ieee transactions on medical imaging': 'IEEE TMI',
        'medical image analysis': 'Medical Image Analysis',
        'international journal of radiation oncology biology physics': 'Int J Radiat Oncol',
        'journal of clinical oncology': 'JCO',
    }

    @staticmethod
    def generate_variants(query: str) -> List[str]:
        """Generate query variants for better coverage.

        Returns list of queries to try, in priority order.
        """
        variants = [query]  # Original query first
        q_lower = query.lower()

        # Add current year for time-sensitive queries
        current_year = str(datetime.now().year)
        if any(kw in q_lower for kw in QueryProcessor.TIME_KEYWORDS):
            cleaned = re.sub(r'\b20\d{2}\b', '', query).strip()
            if current_year not in cleaned:
                variants.append(f"{cleaned} {current_year}")

        # Generate short name variant (e.g., "IEEE Transactions on Medical Imaging" → "IEEE TMI")
        for long_name, short_name in QueryProcessor.SHORT_NAMES.items():
            if long_name in q_lower:
                short_query = re.sub(re.escape(long_name), short_name, query, flags=re.IGNORECASE)
                if short_query != query:
                    variants.append(short_query)
                # Also short + Chinese
                for en_kw, zh_kw in QueryProcessor.EN_TO_ZH.items():
                    if en_kw in q_lower:
                        variants.append(f"{short_name} {zh_kw}")
                break

        # Generate Chinese variant if query has English keywords
        zh_parts = []
        for en_kw, zh_kw in QueryProcessor.EN_TO_ZH.items():
            if en_kw in q_lower and zh_kw not in query:
                main = re.sub(re.escape(en_kw), '', query, flags=re.IGNORECASE).strip()
                main = re.sub(r'\b20\d{2}\b', '', main).strip()
                zh_parts.append(f"{main} {zh_kw}")

        if zh_parts:
            variants.extend(zh_parts)

        # Generate simplified variant (remove years, extra terms)
        simplified = re.sub(r'\b20\d{2}\b', '', query).strip()
        if simplified != query and simplified:
            variants.append(simplified)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for v in variants:
            v_lower = v.lower().strip()
            if v_lower and v_lower not in seen:
                seen.add(v_lower)
                unique.append(v)

        return unique


# ============================================================
# Specialized Search Engines
# ============================================================
# Each engine handles a specific domain with direct API access.
# The search tool checks these BEFORE falling back to general web search.
# To add a new source: add an entry to SPECIALIZED_ENGINES.

class SpecializedEngine:
    """A specialized search engine for a specific domain.

    Each engine can optionally provide:
    - triggers: keywords that activate this engine
    - search_fn: the search function(query, max_results) -> List[Dict]
    - optimize_fn: query optimizer(query) -> optimized_query (optional)
    """

    def __init__(self, name: str, triggers: List[str], search_fn, description: str = "", optimize_fn=None):
        self.name = name
        self.triggers = triggers
        self.search_fn = search_fn
        self.description = description
        self.optimize_fn = optimize_fn

    def matches(self, query: str) -> bool:
        q = query.lower()
        return any(t in q for t in self.triggers)

    def optimize_query(self, query: str) -> str:
        """Optimize query for this specific engine. Default: pass through."""
        if self.optimize_fn:
            return self.optimize_fn(query)
        return query

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        """Optimize query then search."""
        try:
            optimized = self.optimize_query(query)
            return self.search_fn(optimized, max_results)
        except Exception as e:
            logger.warning(f"Specialized engine {self.name} error: {e}")
            return []


def _search_weather(query: str, max_results: int = 5) -> List[Dict]:
    """Weather via wttr.in API. Supports any city name — no hardcoded mapping."""
    # Extract city name: remove weather-related keywords, keep the city
    weather_noise = [
        '天气', 'weather', '气温', '温度', 'temperature', 'forecast',
        '今日', '今天', '明天', 'yesterday', 'today', 'tomorrow',
        '怎么样', '如何', '查询', '帮我查询', '帮我', '请',
    ]
    # English noise words — use word-boundary regex to avoid breaking "Beijing" (contains "in")
    en_noise = ['how', 'what', 'the', 'in', 'at', 'for', 'is', 'of']
    city = query.strip()
    for noise in weather_noise:
        city = city.replace(noise, '')
    for noise in en_noise:
        city = re.sub(r'\b' + noise + r'\b', '', city, flags=re.IGNORECASE)
    # Remove common punctuation and extra spaces
    city = re.sub(r'[?？!！。，,\s]+', ' ', city).strip()
    if not city:
        city = "Shanghai"

    resp = requests.get(f"https://wttr.in/{city}?format=j1", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        current = data.get("current_condition", [{}])[0]
        temp = current.get("temp_C", "?")
        desc = current.get("weatherDesc", [{}])[0].get("value", "")
        humidity = current.get("humidity", "?")
        wind = current.get("windspeedKmph", "?")
        feels = current.get("FeelsLikeC", "?")
        snippet = f"{city}: {temp}°C, {desc}, Humidity: {humidity}%, Wind: {wind} km/h, Feels like: {feels}°C"
        return [{"title": f"{city} Weather", "snippet": snippet, "url": f"https://wttr.in/{city}", "source": "wttr.in", "page_content": snippet}]
    return []


def _search_exchange_rate(query: str, max_results: int = 5) -> List[Dict]:
    """Exchange rates via exchangerate-api.com."""
    # Extract currency codes
    currencies = re.findall(r'(USD|EUR|GBP|JPY|CNY|HKD|KRW|CAD|AUD|CHF)', query.upper())
    if len(currencies) >= 2:
        base, target = currencies[0], currencies[1]
    elif any(kw in query for kw in ['美元', 'dollar', 'usd']):
        base, target = 'USD', 'CNY'
    elif any(kw in query for kw in ['欧元', 'euro', 'eur']):
        base, target = 'EUR', 'CNY'
    elif any(kw in query for kw in ['日元', 'yen', 'jpy']):
        base, target = 'JPY', 'CNY'
    elif any(kw in query for kw in ['英镑', 'pound', 'gbp']):
        base, target = 'GBP', 'CNY'
    else:
        base, target = 'USD', 'CNY'

    resp = requests.get(f"https://open.er-api.com/v6/latest/{base}", timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        rate = data.get("rates", {}).get(target)
        if rate:
            snippet = f"1 {base} = {rate} {target} (source: open.er-api.com)"
            return [{"title": f"{base}/{target} Exchange Rate", "snippet": snippet, "url": f"https://open.er-api.com/v6/latest/{base}", "source": "ExchangeRate API", "page_content": snippet}]
    return []


def _search_pubmed_direct(query: str, max_results: int = 5) -> List[Dict]:
    """PubMed search for clinical literature."""
    results = []
    try:
        search_resp = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db": "pubmed", "term": query, "retmax": max_results, "retmode": "json"}, timeout=10)
        if search_resp.status_code != 200:
            return results
        ids = search_resp.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return results
        fetch_resp = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"}, timeout=10)
        if fetch_resp.status_code == 200:
            for uid in ids:
                article = fetch_resp.json().get("result", {}).get(uid, {})
                if article:
                    title = article.get("title", "")
                    authors = ", ".join(a.get("name", "") for a in article.get("authors", [])[:3])
                    source = article.get("fulljournalname", article.get("source", ""))
                    pub_date = article.get("pubdate", "")
                    results.append({"title": title[:200], "snippet": f"{authors}. {source}. {pub_date}".strip(),
                                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/", "source": "PubMed"})
    except Exception as e:
        logger.warning(f"PubMed error: {e}")
    return results


def _search_semantic_scholar(query: str, max_results: int = 5) -> List[Dict]:
    """Semantic Scholar API for academic papers."""
    results = []
    try:
        resp = requests.get("https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": query, "limit": max_results, "fields": "title,abstract,year,url,citationCount"},
            timeout=10)
        if resp.status_code == 200:
            for paper in resp.json().get("data", [])[:max_results]:
                title = paper.get("title", "")
                abstract = (paper.get("abstract") or "")[:200]
                year = paper.get("year", "")
                citations = paper.get("citationCount", 0)
                url = paper.get("url", "")
                snippet = f"({year}) {abstract} [Citations: {citations}]"
                results.append({"title": title, "snippet": snippet, "url": url, "source": "Semantic Scholar"})
    except Exception as e:
        logger.warning(f"Semantic Scholar error: {e}")
    return results


def _search_clinical_trials(query: str, max_results: int = 5) -> List[Dict]:
    """ClinicalTrials.gov API for clinical trial data."""
    results = []
    try:
        resp = requests.get("https://clinicaltrials.gov/api/v2/studies",
            params={"query.term": query, "pageSize": max_results, "format": "json"}, timeout=15)
        if resp.status_code == 200:
            for study in resp.json().get("studies", [])[:max_results]:
                proto = study.get("protocolSection", {})
                ident = proto.get("identificationModule", {})
                status = proto.get("statusModule", {})
                title = ident.get("briefTitle", "")
                nct = ident.get("nctId", "")
                phase = ", ".join(status.get("phases", []))
                study_status = status.get("overallStatus", "")
                snippet = f"[{nct}] Status: {study_status}, Phase: {phase}"
                results.append({"title": title[:200], "snippet": snippet,
                                "url": f"https://clinicaltrials.gov/study/{nct}", "source": "ClinicalTrials.gov"})
    except Exception as e:
        logger.warning(f"ClinicalTrials.gov error: {e}")
    return results


def _search_fda(query: str, max_results: int = 5) -> List[Dict]:
    """FDA API for drug approvals and safety alerts."""
    results = []
    try:
        resp = requests.get("https://api.fda.gov/drug/label.json",
            params={"search": f"openfda.brand_name:{query}", "limit": max_results}, timeout=10)
        if resp.status_code == 200:
            for item in resp.json().get("results", [])[:max_results]:
                brand = ", ".join(item.get("openfda", {}).get("brand_name", [""]))
                generic = ", ".join(item.get("openfda", {}).get("generic_name", [""]))
                purpose = item.get("purpose", [""])[0] if item.get("purpose") else ""
                snippet = f"{brand} ({generic}): {purpose[:200]}"
                results.append({"title": f"{brand} - {generic}", "snippet": snippet, "url": "https://www.fda.gov/", "source": "FDA"})
    except Exception as e:
        logger.warning(f"FDA error: {e}")
    return results


def _search_stackoverflow(query: str, max_results: int = 5) -> List[Dict]:
    """Stack Overflow API for programming Q&A."""
    results = []
    try:
        resp = requests.get("https://api.stackexchange.com/2.3/search/advanced",
            params={"q": query, "order": "desc", "sort": "relevance", "site": "stackoverflow",
                    "pagesize": max_results, "filter": "default"}, timeout=10)
        if resp.status_code == 200:
            for item in resp.json().get("items", [])[:max_results]:
                title = item.get("title", "")
                score = item.get("score", 0)
                answers = item.get("answer_count", 0)
                link = item.get("link", "")
                snippet = f"Score: {score}, Answers: {answers}"
                results.append({"title": title, "snippet": snippet, "url": link, "source": "Stack Overflow"})
    except Exception as e:
        logger.warning(f"Stack Overflow error: {e}")
    return results


def _search_papers_with_code(query: str, max_results: int = 5) -> List[Dict]:
    """Papers With Code for ML papers with implementations."""
    results = []
    try:
        resp = requests.get("https://paperswithcode.com/api/v1/search/",
            params={"q": query, "page": 1}, timeout=10)
        if resp.status_code == 200:
            for item in resp.json().get("results", [])[:max_results]:
                paper = item.get("paper", {})
                title = paper.get("title", "")
                abstract = (paper.get("abstract") or "")[:200]
                url = f"https://paperswithcode.com{paper.get('url_abs', '')}"
                results.append({"title": title, "snippet": abstract, "url": url, "source": "Papers With Code"})
    except Exception as e:
        logger.warning(f"Papers With Code error: {e}")
    return results


def _search_github_repos(query: str, max_results: int = 5) -> List[Dict]:
    """GitHub repository search."""
    results = []
    try:
        headers = {"Accept": "application/vnd.github.v3+json"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"token {token}"
        resp = requests.get("https://api.github.com/search/repositories",
            headers=headers, params={"q": query, "per_page": max_results}, timeout=10)
        if resp.status_code == 200:
            for item in resp.json().get("items", [])[:max_results]:
                results.append({"title": item.get("full_name", ""), "snippet": (item.get("description") or "")[:200],
                                "url": item.get("html_url", ""), "source": "GitHub"})
    except Exception as e:
        logger.warning(f"GitHub error: {e}")
    return results


# ============================================================
# Query Optimizers (per-engine)
# ============================================================
# Each optimizer transforms the user's natural language query into
# the format that works best for that specific engine.

def _optimize_github(query: str) -> str:
    """GitHub API works best with 1-3 keywords (project name)."""
    words = query.strip().split()
    if len(words) <= 3:
        return query
    # Remove common filler words
    stop = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has',
            'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may',
            'of', 'in', 'on', 'at', 'to', 'for', 'with', 'by', 'from', 'as',
            'and', 'or', 'but', 'not', 'no', 'what', 'how', 'why', 'when', 'where',
            'this', 'that', 'these', 'those', 'it', 'its', 'my', 'your', 'his', 'her',
            'about', 'latest', 'research', 'code', 'implementation', 'system', 'technical',
            '请', '帮我', '查', '搜索', '一下'}
    key = [w for w in words if w.lower() not in stop and len(w) > 1]
    if key:
        return ' '.join(key[:3])
    return ' '.join(words[:2])


def _optimize_pubmed(query: str) -> str:
    """PubMed works best with medical terms, no natural language filler."""
    # Remove common question patterns
    noise = ['what is', 'what are', 'how to', 'tell me about', 'please', 'can you',
             '什么是', '介绍一下', '告诉我', '请问', '帮我查']
    q = query
    for n in noise:
        q = re.sub(re.escape(n), '', q, flags=re.IGNORECASE)
    return q.strip() or query


def _optimize_arxiv(query: str) -> str:
    """arXiv works best with technical terms."""
    noise = ['what is', 'tell me about', 'find papers on', 'search for',
             '介绍一下', '查找', '搜索']
    q = query
    for n in noise:
        q = re.sub(re.escape(n), '', q, flags=re.IGNORECASE)
    return q.strip() or query


def _search_crossref(query: str, max_results: int = 5) -> List[Dict]:
    """CrossRef API — universal DOI metadata for all academic publishers."""
    results = []
    try:
        resp = requests.get("https://api.crossref.org/works",
            params={"query": query, "rows": max_results, "sort": "relevance"}, timeout=15)
        if resp.status_code == 200:
            for item in resp.json().get("message", {}).get("items", [])[:max_results]:
                title = item.get("title", [""])[0]
                doi = item.get("DOI", "")
                year = item.get("published-print", item.get("published-online", {})).get("date-parts", [[None]])[0][0]
                journal = item.get("container-title", [""])[0]
                citations = item.get("is-referenced-by-count", 0)
                authors = ", ".join(a.get("family", "") for a in item.get("author", [])[:3])
                snippet = f"({year}) {authors}. {journal}. Citations: {citations}"
                url = f"https://doi.org/{doi}" if doi else ""
                results.append({"title": title, "snippet": snippet, "url": url, "source": f"CrossRef ({journal})"})
    except Exception as e:
        logger.warning(f"CrossRef error: {e}")
    return results


def _search_openalex(query: str, max_results: int = 5) -> List[Dict]:
    """OpenAlex — open academic database with citation data and full-text links."""
    results = []
    try:
        resp = requests.get("https://api.openalex.org/works",
            params={"search": query, "per_page": max_results, "sort": "relevance_score:desc"},
            headers={"User-Agent": "BrachyBot/1.0 (mailto:brachybot@example.com)"}, timeout=15)
        if resp.status_code == 200:
            for work in resp.json().get("results", [])[:max_results]:
                title = work.get("title", "")
                year = work.get("publication_year", "")
                doi = work.get("doi", "")
                cited = work.get("cited_by_count", 0)
                source = work.get("primary_location", {}).get("source", {}).get("display_name", "")
                oa_url = work.get("open_access", {}).get("oa_url", "")
                snippet = f"({year}) {source}. Citations: {cited}"
                url = oa_url or doi or ""
                results.append({"title": title, "snippet": snippet, "url": url, "source": f"OpenAlex ({source})"})
    except Exception as e:
        logger.warning(f"OpenAlex error: {e}")
    return results


def _search_arxiv(query: str, max_results: int = 5) -> List[Dict]:
    """arXiv API for preprints."""
    results = []
    try:
        resp = requests.get("http://export.arxiv.org/api/query",
            params={"search_query": f"all:{query}", "max_results": max_results, "sortBy": "relevance"},
            timeout=15)
        if resp.status_code == 200:
            entries = re.findall(r'<entry>(.*?)</entry>', resp.text, re.DOTALL)
            for entry in entries[:max_results]:
                title = re.search(r'<title>(.*?)</title>', entry, re.DOTALL)
                summary = re.search(r'<summary>(.*?)</summary>', entry, re.DOTALL)
                link = re.search(r'<id>(.*?)</id>', entry)
                published = re.search(r'<published>(.*?)</published>', entry)
                if title:
                    t = re.sub(r'\s+', ' ', title.group(1)).strip()
                    s = re.sub(r'\s+', ' ', summary.group(1)).strip()[:200] if summary else ""
                    year = published.group(1)[:4] if published else ""
                    url = link.group(1) if link else ""
                    results.append({"title": t, "snippet": f"({year}) {s}", "url": url, "source": "arXiv"})
    except Exception as e:
        logger.warning(f"arXiv error: {e}")
    return results


def _search_biorxiv(query: str, max_results: int = 5) -> List[Dict]:
    """bioRxiv/medRxiv API for biology/medicine preprints."""
    results = []
    try:
        resp = requests.get(f"https://api.biorxiv.org/details/biorxiv/2024-01-01/2026-12-31/0",
                            timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("collection", [])[:max_results]:
                title = item.get("title", "")
                doi = item.get("doi", "")
                date = item.get("date", "")
                category = item.get("category", "")
                snippet = f"({date}) Category: {category}"
                url = f"https://doi.org/{doi}" if doi else ""
                results.append({"title": title, "snippet": snippet, "url": url, "source": "bioRxiv"})
    except Exception as e:
        logger.warning(f"bioRxiv error: {e}")
    return results


def _search_springer(query: str, max_results: int = 5) -> List[Dict]:
    """Springer Nature web scraping for journal articles."""
    results = []
    try:
        resp = requests.get(f"https://link.springer.com/search?query={requests.utils.quote(query)}&showAll=false",
                            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                            timeout=15)
        if resp.status_code == 200:
            # Extract search results
            items = re.findall(r'<li class="c-list-group__item"[^>]*>(.*?)</li>', resp.text, re.DOTALL)
            if not items:
                items = re.findall(r'<a[^>]*class="title"[^>]*>(.*?)</a>', resp.text, re.DOTALL)
            for item in items[:max_results]:
                title = re.sub(r'<[^>]+>', '', item).strip()
                if title and len(title) > 10:
                    results.append({"title": title[:200], "snippet": "", "url": f"https://link.springer.com/search?query={requests.utils.quote(query)}", "source": "Springer Nature"})
    except Exception as e:
        logger.warning(f"Springer error: {e}")
    return results


def _search_ieee_xplore(query: str, max_results: int = 5) -> List[Dict]:
    """IEEE Xplore web scraping for engineering/medical imaging papers."""
    results = []
    try:
        resp = requests.get(f"https://ieeexplore.ieee.org/search/searchresult.jsp?queryText={requests.utils.quote(query)}",
                            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                            timeout=15)
        if resp.status_code == 200:
            # IEEE Xplore loads results via JS, but we can extract some from meta tags
            titles = re.findall(r'<meta name="citation_title" content="([^"]*)"', resp.text)
            for title in titles[:max_results]:
                results.append({"title": title, "snippet": "", "url": f"https://ieeexplore.ieee.org/search/searchresult.jsp?queryText={requests.utils.quote(query)}", "source": "IEEE Xplore"})
    except Exception as e:
        logger.warning(f"IEEE Xplore error: {e}")
    return results


def _search_google_patents(query: str, max_results: int = 5) -> List[Dict]:
    """Google Patents search for patent information."""
    results = []
    try:
        url = f"https://patents.google.com/xhr/query?url=q%3D{requests.utils.quote(query)}"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("results", {}).get("patents", [])[:max_results]:
                title = item.get("title", "")
                snippet = item.get("abstract", "")[:200]
                patent_id = item.get("patent_number", "")
                pub_date = item.get("publication_date", "")
                results.append({"title": f"[{patent_id}] {title}", "snippet": f"({pub_date}) {snippet}",
                                "url": f"https://patents.google.com/patent/{patent_id}", "source": "Google Patents"})
    except Exception as e:
        logger.warning(f"Google Patents error: {e}")
    # Fallback: scrape Google Patents HTML
    if not results:
        try:
            resp = requests.get(f"https://patents.google.com/?q={requests.utils.quote(query)}",
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if resp.status_code == 200:
                titles = re.findall(r'<h3[^>]*>(.*?)</h3>', resp.text)
                for t in titles[:max_results]:
                    clean = re.sub(r'<[^>]+>', '', t).strip()
                    if clean:
                        results.append({"title": clean, "snippet": "", "url": f"https://patents.google.com/?q={requests.utils.quote(query)}", "source": "Google Patents"})
        except Exception as e:
            logger.warning(f"Google Patents fallback error: {e}")
    return results


def _search_nccn(query: str, max_results: int = 5) -> List[Dict]:
    """NCCN Guidelines search."""
    results = []
    try:
        resp = requests.get(f"https://www.nccn.org/search?query={requests.utils.quote(query)}",
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            blocks = re.findall(r'<div class="search-result"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
            for block in blocks[:max_results]:
                title_m = re.search(r'<a[^>]*>(.*?)</a>', block)
                snippet_m = re.search(r'<p[^>]*>(.*?)</p>', block)
                if title_m:
                    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                    snippet = re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip() if snippet_m else ""
                    results.append({"title": title, "snippet": snippet[:200], "url": "https://www.nccn.org/guidelines", "source": "NCCN"})
    except Exception as e:
        logger.warning(f"NCCN search error: {e}")
    return results


def _search_radiopaedia(query: str, max_results: int = 5) -> List[Dict]:
    """Radiopaedia — radiology knowledge base with case-based learning."""
    results = []
    try:
        resp = requests.get(f"https://radiopaedia.org/search?q={requests.utils.quote(query)}&scope=articles",
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            articles = re.findall(r'<article[^>]*>(.*?)</article>', resp.text, re.DOTALL)
            for article in articles[:max_results]:
                title_m = re.search(r'<h2[^>]*><a[^>]*>(.*?)</a>', article, re.DOTALL)
                snippet_m = re.search(r'<p class="article-body"[^>]*>(.*?)</p>', article, re.DOTALL)
                url_m = re.search(r'<a[^>]*href="([^"]*)"', article)
                if title_m:
                    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                    snippet = re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip() if snippet_m else ""
                    url = f"https://radiopaedia.org{url_m.group(1)}" if url_m else ""
                    results.append({"title": title, "snippet": snippet[:200], "url": url, "source": "Radiopaedia"})
    except Exception as e:
        logger.warning(f"Radiopaedia error: {e}")
    return results


def _search_omim(query: str, max_results: int = 5) -> List[Dict]:
    """OMIM — Online Mendelian Inheritance in Man (genetic disorders)."""
    results = []
    try:
        resp = requests.get(f"https://omim.org/search/?search={requests.utils.quote(query)}&start=0&limit={max_results}",
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            entries = re.findall(r'<div class="search-result"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
            for entry in entries[:max_results]:
                title_m = re.search(r'<a[^>]*>(.*?)</a>', entry)
                snippet_m = re.search(r'<p[^>]*>(.*?)</p>', entry)
                if title_m:
                    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                    snippet = re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip() if snippet_m else ""
                    results.append({"title": title, "snippet": snippet[:200], "url": f"https://omim.org/search/?search={requests.utils.quote(query)}", "source": "OMIM"})
    except Exception as e:
        logger.warning(f"OMIM error: {e}")
    return results


def _search_icd(query: str, max_results: int = 5) -> List[Dict]:
    """ICD-11 API search for disease classification codes."""
    results = []
    try:
        resp = requests.get("https://id.who.int/icd/entity/search",
                            params={"q": query, "flatResults": "true", "maxResults": max_results},
                            headers={"Accept": "application/json", "Accept-Language": "en"}, timeout=10)
        if resp.status_code == 200:
            for entity in resp.json().get("destinationEntities", [])[:max_results]:
                title = entity.get("title", "")
                code = entity.get("theCode", "")
                definition = entity.get("definition", "")[:200]
                entity_id = entity.get("id", "")
                snippet = f"[{code}] {definition}" if code else definition
                results.append({"title": title, "snippet": snippet, "url": f"https://icd.who.int/browse{entity_id}", "source": "ICD-11 (WHO)"})
    except Exception as e:
        logger.warning(f"ICD-11 error: {e}")
    return results


def _search_cnipa(query: str, max_results: int = 5) -> List[Dict]:
    """CNIPA (China National Intellectual Property Administration) patent search."""
    results = []
    try:
        resp = requests.get(f"https://pss-system.cponline.cnipa.gov.cn/conventionalSearch",
                            params={"searchWord": query}, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            # Extract patent entries from HTML
            entries = re.findall(r'<div class="result-item"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
            for entry in entries[:max_results]:
                title_m = re.search(r'<a[^>]*>(.*?)</a>', entry)
                if title_m:
                    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                    results.append({"title": title, "snippet": "", "url": "https://pss-system.cponline.cnipa.gov.cn/", "source": "CNIPA"})
    except Exception as e:
        logger.warning(f"CNIPA error: {e}")
    return results


def _search_cnki(query: str, max_results: int = 5) -> List[Dict]:
    """CNKI (China National Knowledge Infrastructure) — Chinese academic database."""
    results = []
    try:
        resp = requests.get(f"https://kns.cnki.net/kns8s/defaultresult/index",
                            params={"kw": query, "korder": "SU"},
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            entries = re.findall(r'<div class="result-table-list"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
            for entry in entries[:max_results]:
                title_m = re.search(r'<a[^>]*>(.*?)</a>', entry)
                if title_m:
                    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                    results.append({"title": title, "snippet": "", "url": f"https://kns.cnki.net/kns8s/defaultresult/index?kw={requests.utils.quote(query)}", "source": "CNKI"})
    except Exception as e:
        logger.warning(f"CNKI error: {e}")
    return results


def _search_wanfang(query: str, max_results: int = 5) -> List[Dict]:
    """Wanfang Data — Chinese academic database."""
    results = []
    try:
        resp = requests.get(f"https://s.wanfangdata.com.cn/paper",
                            params={"q": query}, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            entries = re.findall(r'<div class="normal-list"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
            for entry in entries[:max_results]:
                title_m = re.search(r'<a[^>]*>(.*?)</a>', entry)
                if title_m:
                    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                    results.append({"title": title, "snippet": "", "url": f"https://s.wanfangdata.com.cn/paper?q={requests.utils.quote(query)}", "source": "Wanfang"})
    except Exception as e:
        logger.warning(f"Wanfang error: {e}")
    return results


def _search_europepmc(query: str, max_results: int = 5) -> List[Dict]:
    """Europe PMC — open access biomedical literature."""
    results = []
    try:
        resp = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": query, "format": "json", "pageSize": max_results},
            timeout=15)
        if resp.status_code == 200:
            for item in resp.json().get("resultList", {}).get("result", [])[:max_results]:
                title = item.get("title", "")
                authors = item.get("authorString", "")
                journal = item.get("journalTitle", "")
                year = item.get("pubYear", "")
                pmid = item.get("pmid", "")
                doi = item.get("doi", "")
                snippet = f"({year}) {authors[:80]}. {journal}"
                url = f"https://europepmc.org/article/PMID/{pmid}" if pmid else f"https://doi.org/{doi}"
                results.append({"title": title, "snippet": snippet, "url": url, "source": "Europe PMC"})
    except Exception as e:
        logger.warning(f"Europe PMC error: {e}")
    return results


def _search_lens(query: str, max_results: int = 5) -> List[Dict]:
    """Lens.org — scholarly search covering patents and literature."""
    results = []
    try:
        resp = requests.get("https://www.lens.org/lens/search/scholar/list",
            params={"q": query, "p": 0, "n": max_results},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if resp.status_code == 200:
            # Extract from HTML
            entries = re.findall(r'<div class="scholar-result[^"]*"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
            for entry in entries[:max_results]:
                title_m = re.search(r'<a[^>]*>(.*?)</a>', entry)
                if title_m:
                    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                    results.append({"title": title[:200], "snippet": "", "url": f"https://www.lens.org/lens/search/scholar/list?q={requests.utils.quote(query)}", "source": "Lens.org"})
    except Exception as e:
        logger.warning(f"Lens.org error: {e}")
    return results


def _search_mesh(query: str, max_results: int = 5) -> List[Dict]:
    """MeSH (Medical Subject Headings) — NCBI controlled vocabulary."""
    results = []
    try:
        resp = requests.get("https://id.nlm.nih.gov/mesh/lookup/descriptor",
            params={"label": query, "match": "contains", "limit": max_results},
            timeout=10)
        if resp.status_code == 200:
            for item in resp.json()[:max_results]:
                label = item.get("label", "")
                resource = item.get("resource", "")
                mesh_id = resource.split("/")[-1] if resource else ""
                results.append({"title": f"MeSH: {label}", "snippet": f"MeSH ID: {mesh_id}",
                                "url": f"https://meshb.nlm.nih.gov/record/ui?ui={mesh_id}", "source": "MeSH"})
    except Exception as e:
        logger.warning(f"MeSH error: {e}")
    return results


def _search_aapm(query: str, max_results: int = 5) -> List[Dict]:
    """AAPM reports and task group guidelines."""
    results = []
    try:
        resp = requests.get("https://www.aapm.org/pubs/reports/",
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            # Extract report entries
            entries = re.findall(r'<tr[^>]*>(.*?)</tr>', resp.text, re.DOTALL)
            for entry in entries[:max_results * 3]:  # Search more to filter
                cells = re.findall(r'<td[^>]*>(.*?)</td>', entry, re.DOTALL)
                if len(cells) >= 2:
                    title = re.sub(r'<[^>]+>', '', cells[0]).strip()
                    desc = re.sub(r'<[^>]+>', '', cells[1]).strip()
                    if any(kw in title.lower() or kw in desc.lower() for kw in query.lower().split()):
                        results.append({"title": title[:200], "snippet": desc[:200],
                                        "url": "https://www.aapm.org/pubs/reports/", "source": "AAPM"})
                        if len(results) >= max_results:
                            break
    except Exception as e:
        logger.warning(f"AAPM error: {e}")
    return results


def _search_iop(query: str, max_results: int = 5) -> List[Dict]:
    """IOP Publishing — Physics in Medicine & Biology."""
    results = []
    try:
        resp = requests.get(f"https://iopscience.iop.org/search",
            params={"value": query, "searchType": "journalSearch"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if resp.status_code == 200:
            entries = re.findall(r'<div class="search-result"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
            for entry in entries[:max_results]:
                title_m = re.search(r'<a[^>]*>(.*?)</a>', entry)
                if title_m:
                    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                    results.append({"title": title[:200], "snippet": "", "url": f"https://iopscience.iop.org/search?value={requests.utils.quote(query)}", "source": "IOP (Phys Med Biol)"})
    except Exception as e:
        logger.warning(f"IOP error: {e}")
    return results


# Registry of specialized engines
    """Wanfang Data — Chinese academic database."""
    results = []
    try:
        resp = requests.get(f"https://s.wanfangdata.com.cn/paper",
                            params={"q": query}, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            entries = re.findall(r'<div class="normal-list"[^>]*>(.*?)</div>', resp.text, re.DOTALL)
            for entry in entries[:max_results]:
                title_m = re.search(r'<a[^>]*>(.*?)</a>', entry)
                if title_m:
                    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                    results.append({"title": title, "snippet": "", "url": f"https://s.wanfangdata.com.cn/paper?q={requests.utils.quote(query)}", "source": "Wanfang"})
    except Exception as e:
        logger.warning(f"Wanfang error: {e}")
    return results


# Registry of specialized engines
SPECIALIZED_ENGINES = [
    # Real-time data
    SpecializedEngine("Weather", ["天气", "weather", "气温", "temperature", "forecast"],
                      _search_weather, "Real-time weather via wttr.in API"),
    SpecializedEngine("Exchange Rate", ["汇率", "exchange rate", "美元", "欧元", "日元", "英镑", "usd", "eur"],
                      _search_exchange_rate, "Live exchange rates via open.er-api.com"),

    # Medical guidelines & knowledge
    SpecializedEngine("NCCN Guidelines", ["nccn", "指南", "guideline", "治疗规范"],
                      _search_nccn, "NCCN clinical practice guidelines"),
    SpecializedEngine("Radiopaedia", ["radiopaedia", "影像学", "radiology", "影像诊断"],
                      _search_radiopaedia, "Radiology knowledge base with cases"),
    SpecializedEngine("ICD Codes", ["icd", "疾病编码", "诊断编码", "disease code"],
                      _search_icd, "ICD-11 disease classification codes (WHO)"),
    SpecializedEngine("OMIM", ["omim", "遗传病", "genetic disorder", "基因突变"],
                      _search_omim, "Online Mendelian Inheritance in Man (genetic disorders)"),

    # Clinical research
    SpecializedEngine("Clinical Trials", ["临床试验", "clinical trial", "clinicaltrials.gov"],
                      _search_clinical_trials, "Clinical trial data from ClinicalTrials.gov API"),
    SpecializedEngine("FDA Drugs", ["fda", "药物批准", "drug approval", "药物安全"],
                      _search_fda, "FDA drug labels and approvals"),
    SpecializedEngine("PubMed", ["pubmed", "医学文献", "临床研究", "clinical study"],
                      _search_pubmed_direct, "Clinical literature via PubMed E-utilities",
                      optimize_fn=_optimize_pubmed),
    SpecializedEngine("Semantic Scholar", ["论文", "paper", "publication", "引用", "citation"],
                      _search_semantic_scholar, "Academic papers via Semantic Scholar API"),
    SpecializedEngine("CrossRef", ["doi", "crossref", "期刊论文", "journal article"],
                      _search_crossref, "Universal DOI metadata for all publishers"),
    SpecializedEngine("OpenAlex", ["openalex", "学术数据库", "citation count", "被引"],
                      _search_openalex, "Open academic database with full-text links"),
    SpecializedEngine("arXiv", ["arxiv", "预印本", "preprint"],
                      _search_arxiv, "arXiv preprints", optimize_fn=_optimize_arxiv),
    SpecializedEngine("bioRxiv", ["biorxiv", "medrxiv", "生物学预印本", "医学预印本"],
                      _search_biorxiv, "bioRxiv/medRxiv preprints"),
    SpecializedEngine("Springer Nature", ["springer", "nature", "springer nature", "施普林格"],
                      _search_springer, "Springer Nature journal articles"),
    SpecializedEngine("IEEE Xplore", ["ieee xplore", "ieee论文", "ieee transactions"],
                      _search_ieee_xplore, "IEEE engineering and medical imaging papers"),
    SpecializedEngine("Europe PMC", ["europepmc", "欧洲pmc", "europe pubmed"],
                      _search_europepmc, "European PubMed Central — open access biomedical literature"),
    SpecializedEngine("Lens.org", ["lens.org", "scholarly search", "学术搜索"],
                      _search_lens, "Lens.org — scholarly patents and literature"),
    SpecializedEngine("MeSH", ["mesh", "医学主题词", "medical subject heading"],
                      _search_mesh, "Medical Subject Headings (NCBI controlled vocabulary)"),
    SpecializedEngine("AAPM Reports", ["aapm", "tg-43", "tg-186", "tg-229", "medical physics report"],
                      _search_aapm, "AAPM task group reports and guidelines"),
    SpecializedEngine("IOP Physics Med Biol", ["physics in medicine", "phys med biol", "物理学与医学"],
                      _search_iop, "IOP Publishing — Physics in Medicine & Biology"),

    # Patents
    SpecializedEngine("Google Patents", ["专利", "patent", "发明专利", "实用新型"],
                      _search_google_patents, "Google Patents search"),
    SpecializedEngine("CNIPA", ["cnipa", "中国专利", "国家知识产权局"],
                      _search_cnipa, "China National Intellectual Property Administration"),

    # Chinese academic
    SpecializedEngine("CNKI", ["cnki", "知网", "中国知网", "中文文献"],
                      _search_cnki, "China National Knowledge Infrastructure"),
    SpecializedEngine("Wanfang", ["万方", "wanfang", "万方数据"],
                      _search_wanfang, "Wanfang Chinese academic database"),

    # Technical
    SpecializedEngine("Stack Overflow", ["stackoverflow", "编程", "programming", "代码问题"],
                      _search_stackoverflow, "Programming Q&A via Stack Overflow API"),
    SpecializedEngine("Papers With Code", ["代码实现", "implementation", "papers with code", "benchmark"],
                      _search_papers_with_code, "ML papers with code implementations"),
    SpecializedEngine("GitHub", ["github", "代码库", "repository", "开源项目"],
                      _search_github_repos, "GitHub repository search",
                      optimize_fn=_optimize_github),
]


# ============================================================
# Search Engines
# ============================================================

class SearchEngine:
    """Base class for search engines."""

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        """Search and return list of {title, snippet, url, source}."""
        raise NotImplementedError

    def search_with_retry(self, query: str, max_results: int = 5, retries: int = 2, delay: float = 1.0) -> List[Dict]:
        """Search with retry on failure."""
        import time
        for attempt in range(retries + 1):
            try:
                results = self.search(query, max_results)
                if results:
                    return results
            except Exception as e:
                logger.warning(f"Search attempt {attempt+1}/{retries+1} failed: {e}")
            if attempt < retries:
                time.sleep(delay * (attempt + 1))  # Exponential backoff
        return []


class BingSearch(SearchEngine):
    """Bing search (API or cn.bing.com scraping)."""

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        results = []
        api_key = os.environ.get("BING_SEARCH_API_KEY")

        if api_key:
            return self._search_api(query, max_results, api_key)
        return self._search_scrape(query, max_results)

    def _search_api(self, query: str, max_results: int, api_key: str) -> List[Dict]:
        try:
            resp = requests.get(
                "https://api.bing.microsoft.com/v7.0/search",
                headers={"Ocp-Apim-Subscription-Key": api_key},
                params={"q": query, "count": max_results, "mkt": "en-US"},
                timeout=5,
            )
            if resp.status_code == 200:
                for item in resp.json().get("webPages", {}).get("value", [])[:max_results]:
                    return [{
                        "title": item.get("name", ""),
                        "snippet": item.get("snippet", ""),
                        "url": item.get("url", ""),
                        "source": "Bing API",
                    }]
        except Exception as e:
            logger.warning(f"Bing API error: {e}")
        return []

    def _search_scrape(self, query: str, max_results: int) -> List[Dict]:
        results = []
        try:
            url = f"https://cn.bing.com/search?q={quote_plus(query)}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return results

            text = resp.text
            # Multiple patterns for result blocks (Bing HTML varies)
            blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', text, re.DOTALL)
            if not blocks:
                blocks = re.findall(r'<div class="b_algo"[^>]*>(.*?)</div>\s*</div>', text, re.DOTALL)

            for block in blocks[:max_results]:
                # Extract title
                title_m = re.search(r'<h2[^>]*>(.*?)</h2>', block, re.DOTALL)
                if not title_m:
                    continue
                title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()

                # Extract URL
                url_m = re.search(r'<a[^>]*href="(https?://[^"]*)"', block)
                result_url = url_m.group(1) if url_m else ""

                # Extract snippet — multiple patterns
                snippet = ""
                for pattern in [
                    r'<p[^>]*>(.*?)</p>',
                    r'<div class="b_caption"[^>]*>(.*?)</div>',
                    r'<span class="c_.*?">(.*?)</span>',
                ]:
                    snippet_m = re.search(pattern, block, re.DOTALL)
                    if snippet_m:
                        snippet = re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip()
                        if snippet and len(snippet) > 20:
                            break

                # Fallback: extract all text from block
                if not snippet:
                    snippet = re.sub(r'<[^>]+>', ' ', block)
                    snippet = re.sub(r'\s+', ' ', snippet).strip()[:200]

                if title:
                    results.append({
                        "title": title[:200],
                        "snippet": snippet[:300],
                        "url": result_url,
                        "source": "Bing",
                    })
        except Exception as e:
            logger.warning(f"Bing scrape error: {e}")
        return results


class SogouSearch(SearchEngine):
    """Sogou search (www.sogou.com) — good for Chinese queries."""

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        results = []
        try:
            url = f"https://www.sogou.com/web?query={quote_plus(query)}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return results

            text = resp.text
            # Extract from <div class="vrwrap"> or <div class="rb">
            blocks = re.findall(r'<h3[^>]*>(.*?)</h3>', text, re.DOTALL)
            snippets = re.findall(r'<p[^>]*class="[^"]*str[^"]*"[^>]*>(.*?)</p>', text, re.DOTALL)

            for i, title_html in enumerate(blocks[:max_results]):
                title = re.sub(r'<[^>]+>', '', title_html).strip()
                snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
                if title and len(title) > 5:
                    results.append({
                        "title": title[:200],
                        "snippet": snippet[:300],
                        "url": "",
                        "source": "Sogou",
                    })
        except Exception as e:
            logger.warning(f"Sogou search error: {e}")
        return results


class PubMedSearch(SearchEngine):
    """PubMed search for clinical literature."""

    def search(self, query: str, max_results: int = 3) -> List[Dict]:
        results = []
        try:
            # Search PubMed
            search_resp = requests.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={"db": "pubmed", "term": query, "retmax": max_results, "retmode": "json"},
                timeout=10,
            )
            if search_resp.status_code != 200:
                return results

            ids = search_resp.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return results

            # Fetch abstracts
            fetch_resp = requests.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
                timeout=10,
            )
            if fetch_resp.status_code == 200:
                for uid in ids:
                    article = fetch_resp.json().get("result", {}).get(uid, {})
                    if article:
                        title = article.get("title", "")
                        authors = ", ".join(a.get("name", "") for a in article.get("authors", [])[:3])
                        source = article.get("fulljournalname", article.get("source", ""))
                        pub_date = article.get("pubdate", "")
                        results.append({
                            "title": title[:200],
                            "snippet": f"{authors}. {source}. {pub_date}".strip(),
                            "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                            "source": "PubMed",
                        })
        except Exception as e:
            logger.warning(f"PubMed search error: {e}")
        return results


class GitHubSearch(SearchEngine):
    """GitHub search for code and repositories."""

    def search(self, query: str, max_results: int = 5, search_type: str = "repositories") -> List[Dict]:
        results = []
        try:
            url = f"https://api.github.com/search/{search_type}"
            headers = {"Accept": "application/vnd.github.v3+json"}
            token = os.environ.get("GITHUB_TOKEN")
            if token:
                headers["Authorization"] = f"token {token}"

            resp = requests.get(url, headers=headers, params={"q": query, "per_page": max_results}, timeout=10)
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                for item in items[:max_results]:
                    if search_type == "repositories":
                        results.append({
                            "title": item.get("full_name", ""),
                            "snippet": (item.get("description") or "")[:200],
                            "url": item.get("html_url", ""),
                            "source": "GitHub",
                        })
                    else:
                        results.append({
                            "title": item.get("name", ""),
                            "snippet": (item.get("description") or item.get("path", ""))[:200],
                            "url": item.get("html_url", ""),
                            "source": "GitHub",
                        })
        except Exception as e:
            logger.warning(f"GitHub search error: {e}")
        return results


# ============================================================
# Result Validator
# ============================================================

class ResultValidator:
    """Multi-signal result validation and scoring.

    Scoring combines:
    1. Keyword matching (with cross-language support)
    2. Source quality weighting
    3. Content richness signals
    4. N-gram matching for phrase-level relevance
    """

    STOP_WORDS = frozenset({
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'shall', 'can', 'of', 'in', 'on', 'at',
        'to', 'for', 'with', 'by', 'from', 'as', 'into', 'through', 'during',
        'before', 'after', 'above', 'below', 'between', 'out', 'off', 'over',
        'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when',
        'where', 'why', 'how', 'all', 'each', 'every', 'both', 'few', 'more',
        'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own',
        'same', 'so', 'than', 'too', 'very', 'just', 'about', 'what', 'which',
        'who', 'whom', 'this', 'that', 'these', 'those', 'i', 'me', 'my',
        'we', 'our', 'you', 'your', 'he', 'him', 'his', 'she', 'her', 'it',
        'its', 'they', 'them', 'their', 'and', 'or', 'but', 'if', 'while',
        '最新', '查询', '搜索', '查',
    })

    # Cross-language term mapping
    CROSS_LANG = {
        'impact factor': '影响因子',
        'ranking': '排名',
        'journal': '期刊',
        'publication': '论文',
        'guideline': '指南',
        'dose': '剂量',
        'treatment': '治疗',
        'weather': '天气',
        'temperature': '温度',
        'diagnosis': '诊断',
        'algorithm': '算法',
        'medical image analysis': '医学图像分析',
    }

    # Source quality weights (higher = more trustworthy)
    SOURCE_WEIGHTS = {
        'PubMed': 1.0,
        'GitHub': 0.8,
        'Bing': 0.6,
        'Sogou': 0.6,
        'Baidu': 0.5,
    }

    @staticmethod
    def _extract_key_terms(query: str) -> List[str]:
        """Extract meaningful terms from query, removing noise."""
        terms = re.findall(r'[\w一-鿿]+', query.lower())
        key = []
        for t in terms:
            if t in ResultValidator.STOP_WORDS or len(t) <= 1:
                continue
            if re.match(r'^20\d{2}$', t):  # Skip years
                continue
            key.append(t)
        return key

    @staticmethod
    def _build_search_terms(query: str, key_terms: List[str]) -> set:
        """Build expanded term set with cross-language and n-gram support."""
        search = set(key_terms)

        # Add cross-language equivalents
        q_lower = query.lower()
        for en_term, zh_term in ResultValidator.CROSS_LANG.items():
            if any(t in q_lower for t in en_term.split()):
                search.add(zh_term)
            if zh_term in query:
                search.update(en_term.split())

        # Add bigrams for phrase matching
        for i in range(len(key_terms) - 1):
            search.add(f"{key_terms[i]} {key_terms[i+1]}")

        return search

    @staticmethod
    def score_relevance(query: str, results: List[Dict]) -> float:
        """Score how relevant results are to the query (0-1).

        Multi-signal approach:
        - Keyword match ratio (primary signal)
        - Cross-language matching
        - N-gram phrase matching
        - Source quality weighting
        """
        if not results:
            return 0.0

        key_terms = ResultValidator._extract_key_terms(query)
        if not key_terms:
            return 0.5

        search_terms = ResultValidator._build_search_terms(query, key_terms)

        # Score each result and take the best
        best_score = 0.0
        for r in results:
            text = f"{r.get('title', '')} {r.get('snippet', '')} {r.get('page_content', '')}".lower()

            # Count matched terms
            matched = sum(1 for t in search_terms if t in text)

            # Keyword match ratio (capped at 1.0)
            keyword_score = min(1.0, matched / len(key_terms))

            # Source quality bonus
            source = r.get('source', '')
            source_weight = ResultValidator.SOURCE_WEIGHTS.get(source, 0.5)

            # Content richness bonus (longer snippets = more informative)
            snippet_len = len(r.get('snippet', ''))
            has_page_content = bool(r.get('page_content', ''))
            richness = min(1.0, snippet_len / 100) * 0.3
            if has_page_content:
                richness += 0.2

            # Combined score: keyword match is primary, source and richness are modifiers
            score = keyword_score * 0.7 + source_weight * 0.15 + richness * 0.15
            best_score = max(best_score, score)

        return min(1.0, best_score)

    @staticmethod
    def deduplicate(results: List[Dict]) -> List[Dict]:
        """Remove duplicate results based on title similarity."""
        seen = set()
        unique = []
        for r in results:
            title_key = re.sub(r'\W+', '', r.get('title', '').lower())[:50]
            if title_key and title_key not in seen:
                seen.add(title_key)
                unique.append(r)
        return unique

    @staticmethod
    def get_quality_label(score: float) -> str:
        """Convert relevance score to quality label."""
        if score >= 0.5:
            return "good"
        elif score >= 0.2:
            return "partial"
        return "poor"


# ============================================================
# Search Cache
# ============================================================

class SearchCache:
    """Simple file-based cache with TTL."""

    CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
    TTL_HOURS = 24  # Cache expires after 24 hours

    def __init__(self):
        os.makedirs(self.CACHE_DIR, exist_ok=True)

    def _key(self, query: str) -> str:
        return hashlib.md5(query.lower().strip().encode()).hexdigest()

    def get(self, query: str) -> Optional[Dict]:
        """Get cached result if not expired."""
        path = os.path.join(self.CACHE_DIR, f"{self._key(query)}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Check TTL
            cached_at = data.get('_cached_at', 0)
            if time.time() - cached_at > self.TTL_HOURS * 3600:
                os.remove(path)  # Expired
                return None
            return data
        except Exception:
            return None

    def set(self, query: str, data: Dict):
        """Cache search results."""
        path = os.path.join(self.CACHE_DIR, f"{self._key(query)}.json")
        data['_cached_at'] = time.time()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Cache write error: {e}")


# ============================================================
# Main Search Tool
# ============================================================

class WebSearchTool(BaseTool):
    """Multi-engine web search with intelligent query processing and result validation."""

    name = "web_search"
    description = "Search the web for information. Supports clinical literature (PubMed), general web search (Bing, Sogou), and code search (GitHub)."
    input_schema = {
        "query": {"type": "string", "description": "Search query"},
        "search_type": {"type": "string", "enum": ["general", "clinical", "github_repos", "github_code"], "default": "general"},
        "max_results": {"type": "integer", "default": 5},
    }

    def __init__(self):
        self.engines = {
            'bing': BingSearch(),
            'sogou': SogouSearch(),
            'pubmed': PubMedSearch(),
            'github': GitHubSearch(),
        }
        self.cache = SearchCache()
        self.validator = ResultValidator()
        self.processor = QueryProcessor()

    def _execute(self, **kwargs) -> ToolResult:
        query = kwargs.get("query", "").strip()
        search_type = kwargs.get("search_type", "general")
        max_results = kwargs.get("max_results", 5)

        if not query:
            return ToolResult(success=False, message="No search query provided")

        # Check cache first
        cache_key = f"{search_type}:{query}"
        cached = self.cache.get(cache_key)
        if cached:
            logger.info(f"Cache hit for: {query[:50]}")
            return ToolResult(success=True, data=cached, message=f"Found {len(cached.get('results', []))} results (cached)")

        # Route to appropriate search strategy
        if search_type == "clinical":
            results = self._search_clinical(query, max_results)
        elif search_type.startswith("github"):
            results = self._search_github(query, max_results, search_type)
        else:
            results = self._search_general(query, max_results)

        # Deduplicate
        results = self.validator.deduplicate(results)

        # Always fetch page content from top results (not just when relevance is low)
        # The LLM will judge relevance semantically — we just need to give it enough data
        if results:
            fetched = 0
            for r in results[:3]:
                if fetched >= 2:
                    break
                url = r.get("url", "")
                if not url or not url.startswith("http"):
                    continue
                if any(skip in url for skip in ["bing.com", "baidu.com", "google.com", "so.com"]):
                    continue
                try:
                    from tool_factory.web_fetch import WebFetchTool
                    fetch_tool = WebFetchTool()
                    page = fetch_tool.execute(url=url, extract_text=True, max_length=3000)
                    if page.success and page.data:
                        page_text = page.data.get("text", "") or page.data.get("content", "")
                        if page_text and len(page_text) > 100:
                            r["page_content"] = page_text[:2000]
                            fetched += 1
                            logger.info(f"Fetched {len(page_text)} chars from {url[:60]}")
                except Exception as e:
                    logger.warning(f"Failed to fetch {url[:60]}: {e}")

        # Score relevance (after fetching page content)
        relevance = self.validator.score_relevance(query, results)
        quality = self.validator.get_quality_label(relevance)

        # Handle no results explicitly
        if not results:
            return ToolResult(
                success=False,
                message=f"Search failed: no results found for '{query}'. Network may be unavailable.",
                data={"results": [], "quality": "failed", "sources": []},
                metadata={"quality": "failed", "relevance_score": 0},
            )

        # Build response
        response = {
            "success": True,
            "results": results,
            "quality": quality,
            "relevance_score": round(relevance, 2),
            "sources": [r.get("url", "") for r in results if r.get("url")],
        }

        if quality == "poor":
            response["quality_warning"] = (
                "Search results may not contain the requested information. "
                "The LLM should use page_content if available, or honestly say the search failed."
            )

        # Cache the results
        self.cache.set(cache_key, response)

        # Build message
        msg = f"Found {len(results)} results"
        if quality == "poor":
            msg += " (low relevance - results may not answer the question)"
        elif quality == "partial":
            msg += " (partial match)"

        return ToolResult(
            success=True,
            data=response,
            message=msg,
            metadata={"quality": quality, "relevance_score": relevance},
        )

    def _search_weather(self, query: str) -> List[Dict]:
        """Direct weather API query using wttr.in — returns structured weather data."""
        # This method is kept for backward compatibility but delegates to standalone function
        return _search_weather(query)

        try:
            resp = requests.get(f"https://wttr.in/{city}?format=j1", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                current = data.get("current_condition", [{}])[0]
                temp = current.get("temp_C", "?")
                weather_desc = current.get("weatherDesc", [{}])[0].get("value", "")
                humidity = current.get("humidity", "?")
                wind = current.get("windspeedKmph", "?")
                feels_like = current.get("FeelsLikeC", "?")

                snippet = f"{city}: {temp}°C, {weather_desc}, Humidity: {humidity}%, Wind: {wind} km/h, Feels like: {feels_like}°C"
                return [{
                    "title": f"{city} Weather Today",
                    "snippet": snippet,
                    "url": f"https://wttr.in/{city}",
                    "source": "wttr.in",
                    "page_content": snippet,
                }]
        except Exception as e:
            logger.warning(f"Weather API error: {e}")
        return []

    def _search_general(self, query: str, max_results: int) -> List[Dict]:
        """General web search with specialized engine priority and multi-engine fallback."""
        intent = self.processor.detect_intent(query)
        variants = self.processor.generate_variants(query)
        logger.info(f"Search intent: {intent}, variants: {len(variants)}")

        # Check specialized engines first (direct API access, most reliable)
        specialized_results = []
        for engine in SPECIALIZED_ENGINES:
            if engine.matches(query):
                logger.info(f"Trying specialized engine: {engine.name}")
                results = engine.search(query, max_results)
                if results:
                    score = self.validator.score_relevance(query, results)
                    logger.info(f"Specialized engine {engine.name}: {len(results)} results, score {score:.2f}")
                    if score >= 0.5:
                        return results  # Good enough, use directly
                    specialized_results = results  # Save as fallback
                break  # Only try the first matching engine

        all_results = []
        best_score = 0.0
        best_results = []

        # Try each variant with Bing, use the best result set
        for variant in variants[:4]:  # Max 4 variants
            results = self.engines['bing'].search_with_retry(variant, max_results, retries=2)
            if results:
                score = self.validator.score_relevance(query, results)
                logger.info(f"Variant '{variant[:50]}' -> {len(results)} results, score {score:.2f}")
                all_results.extend(results)
                if score > best_score:
                    best_score = score
                    best_results = results
                if score >= 0.8:
                    break  # Very good, stop early

        # If Bing results are poor, try Sogou (better for Chinese queries)
        if best_score < 0.5:
            for variant in variants[:2]:
                sogou_results = self.engines['sogou'].search_with_retry(variant, max_results, retries=2)
                if sogou_results:
                    score = self.validator.score_relevance(query, sogou_results)
                    if score > best_score:
                        best_score = score
                        best_results = sogou_results
                    if score >= 0.5:
                        break

        # If still poor and query looks clinical, try PubMed
        if best_score < 0.3 and intent == 'research':
            pubmed_results = self.engines['pubmed'].search_with_retry(query, max_results, retries=2)
            if pubmed_results:
                all_results.extend(pubmed_results)

        # Merge specialized results with general results for richer data
        if specialized_results and best_results:
            # Combine: specialized results first (authoritative), then general
            combined = specialized_results + best_results
            return self.validator.deduplicate(combined)[:max_results]

        # Fall back: best general results, then specialized, then all
        if best_results:
            return best_results[:max_results]
        if specialized_results:
            return specialized_results[:max_results]
        return all_results[:max_results]

    def _search_clinical(self, query: str, max_results: int) -> List[Dict]:
        """Clinical search: PubMed first, then Bing for broader context."""
        results = self.engines['pubmed'].search(query, max_results)
        if len(results) < max_results:
            bing_results = self.engines['bing'].search(query, max_results - len(results))
            results.extend(bing_results)
        return results

    def _search_github(self, query: str, max_results: int, search_type: str) -> List[Dict]:
        """GitHub search for code/repos."""
        gh_type = "code" if "code" in search_type else "repositories"
        return self.engines['github'].search(query, max_results, gh_type)


# ============================================================
# Legacy compatibility
# ============================================================

def search_web(query: str, search_type: str = "general", max_results: int = 5) -> Dict:
    """Convenience function for backward compatibility."""
    tool = WebSearchTool()
    result = tool.execute(query=query, search_type=search_type, max_results=max_results)
    return result.data if result.success else {"success": False, "error": result.error}
