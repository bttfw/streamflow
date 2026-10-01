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
| 3 | Validate queued preflight source, channel identity, and expiry | Implemented; integration in progress |
| 4 | Separate dropdown catalogs from due-check admission | Implemented; validation pending |
| 5 | Cache subscription/sport/league metadata | Implemented; validation pending |
| 6 | Thread-owned HTTP connection reuse | Implemented; validation pending |
| 7 | Operation-aware retries and ambiguous POST handling | Implemented; reconciliation integration pending |
| 8 | Coalesce concurrent UDI channel refreshes | In progress |
| 9 | Detect metadata drift with unchanged IDs | In progress |
| 10 | Monotonic duration/timeout clocks | In progress |
| 11 | Conditional status responses with ETags | Backend implemented; frontend in progress |
| 12 | Visible, serial, cancellable browser polling | In progress |
| 13 | Isolated countdowns and visible stream rows | In progress |
| 14 | Consolidate suitable stats write paths | In progress |
| 15 | Bound legacy in-memory changelog | Implemented; validation pending |
| 16 | Extract checker queue/stats responsibilities | In progress |
| 17 | Separate operation timing summaries | In progress |

## Changes so far

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
  can supply a read-only reconciliation callback. Connection-establishment
  failures and rejected authentication are distinguished from accepted requests.
- Status ETags cover the complete serialized public JSON. This saves transfer
  and frontend work on unchanged responses, not the number of status polls or
  the backend's normal status generation. Responses are private and revalidated.
- The legacy compatibility changelog retains at most 200 entries in RAM. SQL
  telemetry remains the historical record.

## Validation pending

Targeted backend regression tests, frontend tests/build, relevant full suites,
and live Unraid validation remain open. New test files are regression
specifications until executed. No test result or image readiness is claimed.
