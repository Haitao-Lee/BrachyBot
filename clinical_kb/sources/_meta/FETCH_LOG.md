# Fetch Log — Brachytherapy Clinical Knowledge Base

**Date:** 2026-06-17

## Summary

All sources fetched via PubMed API (eutils) and direct PubMed page scraping (curl).

## Fetch Statistics

| Status | Count |
|--------|-------|
| Fetched (full abstract) | ~65 |
| Partial (short abstract) | ~5 |
| Metadata only (no PMID) | ~17 |
| **Total** | **87** |

## Methods Used

1. **curl + PubMed HTML**: Primary method for PMID-based sources
2. **NCBI eutils API**: Used for PMID search and XML extraction
3. **Manual metadata**: Used for NCCN, ICRU, IAEA, Chinese sources (no free full text available)

## Blocked Domains

| Domain | Status | Notes |
|--------|--------|-------|
| doi.org | blocked | WebFetch tool restriction |
| sciencedirect.com | blocked | WebFetch tool restriction |
| thelancet.com | blocked | WebFetch tool restriction |
| brachyjournal.com | blocked | WebFetch tool restriction |
| nccn.org | blocked | WebFetch tool restriction (PDF downloads) |
| europepmc.org | accessible via curl | Used for supplementary data |

## Notes

- All PubMed abstracts were successfully extracted
- NCCN guidelines require free registration for PDF download — only metadata recorded
- ICRU/IAEA reports are not freely available online — metadata recorded
- Chinese sources (CSTRO/CSCO) require Chinese language access — metadata recorded

## Rebuild 2026-06-17

- Wiped contaminated guidelines_brachytherapy.md (had subjective model commentary)
- Wiped sources/01-08/raw/ and re-migrated from tmp/brachy_kb_crawl/
- Excluded 4 polluted files (verified by reading content, not filename):
  - 01_gynecologic/raw/portec-3-lancet-oncol-2018.md
  - 04_head_neck_skin/raw/eortc-postop-sbrt-oropharyngeal-2024.md
  - 06_other_sites/raw/acr-asnr-practice-parameter-2025.md
  - 07_physics/raw/aapm-tg-100-fmea.md
- Final: 110 verified real .md/.txt source files in sources/01-08/raw/
- Regenerated 8 INDEX.md + _meta/MANIFEST.csv + _meta/SOURCES_BY_CATEGORY.md
