# Bundled FINVIZ migration (Issue #106)

Adopted upstream: [claude-trading-skills revision 34b848b41f5741435bb4791692a6c0c7a66c0597](https://github.com/tradermonty/claude-trading-skills/tree/34b848b41f5741435bb4791692a6c0c7a66c0597).
Ported the stock export request, Elite market-cap parser, safe provider error
logging, and authenticated group export with public fallback. The app retains
its existing FMP ETF holdings endpoint and provider order.

## Ranking and units

- Stock CSV uses `/export/screener`, `type=stocks`, `v=151`, `ft=4`,
  `c=1,6,66` (Ticker, Market Cap, Change). Industry, capitalization, price,
  average volume, and direction filters are unchanged.
- The approved migration contract is the three-column contract in upstream
  #799. Upstream #800's Volume addition remains separate: do not request
  column 67 here. Without Volume, cap/change weights normalize to 4/7 and
  3/7. For two stocks, BIG with cap 12B/change -1.25% scores 0.7857;
  SMALL with cap 765.59M/change 2.5% scores 0.7143.
- Elite `765.59` means $765,590,000. Suffixed values and public numeric
  dollar values retain their original units. Unknown Elite cap is 0
  (the existing unknown sentinel), never a valid micro-cap observation.
- Missing or duplicate required columns, malformed CSV rows, HTML and
  request failures reject Elite results and allow public fallback. This is
  stricter than upstream's warning-only missing-column behavior.
- Selection order: Elite, public Finviz, FMP ETF holdings, static config.
  Each stock retains its actual `source`: `finviz_elite`, `finviz_public`,
  `etf_holdings`, or `static`. FMP marketValue is the holding's value,
  not the issuer's market capitalization.

## Group data and provenance

Elite groups continue using `/grp_export` (not the stock export endpoint).
Percent points are normalized to decimal ratios, then the app converts them
back to percent points once. Truncated groups (under 11 sectors or 100
industries), invalid schema, and HTTP failures trigger public Finviz fallback.
`metadata.data_sources.finviz_industry_performance` records actual source
(`elite`, `public`, `unavailable`) and a fixed, safe `fallback_reason`.
`metadata.finviz_mode` reflects that source, while individual stock sources
remain independent. Public groups with an FMP configuration are labeled
`FINVIZ-Public+FMP`. Explicit `--finviz-mode public` suppresses Elite requests.
Public parsing requires `finvizfinance>=1.5.0` (declared in pyproject.toml).
Provider exception messages and response bodies must never be logged.

## Validation and rollout

Offline fixtures exercise the app's bundled scripts, representative-stock
entry point, group unit conversion and provider fallback. No real keys are
needed. The finvizfinance 1.5.0 HTML parser is checked with synthetic HTML.

Live comparison is opt-in; skip it when no FINVIZ_API_KEY is available.
On 2026-11-18 at 14:41 UTC, a read-only Elite check compared the legacy
export (saved 18-column settings) with the new pinned 3-column export:

| Industry / filter | Legacy rows | New rows | Tickers / cap / change |
| --- | ---: | ---: | --- |
| Semiconductors, small+, 4w up | 10 | 10 | Identical |
| Semiconductors, small+, 4w down | 36 | 36 | Identical |

All four requests returned HTTP 200. The bundled group adapter fetched
11 sectors and 144 industries with source `elite`, no fallback.
These are point-in-time checks for one industry, not exhaustive coverage.
Repeat the comparison for the configured industries after December 7, 2026.

Offline validation with Python 3.12.10 and finvizfinance 1.5.0: 1,572 passed,
1 skipped; total coverage 98.49% (required 98.44%). The bundled theme suite
has 571 passing tests, including the synthetic 1.5.0 public HTML parser.
The full repository quality gate passes: lint, formatting, Bandit,
codespell, coverage tests and compilation. A separate mechanical commit
resolves pre-existing gate failures using equivalent UTC/type/zip syntax,
formatted documentation examples and annotations for synthetic test keys.
The affected parabolic, PEAD and trader-memory suites additionally pass
259, 63 and 99 tests respectively. Secret scanning and the bootstrap
upload-file collection check also pass.

The uploaded Managed Agent skill is a separate deployment artifact. After
review and merge, use the existing bootstrap skill-version registration flow
to upload this bundled directory and verify the agent uses the new version.
This change does not upload or rotate live agent resources.
