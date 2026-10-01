# Dev reliability and efficiency work - 2026-10-02

Status: draft implementation. Tests, build verification, and runtime validation
are pending. This document describes implementation changes; it does not claim
release readiness or a deployed image.

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
  validation re-reads Teamarr identity and Dispatcharr channel UUID using existing
  control-plane endpoints, and records source outages separately from expiry.
- Persistent control-plane sessions belong to the current thread and origin.
  Headers stay per request; cookies do not carry across API operations. No hidden
  HTTP-adapter retries are enabled.
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
  Direct preflight checks also publish the dedicated preflight run mode.
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
  metadata/API reads, and acknowledged API write request durations separately.
  Each phase retains at most 100 samples. They are backend status fields.
- The browser revalidates eligible status responses with ETags and reuses the
  prior payload for 304 responses. Its cache is bounded to 32 entries and is
  invalidated around mutations and authentication failures. Unsupported status
  endpoints retain ordinary GET behavior.
- Dashboard, Stream Checker, and Teamarr Preflight polling pause on hidden tabs,
  cancel reads on hide/unmount, serialize requests, and refresh on return.
- Stream countdowns update isolated cells. Tables with at least 100 streams
  render the visible range plus overscan, measuring variable row heights.

## Validation pending

Targeted backend regression tests, frontend tests/build, relevant full suites,
and live Unraid validation remain open. New test files are regression
specifications until executed. No test result or image readiness is claimed.
