# Splunk platform seed generation report

## Status

Expanded candidate pilot seed generated for review: ten Capabilities and eight
Skills, with the primary runtime snapshot assembled into one file.
Initial MCP discovery and `get_indexes` were
validated against a live Splunk 9.1 environment, but the generated fixed and
templated searches have not yet been exercised through MOSAIC. The seed must
not yet be treated as an approved production integration.

## Source provenance

- MCP repository: <https://github.com/splunk/splunk-mcp-server2>
- Selected branch: `main`
- Inspected commit: `fac6cbb37be057a68607642d8d60d9c19ba5a060`
- Commit date: 16 June 2025
- Inspection date: 19 October 2026
- MCP implementation: `python/server.py`, `python/splunk_client.py`,
  `python/guardrails.py`, and `python/spl_risk_rules.py`
- Live pilot endpoint: `http://localhost:8051/mcp`
- Live Splunk version: 9.1

The pilot MCP deployment includes local compatibility changes not present in
the pinned repository: MCP SDK v1.30.0, Streamable HTTP transport, synchronous
launcher, stateful HTTP sessions, JSON responses, and corrected Python package
module declarations.

## Observed MCP contract

The inspected source registers seven tools:

| Tool | Inputs | Returned value | Seed disposition |
| --- | --- | --- | --- |
| `validate_spl` | Arbitrary `query` | Structured risk assessment | Excluded; validation is a provider control rather than a user outcome. |
| `search_oneshot` | Query, time range, count, format, guardrail overrides | Structured search result | Allowlisted only behind fixed or narrowly templated read-only queries. |
| `search_export` | Same broad inputs as oneshot | Structured search result | Excluded; implementation buffers results and offers no seed advantage. |
| `get_indexes` | None | Structured index catalogue | Included. |
| `get_saved_searches` | None | Structured saved-search definitions | Excluded because definitions can disclose sensitive searches and schedules. |
| `run_saved_search` | Search name and action flag | Search result | Excluded because dispatch is active execution, can trigger actions, and polls without an overall timeout. |
| `get_config` | None | Server configuration | Excluded because it is diagnostic configuration rather than a platform outcome. |

Live discovery confirmed that dictionary results are wrapped under
`structuredContent.result`. The seed therefore selects `/result/indexes` and
`/result/events`. A live `get_indexes` call completed successfully against
Splunk 9.1.

## Seed design

The expanded candidate contains two endpoint-per-target connection aliases,
ten semantic Capabilities and eight procedural Skills. The original four
Capabilities remain available:

- `splunk.indexes.read`
- `splunk.internal.errors.read`
- `splunk.index.activity.count`
- `splunk.index.errors.read`

New tenant and application outcomes are:

- `splunk.pod.logs.read`
- `splunk.pod.errors.read`
- `splunk.index.ingestion.read`
- `splunk.index.sources.read`
- `splunk.request.trace.read`
- `splunk.index.volume.read`

The existing Skill IDs are preserved and grouped by function:

- `inspect-splunk-platform-health`
- `inspect-splunk-index`
- `investigate-splunk-index-errors`

Five added Skills cover the missing investigations:

- `inspect-splunk-application-logs`
- `investigate-splunk-missing-logs`
- `investigate-splunk-request`
- `inspect-splunk-log-volume`
- `investigate-openshift-application-logs`

Seven packages use `skills/splunk/<function>/<skill-name>` with indexes,
platform-health, investigations, application-logs, ingestion, request-tracing
and volume functions. The cross-domain package uses
`skills/container-platforms/investigations/investigate-openshift-application-logs`.
The index Skill is version 1.1.0 because it gains optional ingestion/source
outcomes. Other existing versions and IDs are preserved.

Bounded log excerpts are now supported. No unrestricted raw event, arbitrary
SPL or export Capability is exposed. The platform Skill retains aggregate-only
behaviour and is not a complete distributed Splunk health assessment.

## Safety boundary

- Only `get_indexes` and `search_oneshot` are allowlisted.
- Original activity/error searches retain their fixed fifteen-minute window.
  New searches accept only `15m`, `30m` or `1h`, with identical SPL and REST
  time bounds. They do not support arbitrary historical intervals.
- Query, maximum count, output format, risk tolerance, and sanitisation are
  fixed by the binding and cannot be overridden by the model.
- New semantic values are exact namespace, pod or non-secret request names
  and one enumerated window. Full-match patterns exclude SPL syntax. The
  namespace is the index name under the supplied tenant convention.
- Templates exclude whitespace, quotes, wildcards, pipes, brackets, and other
  SPL syntax from the supplied index name.
- New sampled log results contain at most 30 excerpts of at most 600 characters
  plus selected timestamps and cluster/pod/container metadata. The final table
  does not contain `_raw`. Minimal display redaction is still required because
  provider sanitisation is not a comprehensive sensitive-data control.
- Results are bounded to at most 50 aggregate rows and 200,000 encoded
  characters, except the index catalogue which permits 1,000 entries and
  500,000 characters.
