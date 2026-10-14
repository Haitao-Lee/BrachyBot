# Case resource recovery and planning-reference UI — 2026-10-14

## Scope and confirmed causes

The LAN and public deployments remain separate: no account, cookie, key,
runtime directory, case storage or unrelated product changes are copied.
Clinical algorithms and user-reviewed geometry are not substituted or reset.

An isolated actual-case copy reproduced an endless recovery loop: 592 unique
array sidecars mapped about 2.75 GiB, exceeding the old 2 GiB cache accounting.
A successful decoded result was immediately evicted; the next poll started
over. The initial page retained CT but never reached full visual readiness.

Additional inspected/tested causes:

- Nested JSON was restored recursively again at every ancestor, and complete
  DVH/Planning histories were repeatedly deep-copied for small resource reads.
- The external font stylesheet blocked local script execution when the font
  host was unreachable. A private full-page navigation timed out at 120 s.
- Final presentation reconciliation could race late mesh/guide completion;
  an empty legacy image catalog was incorrectly interpreted as explicit hiding.
- A failed dose request cleared a valid projection before replacement arrived.
- Same-owner guide loads superseded each other through one generation counter.
- Obsolete spinner callbacks touched the elapsed clock before ownership checks.
- Shared context-indicator polling constructed clinical hydration runtimes.

## Implemented behavior

1. Read-only memory mappings are charged as wrapper/heap allocations, not their
   complete virtual byte length. Cache entry/pending-worker limits remain; one
   oversized heap handoff is retained instead of self-evicting forever. Native
   SimpleITK buffers are explicitly charged using a zero-copy array view.
2. A decode error is returned consistently rather than disappearing into a new
   202 loop. Failed handoffs expire after five seconds to permit repaired-file
   retries; a changed clinical/lifecycle revision has a distinct cache identity.
3. JSON/array decoding is one pass. Verified manifest bytes are cached with
   owner, Session, timepoint, path, checksum and file identity; cache capacity
   is eight manifests / 128 MiB. Every consumer gets fresh mutable containers.
4. HTTP resource views avoid copying shared chat/attachment history, and warm
   views use already-completed hydration instead of constructing and replacing
   an intermediate clinical history. Mutable per-request containers and
   read-only arrays preserve isolation. Shared conversational controls remain
   on the authenticated Session Agent.
5. The optional font stylesheet uses non-blocking print-media/onload activation.
   The system-font fallback leaves clinical resources usable without that host.
6. Saved presentation is reconciled after all registered visual producers.
   Intentional image hiding happens after that merge; an empty legacy catalog
   does not hide restored CT. Scope changes cancel the final handoff.
7. Dose replacement is transactional: transport failures retain the current
   valid projection; confirmed absent/stale dose clears it. Failed transport
   does not authorize saving a partial workspace as restored.
8. Same-owner guide requests share one in-flight task; explicit invalidation
   clears that registry. The final guide check is read-only and never generates
   a new guide. An expected guide failure is reported as partial readiness.
9. The shared spinner includes observations, selected dose and the final
   revision receipt, and rejects stale Session/timepoint/generation callbacks
   before changing timers/messages/animations.
10. Planning reference identifies the image and physical frame used by clinical
    planning, independently of the currently displayed image. The Data Tree
    now shows a muted inline “参考 / Ref” with an explanatory bilingual tooltip;
    the image context menu and Input selection retain the actual reference
    control. The redundant under-slider badge is removed.
11. Complete-workspace import preserves truncated UTF-16 code units from older
    browser presentation text as JSON escapes, without changing canonical bytes
    for valid Unicode or invalidating scientific journal hashes. A formerly
    failing exported software workspace now imports successfully. A historical
    guide explicitly mismatched to the current plan is retained as stale, not
    promoted to current use and not treated as a failed current mesh load.

## Storage policy

There is no separate per-Session byte limit in this implementation: uploaded
and generated resources consume the owner's quota. The default is raised
from 40 GiB to 160 GiB, including existing accounts with the exact old default
when no explicit environment override is configured. Custom administrator
quotas and explicit `BRACHYBOT_USER_STORAGE_QUOTA_BYTES` policies are retained.
Disk-free protections and independent upload-size guards are not removed.
This is storage capacity, not permission to eagerly load all data into RAM.

