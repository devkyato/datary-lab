# Datary report: noisy\-sensor\-example

- Datary version: `0.2.4`
- Recorded with Datary: `0.2.4`
- Session format: `2`
- Started: `2026-08-09T01:07:55.640448+08:00`
- Ended: `2026-08-09T01:07:55.688832+08:00`
- Input format: `jsonl`
- Records: 101 valid, 0 invalid

## Reproduction

- Original command: `datary generate noisy-sensor --seed 1`
- Working directory: `<redacted>`
- Command context: Run from the session parent directory or set DATARY\_WORKSPACE to that directory\.
- compare: `datary compare noisy-sensor-example OTHER`
- inspect: `datary inspect noisy-sensor-example`
- replay: `datary replay noisy-sensor-example`
- report: `datary report noisy-sensor-example`

## Data schema

| Field | Type | Unit |
|---|---|---|
| timestamp | number |  |
| value | number |  |

## Descriptive statistics

### timestamp

- Mean: 4.999999999999993
- Median: 5.0
- Range: 0.0 to 10.0

### value

- Mean: 20.17767606050936
- Median: 20.261510417832035
- Range: 18.94492804097838 to 21.111120412614504

## Timing

- backward\_timestamp\_count: `0`
- duplicate\_timestamp\_count: `0`
- duration: `10.0`
- effective\_sample\_rate: `9.999999999999988`
- end: `10.0`
- gap\_count: `0`
- jitter: `4.3390452126414056e-16`
- maximum\_interval: `0.10000000000000142`
- mean\_interval: `0.10000000000000013`
- median\_interval: `0.09999999999999998`
- minimum\_interval: `0.09999999999999964`
- start: `0.0`

## Engineering metrics

No control or network field roles were supplied.

## Quality findings

No heuristic findings.

## Input hashes

- `data.csv`: `cb52476a95187874065f6cc5306c368b7433d28fd8357dccfe659603a3f5e24a`
- `invalid.jsonl`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `metrics.json`: `70263c17f02120c8f4e04285025aa8d5e43b71bd7034030df7fc808fc211cd65`
- `notes.md`: `a510c5cf6eb3f60d592443e63d03bcda952e157eea94c9cd76a4695426cb51e9`
- `quality.json`: `8aa973100a15bf817985395637131e838cf84e427be4792583def923f020f5fa`
- `raw.log`: `d22ef77cba7e4330d271280e85dc7d1d8a852b6a731b5443ca436d5fd2d65d8e`
- `records.jsonl`: `9ccd2b842825bf7788c36e7e546a04a3b582cae386903dd1171b08816fc3f31e`

## Integrity verification

All manifest-listed artefacts passed SHA-256 corruption checks.
These checks detect accidental changes; they do not prove cryptographic authenticity.

## Warnings and assumptions

- Statistics describe recorded data; they do not establish scientific validity\.
- Quality checks are heuristics and require domain review\.
- Plot downsampling preserves declared extrema but is visual evidence, not a new recording\.

## Plots

- [plot\-value\.png](../sessions/noisy-sensor-example/plots/plot-value.png)
  - Downsample: algorithm=`extrema-preserving-buckets`; applied=`False`; original=`101`; plotted=`101`; max_points=`5000`; preserved_extrema=`True`
  - Policy: keep first, last, local min, and local max per bucket
