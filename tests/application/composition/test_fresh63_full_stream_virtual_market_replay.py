from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from application.composition.validation_only_no_lookahead_anchor_reconciler import find_future_donors
from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources, build_synthetic_option_master
from environments.high_speed.virtual_runtime_replay import _publish_contract_scoped_replay_quote

ROOT = Path('reports/synth')
SOURCE_MANIFEST = ROOT / 'Q25_A8_R10_FRESH61_NO_LOOKAHEAD_MANIFEST_20261118.json'
SOURCE_REPORT = ROOT / 'Q25_A8_R10_FRESH61_NO_LOOKAHEAD_RECONCILIATION_20261118.json'
SOURCE_FILES = {
    '20261012': ROOT / 'Q25_A8_R10_FRESH61_NO_LOOKAHEAD_20261012_20261118.jsonl',
    '20261013': ROOT / 'Q25_A8_R10_FRESH61_NO_LOOKAHEAD_20261013_20261118.jsonl',
}
SCENARIO_ID = 'Q25_A8_R10_FRESH63_FULL_STREAM_VIRTUAL_MARKET'


def _build_dataset(tmp_path):
    manifest_source = json.loads(SOURCE_MANIFEST.read_text(encoding='utf-8'))
    report_source = json.loads(SOURCE_REPORT.read_text(encoding='utf-8'))
    root = tmp_path / 'fresh63_full_stream_dataset'
    root.mkdir()
    source_rows = []
    day_stats = {}
    for day, source_path in SOURCE_FILES.items():
        expected = next(x['sha256'] for x in report_source['corrected_sidecars'] if x['file'] == source_path.name)
        assert sha256(source_path.read_bytes()).hexdigest() == expected
        records = [json.loads(line) for line in source_path.read_text(encoding='utf-8').splitlines() if line.strip()]
        converted = []
        for original in records:
            assert find_future_donors(original) == []
            assert original['scenario_metadata'].get('validation_only_no_lookahead') is True
            record = json.loads(json.dumps(original))
            record['synthetic'] = True
            tick = record['tick']
            source_code = str(tick.get('source_instrument_code') or tick['symbol'])
            synthetic_id = 'SYNTHETIC_CONTRACT:FRESH63:' + sha256(
                f"{source_code}|{tick['expiry']}|{tick['option_type']}|{tick['strike_price']}".encode()
            ).hexdigest()[:20]
            tick['source_instrument_code'] = source_code
            tick['synthetic_contract_id'] = synthetic_id
            tick['instrument_id'] = None
            tick['instrument_identity_status'] = 'BLOCKED_IDENTITY_OWNER_UNRESOLVED'
            tick['symbol'] = synthetic_id
            metadata = record['scenario_metadata']
            metadata['scenario_id'] = SCENARIO_ID
            metadata['regime'] = 'NORMAL'
            metadata['validation_only'] = True
            metadata['contract_identity_authority'] = 'SYNTHETIC_ONLY'
            metadata['fresh61_source_manifest_sha256'] = sha256(SOURCE_MANIFEST.read_bytes()).hexdigest()
            metadata['fresh61_source_sidecar_sha256'] = expected
            metadata['fresh61_original_instrument_code'] = source_code
            metadata['fresh61_no_lookahead_assertion'] = True
            metadata['contract_multiplier_authority'] = 'SYNTHETIC_VALIDATION_FIXTURE_ONLY'
            converted.append(record)
            source_rows.append(original)
        payload = ''.join(json.dumps(x, sort_keys=True, separators=(',', ':')) + '\n' for x in converted).encode()
        (root / f'{day}.jsonl').write_bytes(payload)
        day_stats[day] = {'rows': len(converted), 'sha256': sha256(payload).hexdigest()}
    days = []
    current = date(2026, 10, 12)
    final = date(2026, 11, 12)
    while current <= final:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    manifest = {
        'schema': 'reference-canonical-market-tick-v1', 'synthetic': True,
        'provenance': 'DERIVED_SCENARIO', 'validation_only': True,
        'production_runtime_eligible': False,
        'identity_source_status': 'BLOCKED_IDENTITY_OWNER_UNRESOLVED',
        'identity_policy': {'mode': 'SYNTHETIC_ONLY', 'synthetic_contract_id_namespace': 'SYNTHETIC_CONTRACT:', 'production_standard_instrument_id_assigned': False},
        'scenario_id': SCENARIO_ID, 'scenario_regimes': {SCENARIO_ID: 'NORMAL'},
        'trading_calendar': {'source_type': 'SYNTHETIC', 'authoritative': False, 'timezone': 'Asia/Seoul', 'trading_days': days},
        'source_manifest_sha256': sha256(SOURCE_MANIFEST.read_bytes()).hexdigest(),
        'source_report_sha256': report_source['report_sha256'],
        'source_sidecars': day_stats,
        'deterministic_rule_id': 'FRESH63-FULL-STREAM-SYNTHETIC-IDENTITY-v1',
        'execution_enabled': False, 'order_submission_enabled': False, 'live_api_enabled': False,
    }
    (root / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding='utf-8')
    return root, manifest, source_rows, day_stats