Deployment verification found a public bootstrap configuration explicitly
holding the old 40 GiB policy. Under this requested storage expansion, only
`BRACHYBOT_USER_STORAGE_QUOTA_BYTES` was administratively changed to 160 GiB,
and the three old-default public accounts were migrated separately. The full
configuration and old quotas have restricted pre-change backups; all other
configuration values and custom quotas were retained. LAN's 24 old-default
accounts migrated at startup. Both live deployments now report 160 GiB.

## Verification record

- Real file-backed array cache, revision separation, missing-sidecar error and
  repair retry, detached manifest/checksum, nested label/tuple decoding,
  resource projection and quota migration tests are in
  `tests/test_resource_recovery_20261014.py`.
- Executed product frontend boundaries are in `tests/resource-recovery.test.cjs`:
  empty legacy catalog, intentional hide after final merge, cancelled late
  merge, dose failure/confirmed absence, stale spinner clock, optional fonts
  and duplicate guide single-flight. These are software contracts, not clinical
  model or WebGL acceptance substitutes.
- Actual-case full-page restore and a subsequent stability interval use the
  isolated copied case; no production case is modified by that acceptance run.
- Full-suite results, public merge results, final actual-case timing and live
  deployment hashes will be appended after verification, not inferred from
  earlier test passes.

Missing/corrupt source artifacts cannot be recreated from UI state alone.
Failures remain explicit and retryable without overwriting intact saved
presentation. This work does not claim clinical validation of restored plans.

## Final candidate evidence

- Final complete LAN regression: **4549 passed, 5 skipped, 34 warnings,
  4 subtests passed, zero failures** (800.80 s). The warnings are the existing
  SWIG/datetime deprecations; skipped tests are not counted as validation.
- Executed full-page two-timepoint upload, switch, cold restore, complete ZIP
  import, guide registration/review/reload/rejection, and recovery/bundle tests:
  **17 passed, 3 skipped** (175.60 s). The three supplied-model browser tests
  require an explicit demo input and were not executed in this run.
- Independent public candidate boundary/store/frontend subset: **271 passed,
  11 failed**. The untouched public checkout's paired baseline had exactly the
  same 11 stale static/source-contract failures (**260 passed, 11 failed**).
  There are zero newly introduced failures in that comparison; this is not a
  claim that the public suite is fully green or that its stale tests are fixed.
- Final revised real-case copy: 592 mapped sidecars / approximately 2.75 GiB;
  **118 3D objects, 61 visible objects, 291 Data Tree nodes, CT visible,
  resource ready, spinner hidden, no JavaScript or server-5xx errors**. Readiness
  was reached 332.881 s after the first browser sample during concurrent full
  regression; the following 10.006 s remained stable. This is correctness and
  a loaded-system cold-start observation, not an isolated speed benchmark.
- Before the fix, that copy never reached readiness in the 185 s observation
  and repeatedly restarted hydration. The invalid self-eviction loop is removed.
- A profiled warm owned `/api/planning/seeds_3d` read now completes in 1.681 s
  versus 3.659 s in the earlier intermediate candidate. This compares the same
  isolated case and profiler, not the entire page or an idle production SLA.
- Final full-suite and deployed listener/asset/quota receipts are recorded in
  `VERIFICATION_20261014.json`; deployment writes are checksum-fenced against
  concurrent edits and have pre-install backups. No production case data is
  used as a writable test fixture.

## Installed deployments

The formal LAN `/home/lht/snap/brachyplan/BrachyBot` and independent public
`/home/lht/snap/brachyplan/BrachyBot-release` each received 20 checked files:
15 product files, four test files and this record. Per-deployment product delta
is 284 inserted / 74 removed lines for this recovery patch only; it is not a
claim about cumulative earlier work. Both listeners were gracefully reloaded
with their own launch environment, without forced termination. Live health,
listener working directories, all 20 installed hashes, five served JS assets
and anonymous clinical-configuration rejection were checked. The restricted
pre-install backup is `/home/lht/snap/brachyplan/backups/resource-recovery-20261014-183207`.
