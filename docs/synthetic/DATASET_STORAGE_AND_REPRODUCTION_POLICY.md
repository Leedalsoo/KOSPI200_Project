# Synthetic Dataset Storage and Reproduction Policy

Status: A2-0 policy; datasets are intentionally excluded from Git.

## Rules

- Never commit generated market-data rows, replay datasets, original KIS collection data, `.env`, credentials, tokens, or local runtime databases.
- Commit generator/validator source, the documented generator version, deterministic seed, configuration identity when available, and SHA-256 hashes of dataset manifests only.
- Keep generated datasets under the local `data/derived_scenario/` tree. A clean checkout must not require the dataset bytes merely to collect and run unit tests.
- Regenerate datasets with the committed generator and validator. Compare the newly generated manifest SHA-256 to the recorded value before treating it as the same dataset.
- Every generated record must retain synthetic provenance (`synthetic=true`, `provenance=DERIVED_SCENARIO`, generator version and seed). Synthetic outputs are for implementation-gap detection only; never use their returns as profitability evidence or to tune strategy parameters.
- Keep REAL_VTS source partitions and synthetic datasets separate. Do not copy source records into synthetic output or synthetic records into source partitions.
- The recorded hashes below identify manifest bytes only; they do not hash or archive the dataset rows. A changed manifest requires a new evidence record rather than overwriting the old hash.

## Existing P5 scenario manifest evidence

Generator version: `p5-deterministic-synthetic-3m-v1`
Seed: `20261026`
Provenance: `DERIVED_SCENARIO`
Dataset rows are not included in this repository.

| Scenario | Manifest SHA-256 |
|---|---|
| `high_volatility` | `eec7c4ec50ec1eed56437568e6041ede4824f2d98a5cb27a07d00b4618b6669a` |
| `low_volatility` | `ff3f1787de7d15f7776659b472282ce85402b29c3448cf3b3bdbc4360dc49021` |
| `mean_revert` | `4d3b33662fdebbdbf15932aab296f33e79835f60c4986480e1398db7dc163247` |
| `shock` | `2f6b8dab48d6eac78bbceaf90c0b1cca2477a47b47f7c945ff18b920ef8ffc06` |
| `trend_down` | `e702a077a6f24600f2ef35891e5608cfb1c42ad2e714311809b7f50a60d03b0e` |
| `trend_up` | `47d6746bfd7abfea9d52016434ca06f097ca117e6724f96c522b58eb8e5590f5` |

The hashes above were calculated from the six local `manifest.json` files on 2026-10-30. They are not a claim that the dataset files are present in Git or that the datasets prove strategy profitability. `config_hash` was not present in these manifests and is therefore not inferred here.