- New search responses are limited to 100,000 encoded characters and 30
  selected rows. Result extraction remains `/result/events`; a tool error
  envelope without events fails extraction rather than becoming an empty list.

This is defence in depth. The Splunk token must still belong to a least-
privilege user limited to the indexes approved for this pilot.

## Deployment facts and assumptions

- Canonical pilot Target: `splunk/pilot`.
- Current MCP endpoint: `http://localhost:8051/mcp`.
- Provider routing: endpoint per target because the MCP server is configured
  for one Splunk backend and accepts no target selector.
- The existing `splunk` connection remains on the Splunk platform target.
  A separate `splunk-workloads` connection alias uses the same endpoint but
  resolves on the existing Kubernetes canonical cluster target. It permits
  only `search_oneshot`, not index inventory or internal platform searches.
  Activity and error aggregate outcomes gain a tenant binding on this target.
  No new MCP server is deployed by this change.
- The primary `config/local/capability-runtime-snapshot.json` contains the
  combined definitions and is the sole Splunk capability JSON. The separate
  Splunk example file has been removed. Container/MQ definitions and target
  identities are preserved; the previously identifying cluster alias is now
  generic. The tests read this primary file directly.
- Routing associates an endpoint with the cluster; it does not enforce a
  cluster filter in SPL. Index names can repeat across clusters. Searches
  retain observed cluster/pod/container hints, and the cross-domain Skill
  refuses attribution when the cluster relationship cannot be verified.
  Validate collector-controlled field mappings before demonstrating correlation;
  ambiguous or missing metadata must not be silently treated as a match.
- The endpoint currently has no inbound MCP authentication and must remain
  reachable only from the Mosaic runtime or an equivalent trusted boundary.
- `localhost` is valid only while Mosaic and the MCP server share a network
  namespace. Remote deployment requires a routable private URL and TLS.
- Credentials remain exclusively in the MCP server environment and are not
  present in the runtime snapshot.

## Validation

Initial mechanical validation, before this expansion:

- The standalone contribution validates with one Target, one Provider, and
  four Capabilities.
- The combined snapshot validates with three Targets, five Providers, and 69
  Capabilities.
- All three Splunk Skill packages validate individually through the catalogue
  parser.
- Exact index names prepare successfully for `splunk/pilot`; wildcard,
  whitespace, quote, pipe, and newline injection values are rejected.
- All 351 existing MOSAIC unit tests pass, with two existing skips.

Expansion validation:

- All eight expanded packages validate at the required hierarchy depth.
- The primary validates with three Targets, six
  connection aliases and 75 Capabilities.
- Cross-domain required Kubernetes and Splunk Capabilities resolve together
  against the same canonical cluster Target.
- `app/mosaic/tests/test_splunk_skill_seed.py` covers hierarchy and references,
  read-only allowlists, window consistency, output bounds, injected scope,
  ignored overrides, platform/workload routing separation, structured errors
  and coexistence with container and MQ outcomes in the primary file.
- No new live Splunk calls were made during expansion. Initial live discovery
  below is prior-session evidence, not verification of the added queries.
- All 362 backend unit tests complete successfully, with two existing opt-in
  live tests skipped. Eleven focused seed tests pass, as do lint and compilation.
  The replacement provider's guardrail evaluator accepts 33 synthetic prepared
  queries across the supported targets and windows. No search was executed.

Live validation completed:

- Streamable HTTP initialisation and `tools/list` completed successfully.
- `get_indexes` completed successfully against Splunk 9.1.
- Live results confirmed the `structuredContent.result` wrapper used by the
  generated JSON pointers.

Validation still required before approval:

1. Exercise all four Capabilities through MOSAIC against the live endpoint.
2. Confirm the fixed searches return the expected `result.events` shapes for
   normal, empty, unauthorised, timeout, and oversized cases.
3. Confirm the Splunk service identity cannot access indexes outside the pilot
   boundary and has no mutation capabilities.
4. Replace `localhost` with the approved private endpoint before separating
   Mosaic and the MCP server.
5. Review the Skills and aggregate queries with the Splunk platform owner.
6. Exercise added queries with normal, empty, denied, timeout and oversized
   responses. Verify pod-field mappings, request identifier fields and UTC
   timestamps. Known mappings are candidates, not proven deployment facts.
7. Demonstrate same-namespace records from different clusters are not combined.
   The current query scope is the approved index; provider-side permissions
   remain the security boundary. Metadata checks are not an RBAC replacement.

## Known limitations

- The MCP endpoint has no inbound authentication.
- The server's output sanitisation only masks credit-card-like numbers and US
  Social Security numbers; it is not a general data-loss-prevention control.
- `search_oneshot` permits broad queries at the provider layer. MOSAIC's fixed
  bindings and the Splunk account's permissions are required controls.
- The server duplicates time scope in the SPL text and REST parameters because
  its guardrail evaluates only the query text.
- Aggregate keyword searches can produce false positives and must not be
  interpreted as confirmed incidents.
- The source repository has no Splunk 9.1 automated compatibility suite; live
  `get_indexes` proves the exercised REST path, not every exposed tool.
