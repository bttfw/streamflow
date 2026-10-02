# Dev reliability and efficiency work - 2026-10-02

Status: draft validation. Targeted backend regressions, isolated integration
contracts, frontend tests, and the frontend production build have passed. The
complete stable backend suite and live validation of the new image are pending.

Base: `ccab14e7f61a12ba4fa1375e7db8472757c941bd` (`upstream/dev`).

## Compatibility

- Changes are contained in StreamFlow and use existing Teamarr/Dispatcharr APIs.
- Regex matching behavior and priorities are preserved.
- Specialized checks retain their existing maximum of 25 entries per drain.
- Media measurement reuse remains unchanged.

## Implementation ledger

| # | Change | Implementation status |
|---|---|---|
| 1 | Preflight cadence and crossed checkpoints | Implemented; validation pending |
| 2 | Bounded retry when a channel has no streams yet | Implemented; validation pending |
| 3 | Validate queued preflight source, channel identity, and expiry | Implemented; validation pending |
| 4 | Separate dropdown catalogs from due-check admission | Implemented; validation pending |
| 5 | Cache subscription/sport/league metadata | Implemented; validation pending |
| 6 | Thread-owned HTTP connection reuse | Implemented; validation pending |
| 7 | Operation-aware retries and ambiguous POST handling | Implemented; validation pending |
| 8 | Coalesce concurrent UDI channel refreshes | Implemented; validation pending |
| 9 | Detect metadata drift with unchanged IDs | Implemented; validation pending |
| 10 | Monotonic duration/timeout clocks | Implemented; validation pending |
| 11 | Conditional status responses with ETags | Implemented; validation pending |
| 12 | Visible, serial, cancellable browser polling | Implemented; validation pending |
| 13 | Isolated countdowns and visible stream rows | Implemented; validation pending |
| 14 | Consolidate suitable stats write paths | Implemented; validation pending |
| 15 | Bound legacy in-memory changelog | Implemented; validation pending |
| 16 | Extract checker queue/stats responsibilities | Implemented; validation pending |
| 17 | Separate operation timing summaries | Implemented; validation pending |

## Implementation changes

- Preflight scheduling now uses a monotonic start-to-start cadence with a wake
  signal for configuration changes and stop requests. The newest crossed timing
  bucket can be admitted after a slow scan without replaying superseded buckets.
- Candidates are reclassified after network reads against the current event time.
- Missing streams get bounded, interval-spaced retries within that bucket's
  deadline, instead of immediately consuming the attempted-bucket marker.
- Dropdown options refresh on a separate bounded worker. Catalog/subscription
  reads share a 300-second monotonic TTL cache scoped to connector credentials.
  Configuration changes invalidate it. Event/team readiness is never TTL cached.
- Queue metadata includes expiry and an enqueue monotonic timestamp. Queued
  validation checks the queued policy fingerprint (excluding the API key) and
  re-reads Teamarr
  identity and Dispatcharr channel UUID using existing
  control-plane endpoints, and records source outages separately from expiry.
  Invalid time, changed policy/source, disabled preflight, filtering, and channel
  reuse have explicit skip reasons. Explicit scans and manual checks retain
  their opt-in behavior while automatic scanning is disabled. Transient source outages release the attempt
  marker for readmission; expired checkpoints remain terminal.
- Persistent control-plane sessions belong to the current thread and origin.
  Headers stay per request; cookies do not carry across API operations. No hidden
  HTTP-adapter retries are enabled. PATCH retries distinguish permission failures
  from transient transport/server/rate-limit errors, with bounded backoff and
  numeric Retry-After handling. Authentication is refreshed at most once per call.
- Ambiguous non-idempotent POST outcomes are not replayed automatically. Callers
  can supply a read-only reconciliation callback. Channel creation reconciles
  new channel IDs against a pre-request baseline and accepts only one matching
  channel; an unconfirmed creation or refresh remains uncertain without replay. Connection-establishment
  failures and rejected authentication are distinguished from accepted requests.
- Status ETags cover the complete serialized public JSON. This saves transfer
  and frontend work on unchanged responses, not the number of status polls or
  the backend's normal status generation. Responses are private and revalidated.
- The legacy compatibility changelog retains at most 200 entries in RAM. SQL
  telemetry remains the historical record.

- Concurrent reads for the same UDI channel share only in-flight requests. A
  later check fetches fresh channel and stream metadata through existing APIs.
  Incomplete stream responses are rejected before publication.
- Stable-ID changes in names, URLs, groups, provider assignment, or channel
  assignment invalidate affected checked-stream immunity. UDI updates keep URL,
  account, and group indexes consistent. Statistics writes update existing
  indexed records without a full stream-list scan, and acknowledged local
  statistics changes during a metadata read are preserved.
- Queued preflight validation is wired into the specialized execution module.
  Direct preflight checks also publish the dedicated preflight run mode and
  reject a changed policy or expired checkpoint before launching media work.
