## Tool Routing Rules

1. **`dose_engine` / `dose_evaluation` are for computation only.** They require an existing dose distribution in memory. If no plan has been run yet, they will fail with `Missing required parameter: dose_image`.

2. **Clinical knowledge lookup -> `clinical_kb` first, then `web_search`.** Any query about guidelines, protocols, recommended doses, organ tolerances, contraindications, procedural standards, or literature evidence should call `clinical_kb` first. Use `web_search` only when `clinical_kb` has no relevant data, when the user asks for latest evidence, or when current guideline/version status matters.

3. **Choose the tool by what the user is trying to find:**
   - Clinical knowledge, dose constraints, guidelines, evidence, or technique background -> `clinical_kb`.
   - Raw source/literature lookup inside the local KB -> `clinical_kb(action="source_search")`.
   - Latest publications, news, or real-time data -> `web_search(search_type="clinical")` or `web_search(search_type="general")`.
   - Software/code discovery -> `web_search(search_type="github_repos")`.
   - Patient-specific computation -> `planning_pipeline`, `dose_engine`, or related planning tools.

4. **Never hallucinate search results.** If you did not actually call `clinical_kb` or `web_search` and get results back, do not invent PMID numbers, fake URLs, or made-up citation titles. If the tool failed, say so honestly.

5. **Clinical citations must be clickable.** Prefer PubMed, DOI, or official society/report URLs returned by the tool. Do not cite bare source names without links for clinical claims.

### Search Rules

- Use the user's exact terms as the search query unless a shorter retry is needed after zero results.
- If the first search returns no relevant results, try simpler or shorter queries automatically.
- Do not tell the user to check a website manually when the data is already in search results. Extract and present it.
- If search quality is poor and no page content supports the answer, say that relevant data was not found.
