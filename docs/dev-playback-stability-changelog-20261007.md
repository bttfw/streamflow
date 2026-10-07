# Dev playback stability changelog — 2026-10-07

## Passive playback evidence

- Added an optional recorder using Dispatcharr's existing proxy status. It opens
  no additional IPTV/provider connection and preserves the existing authoritative
  status cache and viewer protection rules.
- Recording defaults to off for existing and new installations. Configuration is
  persisted in the existing SQLite database under `playback_stability`.
- Confirmed viewer sessions accumulate observed duration, byte-delivery stalls
  and source switches while the same viewer remains attached to the same channel
  session. Shadow watchers and identifiable StreamFlow clients are excluded.
- Ordinary session endings, retuning, API outages, observation gaps and byte
  counter resets do not count as failures. Initial tuning has a grace period;
  stalls require at least 30 seconds without byte progress after that period.
- History uses checkpointed rows in `playback_observations`, including during an
  active playback. Restarting preserves confirmed history without treating the
  unobserved restart interval as a failure. Long sessions rotate checkpoints every
  ten minutes. Retention is evaluated using each checkpoint's last observed time,
  with at most ten minutes of boundary overlap.
- Evidence is tied to the Dispatcharr stream ID and a hash of its source URL.
  Viewer identities, IP addresses, provider credentials and source URLs are not
  stored in the history. A changed URL cannot inherit an older source's evidence.
- All channels, including Teamarr channels, follow the same optional rules.
  Observations for the same source are combined across channels.

## Optional quality scoring

- Added `Use Playback Stability` and `Playback Stability Weight` to the profile
  editor's Stream Checking → Stream Quality Scoring section. Usage defaults to off
  and requires the global recording option to be enabled.
- A source needs at least 600 observed seconds and 60 valid samples inside the
  retention window before its stability can affect ordering.
- Stability is `max(0, 1 - stalled / observed) / (1 + failovers * 3600 / observed)`.
  The existing quality score is multiplied by
  `1 - playback_stability_weight * (1 - stability)`. The default optional weight
  is 0.15, limiting deductions to 15% of the existing quality score.
- Sources without sufficient evidence retain exactly the existing quality score;
  there is no default zero and no extra denominator weight. A measured stable
  source also retains its existing score. Playlist and resolution ordering modes
  keep their existing priority rules.
- Sequential and concurrent channel checks obtain one immutable evidence snapshot
  per channel. One-off source probes without a channel/profile remain unchanged.
- The legacy sequential retry retains its existing global quality weights. Its
  optional stability deduction is applied separately, so adding the feature cannot
  silently change that retry's baseline for an unobserved source.

## Settings and history

- Added Settings → Monitoring → Playback Stability, with an independent save action,
  `Record Playback Stability`, polling interval (5–60 seconds, default 10) and
  retention (1–30 days, default 14).
- Added a sanitized passive history table showing observed time, stall time,
  failovers and either a measured score or `Not enough data`. The API limits the
  display to the 200 most recently observed sources; scoring uses the full eligible
  history for the channel's assigned sources.
- Added `/api/playback-stability/config` (GET/PUT) and
  `/api/playback-stability/status` (GET). Invalid settings are rejected without
  overwriting the saved configuration. Disabled collection performs no polling
  and has no scoring effect.

## Measurement limits

- This observes delivery through Dispatcharr; it cannot detect a decoder freeze
  while bytes continue arriving or prove what a player displayed.
- A source switch with a continuously attached viewer is an observed failover,
  not proof of its underlying cause. Missing client/session/byte-counter metadata
  is ignored rather than inferred.
- Polling can miss interruptions shorter than its interval. The history describes
  observed playback, not every event between snapshots.

## Validation

- Initial focused backend coverage: 48 tests passed, including missing evidence,
  Teamarr parity, stalls, session changes, API outages, restart persistence, source
  replacement, retention, cross-channel aggregation and disable-during-poll races.
- Extended focused backend coverage: 55 tests passed, including real Flask routes,
  profile/config persistence and freshness/eligibility boundaries.
- Final expanded stable backend suite: 2,038 passed, one skipped;
  integration contracts: 57 passed, one skipped.
- Frontend: all 302 tests passed; production build passed. Six browser scenarios
  covered default-off settings, save/reload, independent profile opt-in, editable
  weight, master-off gating and isolated settings-load failures, with no page errors.
- Profile step buttons now expose accessible names and their selected state.
- Normal Unraid DockerMan validation is pending.

## Backend dependency audit

- GitHub's backend audit reported CVE-2026-102598 in the existing Werkzeug 3.1.8
  pin before reaching the test step. Updated the production and test locks to
  Werkzeug 3.1.9, retaining hash-verified installation. Release artifacts and
  SHA-256 hashes were checked against https://pypi.org/project/Werkzeug/3.1.9/.
- The existing frontend dependency audit is unchanged; no check is disabled.