- Single-stream statistics writes share the existing acknowledged batch writer.
  Each stream still uses Dispatcharr's existing PATCH endpoint; this is not a
  server-side bulk-write API. Cache publication follows successful responses;
  partial failures remain counted separately. Payload filtering is preserved
  independently for single-stream and batch preparation.
- Queue execution and statistics preparation/writing now live in separate
  modules, with shared probe-report field definitions.
- Recovery deadlines, provider waits, media-probe elapsed time, and channel/run
  durations use monotonic clocks. Event dates and persisted start timestamps
  continue to use calendar time.
- Bounded operation summaries expose queue wait, provider wait, analysis,
  metadata/API reads, and API write request durations separately.
  Each phase retains at most 100 samples; totals cover that retained window.
  Provider wait includes provider/profile/global capacity admission. These are
  backend status fields and do not add user settings.
- The browser revalidates eligible status responses with ETags and reuses the
  prior payload for 304 responses. Its cache is bounded to 32 entries and is
  invalidated around mutations and authentication failures. Unsupported status
  endpoints retain ordinary GET behavior.
- Dashboard, Stream Checker, and Teamarr Preflight polling pause on hidden tabs,
  cancel reads on hide/unmount, serialize requests, and refresh on return.
- Stream countdowns update isolated cells. Tables with at least 100 streams
  render the visible range plus overscan, measuring variable row heights.

## Validation corrections - 2026-10-02

- Restored the complete queue terminalization callback and abort-isolation block
  inside the extracted queue mixin. Python compilation and queue lifecycle tests
  now cover the complete module rather than its partial extraction.
- Failed or incomplete fresh metadata reads now defer checks before profile
  fallback, checked-stream immunity, media analysis, or assignment writes.
  Teamarr attempt markers are released for this transient deferral.
- Newly assigned streams establish their statistics baseline before the stream
  read: fresh server values replace old cached statistics, while acknowledged
  writes during that read remain preserved.
- Catalog publication uses a generation fence. Stop/configuration changes reject
  old in-flight catalogs; a subsequent explicit scan can publish fresh dropdown
  options while automatic scanning remains disabled.
- HTTP timeout/retry tests mock the shared transport boundary. Queue ownership
  fixtures explicitly accept queued validation; dedicated expiry/source tests
  continue exercising the real validator. Post-start catch-up is tested inside
  the grace deadline rather than at its expiry boundary.

## Recorded validation

Local environment: Windows, Python 3.12.10, Node 24.15.0.

- Backend compilation: passed (`python -m compileall -q backend/apps`).
- Targeted regression/preflight/connectivity tests: 123 passed.
- Isolated integration contracts: 57 passed, 1 skipped.
- Frontend: 295 tests passed across 39 files; production build passed.
- Frontend dependency audit: high-severity gate passed; two existing moderate
  React Router findings remain. No forced major-version upgrade is included.
- Complete stable backend suite: final rerun pending.
- Live validation of the new image: pending. Existing deployment baseline pages
  load without browser exceptions; that baseline is not evidence for this image.

## Regression specifications added or updated

Executed locally during draft validation:

- `backend/tests/test_efficiency_primitives.py`: in-flight sharing, failure
  recovery, catalog TTL/copy semantics, invalidation during reads, crossed
  checkpoints, deadline calculation, and full-response ETag revalidation.
- `backend/tests/test_operation_aware_posts.py`: ambiguous response suppression,
  reconciliation, connect/auth retries, rate limits, permission failures, and
  per-stream partial statistics write failures.
- `backend/tests/test_fresh_channel_metadata.py`: stable-ID drift, index
  consistency, incomplete responses, fresh later reads, and concurrent stats.
- `backend/tests/test_queued_preflight_validation.py`: expiry before/after reads,
  channel reuse, source changes/outages, policy changes, invalid times, and
  queue integration that prevents probes on skipped entries, bounded missing
  stream retries, and release of attempt markers after source outages.
- `frontend/src/lib/conditional-status.test.js`: 304 reuse, auth isolation,
  bounded storage, mutations, and in-flight invalidation.
- `frontend/src/lib/visible-poller.test.js`: hide/return cancellation and
  serialization, hidden-tab behavior, and recovery after transient errors.
- `frontend/src/lib/virtual-rows.test.js`: variable-height ranges, overscan,
  empty data, and scroll extent.
- Existing preflight/checker statistics tests and provider fixtures are adapted
  to the extracted writer and fresh metadata boundary.

## Required runtime validation

- Backend targeted regressions, then relevant checker/UDI/preflight suites.
- Frontend tests and production build; inspect small and large stream tables,
  changing row order/heights, countdowns, and narrow viewports.
- Verify conditional 200/304 transitions across queue/progress changes and
  mutations; hide/return/unmount during an in-flight request.
- Live Unraid validation against existing connector APIs: late scans, no-stream
  retries, queued expiry, transient outages, provider admission, and write-back.
- Compare added targeted metadata-read cost against saved duplicate reads and
  connection reuse. Timing samples are instrumentation, not a measured speedup.

Performance timing samples remain instrumentation; no production speedup is claimed.
