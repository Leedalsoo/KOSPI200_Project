# Q25 A7 X+1 — strategy_ids registry compatibility fix

Date: 2026-11-11
Status: implemented, focused regression verified, local commit only. B4 not started.

## Finding

build_standard_strategy_registry() did not accept the strategy_ids keyword, while application/composition/automated_virtual_runtime_factory.py passed the selected strategy IDs. This raised TypeError before selected Runtime strategies could be registered.

## Change

- core/strategy/standard_registry.py
  - Added optional strategy_ids: Iterable[str] | None.
  - None retains the previous all-standard-strategies behavior.
  - Explicit selections instantiate and register only the requested strategy IDs.
  - Full manifest-vs-code strategy ID set validation remains unchanged.
  - Code-version validation remains strict for each selected strategy.
  - Empty/invalid selections and unknown IDs fail closed with explicit errors.
- tests/core/test_standard_strategy_registry_selection.py
  - Verifies S2-only selection, exclusion of unselected strategies, unknown ID rejection, empty/invalid selection rejection, and string-as-collection rejection.
- Caller and strategy manifest were not changed.

## Verification

- 13 focused S2 test files: 193 passed.
- py -m compileall on changed Python files: PASS.
- git diff --check: PASS.
- Secret-pattern scan: no matches.
- Graphify AST refresh: completed; existing warning remains for application/composition/virtual_composition_root.py line 54 and 29 no-symbol files.

## Known separate baseline issue

The broad/default all-strategy registry path still encounters the previously recorded Track1 manifest/code version mismatch (manifest=1.1.0, code=1.2.0). This predates X+1 and was already recorded in the A3 baseline comparison. It is not changed as part of this narrow compatibility fix. Explicit S2 selection (track2_asymmetric_trap, version 1.0) succeeds against the current manifest.

## Git and safety

- Worktree: C:\Users\white\AppData\Local\Temp\Q25_S2_INTEGRATE_20261111
- Branch: integrate/q25-s2-20261111
- Start HEAD: 8e13ac90220df05ffc124507e9ca40baee60cb17
- Local commit only; no push (X+1 is not an A7 push stage).
- Original project work folder and its 224 dirty/untracked items were not touched.
- No Live/REAL_VTS/real-account/order/cancel/correction/balance API, .env, operational configuration, scheduler or collector changes.

## Next

X+1 is resolved for explicit strategy selection. B4 remains pending user approval and has not been started.
