# Splunk platform seed generation report

## Status

Candidate pilot seed generated for review. MCP discovery and `get_indexes` were
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

The candidate contains one endpoint-per-target provider, four semantic
Capabilities, and three procedural Skills:

- `splunk.indexes.read`
- `splunk.internal.errors.read`
- `splunk.index.activity.count`
- `splunk.index.errors.read`
- `inspect-splunk-platform-health`
- `inspect-splunk-index`
- `investigate-splunk-index-errors`

The seed starts with index metadata, recent activity counts, and aggregate
error indicators. It intentionally does not expose a general Splunk search
Capability or raw events.

## Safety boundary

- Only `get_indexes` and `search_oneshot` are allowlisted.
- Every search uses a fixed fifteen-minute window.
- Query, maximum count, output format, risk tolerance, and sanitization are
  fixed by the binding and cannot be overridden by the model.
- The only semantic query value is one exact index name constrained to a
  conservative character set and maximum length.
- Templates exclude whitespace, quotes, wildcards, pipes, brackets, and other
  SPL syntax from the supplied index name.
- Search outputs contain counts grouped by host/component or host/sourcetype;
  raw events are not returned by the generated queries.
- Results are bounded to at most 50 aggregate rows and 200,000 encoded
  characters, except the index catalogue which permits 1,000 entries and
  500,000 characters.

This is defence in depth. The Splunk token must still belong to a least-
privilege user limited to the indexes approved for this pilot.

## Deployment facts and assumptions

- Canonical pilot Target: `splunk/pilot`.
- Current MCP endpoint: `http://localhost:8051/mcp`.
- Provider routing: endpoint per target because the MCP server is configured
  for one Splunk backend and accepts no target selector.
- The endpoint currently has no inbound MCP authentication and must remain
  reachable only from the Mosaic runtime or an equivalent trusted boundary.
- `localhost` is valid only while Mosaic and the MCP server share a network
  namespace. Remote deployment requires a routable private URL and TLS.
- Credentials remain exclusively in the MCP server environment and are not
  present in the runtime snapshot.

## Validation

Completed mechanical validation:

- The standalone contribution validates with one Target, one Provider, and
  four Capabilities.
- The combined snapshot validates with three Targets, five Providers, and 69
  Capabilities.
- All three Splunk Skill packages validate individually through the catalogue
  parser.
- Exact index names prepare successfully for `splunk/pilot`; wildcard,
  whitespace, quote, pipe, and newline injection values are rejected.
- All 351 existing MOSAIC unit tests pass, with two existing skips.

Live validation completed:

- Streamable HTTP initialization and `tools/list` completed successfully.
- `get_indexes` completed successfully against Splunk 9.1.
- Live results confirmed the `structuredContent.result` wrapper used by the
  generated JSON pointers.

Validation still required before approval:

1. Exercise all four Capabilities through MOSAIC against the live endpoint.
2. Confirm the fixed searches return the expected `result.events` shapes for
   normal, empty, unauthorized, timeout, and oversized cases.
3. Confirm the Splunk service identity cannot access indexes outside the pilot
   boundary and has no mutation capabilities.
4. Replace `localhost` with the approved private endpoint before separating
   Mosaic and the MCP server.
5. Review the Skills and aggregate queries with the Splunk platform owner.

## Known limitations

- The MCP endpoint has no inbound authentication.
- The server's output sanitization only masks credit-card-like numbers and US
  Social Security numbers; it is not a general data-loss-prevention control.
- `search_oneshot` permits broad queries at the provider layer. MOSAIC's fixed
  bindings and the Splunk account's permissions are required controls.
- The server duplicates time scope in the SPL text and REST parameters because
  its guardrail evaluates only the query text.
- Aggregate keyword searches can produce false positives and must not be
  interpreted as confirmed incidents.
- The source repository has no Splunk 9.1 automated compatibility suite; live
  `get_indexes` proves the exercised REST path, not every exposed tool.
