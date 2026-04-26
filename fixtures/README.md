# fixtures

Canonical test fixtures used by `tests/test_scrape.py`.

- `endpoint_notes.md` — endpoint, query params, quirks. Authoritative.
- `sample_response.json` — one full saved response from the live endpoint
  (captured 2026-04-25). 12 records, page 1 of a 53-record total.

Note: the fixture's `paging.totalCount` is 53 (all CPO E-Class **wagons**,
no model filter), not 34 (CPO E450S4 wagons specifically — what the canonical
query in PROJECT.md returns). The 12 records on page 1 happen to all be
E450S4 because they're closest by distance to ZIP 90210. For parser tests,
record contents are still representative; for end-to-end pagination tests
against this fixture, expect 53/12 not 34/12.
