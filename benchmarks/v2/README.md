# BrachyBot Benchmark v2

**Focus: System capabilities, not knowledge recall.**

## Design Principles

1. **Test what matters**: Tool calling accuracy, multi-step execution, UI control, language consistency
2. **Not knowledge trivia**: Removed pure knowledge questions any LLM can answer
3. **Real scenarios**: Based on actual clinical workflows
4. **Measurable**: `expected_tools`, `forbidden_keywords`, `language` — not just keyword matching

## Categories (8, 136 cases total)

| Category | Cases | What it tests |
|----------|-------|---------------|
| `01_tool_calling` | 30 | Correct tool selection for each request |
| `02_multi_step` | 15 | All steps executed in correct order |
| `03_hallucination` | 15 | No fabricated results, honest about uncertainty |
| `04_language` | 15 | Input/output language consistency |
| `05_context` | 31 | Multi-turn context retention |
| `06_response_quality` | 10 | Structured output, no filler phrases |
| `07_safety` | 10 | Refuse unsafe requests, cite guidelines |
| `08_error_recovery` | 10 | Graceful error handling |

## Evaluation

- **Tool calling**: Check `expected_tools` and `forbidden_tools`
- **Language**: Check `language` field matches output
- **Hallucination**: Check `forbidden_keywords` not present
- **Multi-turn**: Check context across turns
- **Quality**: Check for table format, section headers, no transitional phrases

## What was removed from v1

- 1200+ pure knowledge questions (prescription doses, organ tolerances, etc.)
- Duplicate test cases across categories
- Tests that any LLM can pass without BrachyBot's tools
- English-only tests (v2 has Chinese + English)
