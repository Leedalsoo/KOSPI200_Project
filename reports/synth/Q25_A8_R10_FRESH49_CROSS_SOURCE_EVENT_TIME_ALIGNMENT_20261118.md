# FRESH-49 Cross-source event-time alignment audit

## Scope

- Accepted Runtime v2 rows: 2,072
- Timestamp groups: 1,596
- Trading dates: 2026-10-12 and 2026-10-13
- Accepted Runtime manifest SHA-256: 7657c90f13a81a7f98a8ccd075a259c8ec9795477a2a0541366094cd87e0360f
- Combined REST manifest/raw evidence SHA-256: f30cce891eaed63d373ce6cebb5bbd758af71a523b06e0ae81425f7ebe7915ab
- Original Project200 Raw/Canonical/Accepted and synthetic source files were read-only. No collector/API calls or data writes.

## Accepted option and REST alignment

- Accepted option event-to-collection lag seconds: {'count': 2072, 'min_seconds': 0.047872, 'median_seconds': 0.5935275, 'p90_seconds': 0.969297, 'max_seconds': 4.393446}
- REST rows: 10,555; valid aspr_acpt_hour: 10,505; missing/zero event time: 50.
- REST request/response symbol mismatches: 0
- REST exact / nearest-prior / no matching symbol: 7 / 186 / 1879 option-symbol rows.
- REST anchor age seconds: {'count': 193, 'min_seconds': 0.0, 'median_seconds': 74.0, 'p90_seconds': 137.0, 'max_seconds': 355.0}
- REST source-event-to-collection lag seconds: {'count': 10505, 'min_seconds': 0.085014, 'median_seconds': 41.858898, 'p90_seconds': 231.152656, 'max_seconds': 2067.470727}

## Underlying alignment and future-anchor correction

- Selected source classes: {'KIS_EXACT_TIMESTAMP': 1168, 'KIS_NEAREST_PRIOR': 354, 'KIS_GROUP_MEDIAN_DERIVED': 40, 'SYNTHETIC_DERIVED_ANCHOR': 34}
- Selected anchor age by class: {'KIS_EXACT_TIMESTAMP': {'count': 1168, 'min_seconds': 0.0, 'median_seconds': 0.0, 'p90_seconds': 0.0, 'max_seconds': 0.0}, 'KIS_GROUP_MEDIAN_DERIVED': {'count': 40, 'min_seconds': 0.0, 'median_seconds': 0.0, 'p90_seconds': 0.0, 'max_seconds': 0.0}, 'KIS_NEAREST_PRIOR': {'count': 354, 'min_seconds': 1.0, 'median_seconds': 1.0, 'p90_seconds': 1.0, 'max_seconds': 180.0}, 'SYNTHETIC_DERIVED_ANCHOR': {'count': 34, 'min_seconds': 0.0, 'median_seconds': 96.0, 'p90_seconds': 233.0, 'max_seconds': 283.0}}
- Original synthetic donor anchors: 50 timestamp groups / 62 option rows; future donor: 21 groups / 27 rows.
- Re-resolved with nearest-prior KIS H0UPCNT0: 16 groups / 19 rows; with nearest-prior KRX-derived scenario bars: 34 groups / 43 rows.
- Selected future anchors after alternative resolution: 0 groups / 0 rows.
- KIS H0UPCNT0 Raw: 23335 valid event-time rows; 1 malformed-time row excluded from anchor candidates.
- KRX shock-v4 scenario: 84 unique 5-minute bar timestamps; conflicting underlying spot bars: 0.
- Original accepted synthetic donor values remain recorded per timestamp group; the selected alternate anchor is separately recorded with source, timestamp, value, payload/dataset hash and selection method.

## Per-day matrix

| Trading date | Timestamp groups | Option rows | REST exact | REST prior | No REST symbol | Underlying exact | Underlying prior | Group median | Synthetic prior |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20261012 | 543 | 686 | 7 | 186 | 493 | 381 | 149 | 13 | 0 |
| 20261013 | 1053 | 1386 | 0 | 0 | 1386 | 787 | 205 | 27 | 34 |

## Interpretation

- REST collected_at is receive/collection evidence, not an event-time substitute. REST anchors are selected only from same-day, same-symbol source times at or before the option event.
- No REST match is a coverage boundary, not an automatic overall block. 2026-10-13 has no matching REST symbols for the Accepted Runtime option set.
- Underlying synthetic future donors were not reused. When possible, original H0UPCNT0 Raw was used as nearest-prior; before the first KIS underlying event, the existing KRX-derived scenario was re-anchored to the latest prior 5-minute bar. This remains synthetic validation input, not observed KIS data.
- No universal freshness threshold was invented. Anchor age and receive lag are reported as distributions for later policy comparison.
- Accepted Runtime v2 remains a derived replay view. Synthetic/enriched Greeks, depth, multiplier and scenario anchors are not authoritative KIS/account facts.
- Read-only, validation-only, non-authoritative. No gate release, Production/Live readiness, actual tradability or profitability claim.
- Report SHA-256: 3f30c6e5c2b4e265dc631ef5ab0582637ee718faa175a86f0098f7d3138db940
