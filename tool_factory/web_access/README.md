# Web Access Integration Guide

## Overview

BrachyBot's web access capability is inspired by three leading projects:

| Project | Stars | Key Innovation |
|---------|-------|----------------|
| [Agent-Reach](https://github.com/Panniantong/Agent-Reach) | 20k+ | Multi-platform access (17 platforms), zero API fees |
| [web-access](https://github.com/eze-is/web-access) | 7k+ | CDP browser automation, site experience accumulation |
| [bb-browser](https://github.com/epiral/bb-browser) | 5k+ | Real browser integration, login state preservation |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    BrachyBot Web Access                      │
├─────────────────────────────────────────────────────────────┤
│  web_search    │  Search engines (PubMed, GitHub, Bing)     │
│  web_fetch     │  Direct URL fetching (HTML → text)         │
│  Evidence Chain│  Source tracking and verification           │
└─────────────────────────────────────────────────────────────┘
```

## Search Sources

| Source | Status | Use Case |
|--------|--------|----------|
| PubMed | ✅ Working | Medical literature, clinical trials |
| GitHub API | ✅ Working | Code repositories, technical topics |
| Bing CN | ⚠️ Limited | General web search |
| DuckDuckGo | ❌ Blocked | N/A from this network |
| Jina Reader | ❌ Blocked | N/A from this network |

## Key Learnings from Reference Projects

### From Agent-Reach
1. **Multi-platform support**: Don't just search - read specific platforms
2. **Zero API fees**: Use free APIs and scraping where possible
3. **CLI-first design**: Tools should be callable from command line

### From web-access
1. **CDP Browser**: Real browser integration for authenticated sites
2. **Site experience**: Accumulate knowledge about how to access specific sites
3. **Parallel execution**: Search multiple sources concurrently

### From bb-browser
1. **Real browser state**: Use user's existing login sessions
2. **Adapter pattern**: Each site has its own adapter
3. **Eval-based**: Execute code in browser context

## Limitations in Current Network

Due to network restrictions, the following services are NOT accessible:
- DuckDuckGo (search engine)
- Jina Reader (web page reader)
- Wikipedia API
- Most general web APIs

**Working services:**
- PubMed E-utilities API
- GitHub API
- Some Chinese services (Baidu, Bing CN)

## Recommendations

1. **For medical queries**: Use PubMed (reliable, authoritative)
2. **For technical queries**: Use GitHub API (code, repositories)
3. **For general queries**: Use Bing CN or Baidu (if accessible)
4. **For specific URLs**: Use web_fetch (direct access)

## Future Improvements

When network restrictions are lifted:
1. Add Jina Reader support for better web page reading
2. Add DuckDuckGo as fallback search engine
3. Add Exa search for semantic web search
4. Consider CDP browser integration for authenticated sites