def test_fresh61_all_2072_rows_replay_through_virtual_market_without_order_submission(tmp_path):
    source_report = json.loads(SOURCE_REPORT.read_text(encoding='utf-8'))
    assert source_report['after']['future_market_price_donors'] == 0
    root, manifest, source_rows, day_stats = _build_dataset(tmp_path)
    assert day_stats['20261012']['rows'] == 686
    assert day_stats['20261013']['rows'] == 1386
    adapter = SyntheticReplayAdapter(root)
    option_master = build_synthetic_option_master(root, validation_only_adapter=adapter)
    replay = HighSpeedReplayRunner(root, synthetic_adapter=adapter)

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(option_master=option_master, initial_capital=250_000_000.0, risk_guard_status_source=sources)
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap, strategy_keys=(('TRACK1_TAIL_DEFENSE', '1.2.0'),),
        run_id='Q25-A8-FRESH63-FULL-STREAM', synthetic_runtime_sources=sources,
        track4_greeks_provider=sources, risk_guard_status_source=sources,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    market = bootstrap.bundle.market
    bridge = loop.multi_leg_bridge
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime

    count = 0
    previous = None
    reversals = 0
    timestamp_underlying = {}
    duplicate_keys = Counter()
    duplicate_prices = defaultdict(set)
    unique_contracts = set()
    collected_times = [datetime.fromisoformat(x['scenario_metadata']['source_collected_at']) for x in source_rows]
    for tick in replay.events():
        observed = datetime.fromisoformat(tick.timestamp)
        if previous is not None and observed < previous:
            reversals += 1
        previous = observed
        key = (tick.timestamp, tick.source_instrument_code)
        duplicate_keys[key] += 1
        duplicate_prices[key].add((tick.bid_price, tick.ask_price, tick.last_price))
        unique_contracts.add(tick.instrument_id)
        assert tick.validation_only is True
        assert tick.instrument_id.startswith('SYNTHETIC_CONTRACT:FRESH63:')
        assert tick.instrument_id == tick.synthetic_contract_id
        assert tick.underlying_price is not None and tick.underlying_price > 0
        assert tick.bid_price >= 0 and tick.ask_price > tick.bid_price and tick.last_price > 0
        assert tick.contract_multiplier == 250000.0
        prior_underlying = timestamp_underlying.setdefault(tick.timestamp, tick.underlying_price)
        assert prior_underlying == tick.underlying_price
        _publish_contract_scoped_replay_quote(tick, option_master=option_master, market=market, order_book=vssf.order_book)
        sources.set_tick(tick)
        market.publish_replay_tick(tick)
        count += 1

    original_ids = [x['scenario_metadata']['source_observation_id'] for x in source_rows]
    original_lines = [(x['scenario_metadata']['trading_date'], x['scenario_metadata']['source_line_number']) for x in source_rows]
    assert count == 2072
    assert reversals == 0
    assert sum(b < a for a, b in zip(collected_times, collected_times[1:])) == 0
    assert len(timestamp_underlying) == 1596
    assert len(set(original_ids)) == 2072
    assert len(set(original_lines)) == 2072
    assert len(unique_contracts) == 77
    assert len(market.option_quotes_by_instrument_id) == 77
    assert len(market.option_quotes) == 77
    assert len(vssf.order_book.books) == 77
    assert all(value['source'] == 'SYNTHETIC:DERIVED_SCENARIO' for value in market.option_quotes_by_instrument_id.values())
    assert market.last_tick.timestamp == '2026-10-13T15:33:30+09:00'
    assert market.clock.current_time == datetime.fromisoformat('2026-10-13T15:33:30+09:00')
    assert bridge.pending_legs == {}
    assert vssf.order_book.pending_orders() == ()
    assert vssf.metrics['order_commands'] == 0
    assert vssf.account.positions == {}
    assert len([key for key, value in duplicate_keys.items() if value > 1]) == 183
    assert sum(value - 1 for value in duplicate_keys.values() if value > 1) == 299
    assert sum(len(duplicate_prices[key]) == 1 for key in duplicate_keys if duplicate_keys[key] > 1) == 49
    assert sum(len(duplicate_prices[key]) > 1 for key in duplicate_keys if duplicate_keys[key] > 1) == 134
