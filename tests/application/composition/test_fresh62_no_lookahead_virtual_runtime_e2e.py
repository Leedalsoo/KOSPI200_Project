from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from contracts.types import ExecutionLeg, MultiLegExecutionPlan, OptionInstrumentIdentity
from application.composition.validation_only_no_lookahead_anchor_reconciler import find_future_donors
from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources, build_synthetic_option_master
from environments.high_speed.virtual_runtime_replay import _publish_contract_scoped_replay_quote

SOURCE = Path('reports/synth/Q25_A8_R10_FRESH61_NO_LOOKAHEAD_20261013_20261118.jsonl')
SOURCE_MANIFEST = Path('reports/synth/Q25_A8_R10_FRESH61_NO_LOOKAHEAD_MANIFEST_20261118.json')
SOURCE_REPORT = Path('reports/synth/Q25_A8_R10_FRESH61_NO_LOOKAHEAD_RECONCILIATION_20261118.json')
TARGET_TIMESTAMP = '2026-10-13T10:55:46+09:00'
SCENARIO_ID = 'Q25_A8_R10_FRESH62_NO_LOOKAHEAD_VIRTUAL_RUNTIME'
STRATEGY_ID = 'track8_macro_regime_monthly_strangle'


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def _build_dataset(tmp_path):
    source_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding='utf-8'))
    source_report = json.loads(SOURCE_REPORT.read_text(encoding='utf-8'))
    rows = [json.loads(line) for line in SOURCE.read_text(encoding='utf-8').splitlines() if line.strip()]
    selected = [row for row in rows if row['tick']['timestamp'] == TARGET_TIMESTAMP]
    assert len(selected) == 4
    assert {(x['tick']['option_type'], x['tick']['strike_price']) for x in selected} == {
        ('CALL', 927.5), ('CALL', 930.0), ('PUT', 937.5), ('PUT', 950.0)
    }
    root = tmp_path / 'fresh62_replay_dataset'
    root.mkdir()
    output = []
    for row in selected:
        assert find_future_donors(row) == []
        record = json.loads(json.dumps(row))
        record['synthetic'] = True
        tick = record['tick']
        source_code = str(tick.get('source_instrument_code') or tick['symbol'])
        synthetic_id = 'SYNTHETIC_CONTRACT:FRESH62:' + sha256(
            f"{source_code}|{tick['expiry']}|{tick['option_type']}|{tick['strike_price']}".encode()
        ).hexdigest()[:20]
        tick['source_instrument_code'] = source_code
        tick['synthetic_contract_id'] = synthetic_id
        tick['instrument_id'] = None
        tick['instrument_identity_status'] = 'BLOCKED_IDENTITY_OWNER_UNRESOLVED'
        tick['symbol'] = synthetic_id
        record['scenario_metadata']['scenario_id'] = SCENARIO_ID
        record['scenario_metadata']['regime'] = 'NORMAL'
        record['scenario_metadata']['contract_identity_authority'] = 'SYNTHETIC_ONLY'
        record['scenario_metadata']['validation_only'] = True
        record['scenario_metadata']['fresh61_source_manifest_sha256'] = sha256(SOURCE_MANIFEST.read_bytes()).hexdigest()
        record['scenario_metadata']['fresh61_source_sidecar_sha256'] = sha256(SOURCE.read_bytes()).hexdigest()
        record['scenario_metadata']['fresh61_original_instrument_code'] = source_code
        record['scenario_metadata']['fresh61_no_lookahead_assertion'] = True
        record['scenario_metadata']['contract_multiplier_authority'] = 'SYNTHETIC_VALIDATION_FIXTURE_ONLY'
        output.append(record)
    payload = ''.join(json.dumps(x, sort_keys=True, separators=(',', ':')) + '\n' for x in output).encode()
    dataset_file = root / '20261013.jsonl'
    dataset_file.write_bytes(payload)
    days = []
    day = datetime(2026, 10, 13).date()
    expiry = datetime.strptime('20261112', '%Y%m%d').date()
    while day <= expiry:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    manifest = {
        'schema': 'reference-canonical-market-tick-v1', 'synthetic': True,
        'provenance': 'DERIVED_SCENARIO', 'validation_only': True,
        'production_runtime_eligible': False,
        'identity_source_status': 'BLOCKED_IDENTITY_OWNER_UNRESOLVED',
        'identity_policy': {'mode': 'SYNTHETIC_ONLY', 'synthetic_contract_id_namespace': 'SYNTHETIC_CONTRACT:', 'production_standard_instrument_id_assigned': False},
        'scenario_id': SCENARIO_ID, 'scenario_regimes': {SCENARIO_ID: 'NORMAL'},
        'trading_calendar': {'source_type': 'SYNTHETIC', 'authoritative': False, 'timezone': 'Asia/Seoul', 'trading_days': days},
        'source_manifest_sha256': sha256(SOURCE_MANIFEST.read_bytes()).hexdigest(),
        'source_sidecar_sha256': sha256(SOURCE.read_bytes()).hexdigest(),
        'source_fresh61_report_sha256': source_report['report_sha256'],
        'source_anchor_timestamp': TARGET_TIMESTAMP,
        'scenario_timestamp': TARGET_TIMESTAMP,
        'deterministic_rule_id': 'FRESH62-FOUR-LEG-NO-LOOKAHEAD-REPLAY-v1',
        'output_path': str(dataset_file),
        'output_sha256': sha256(payload).hexdigest(), 'output_bytes': len(payload), 'rows': len(output),
        'execution_enabled': False, 'order_submission_enabled': False, 'live_api_enabled': False,
    }
    (root / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding='utf-8')
    return root, manifest, output


def test_fresh61_corrected_four_leg_data_replays_through_virtual_runtime_bridge_to_flat(tmp_path):
    source_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding='utf-8'))
    source_report = json.loads(SOURCE_REPORT.read_text(encoding='utf-8'))
    assert source_report['after']['future_market_price_donors'] == 0
    root, manifest, source_rows = _build_dataset(tmp_path)
    adapter = SyntheticReplayAdapter(root)
    master = build_synthetic_option_master(root, validation_only_adapter=adapter)
    ticks = tuple(HighSpeedReplayRunner(root, synthetic_adapter=adapter).events())
    assert len(ticks) == 4
    assert {tick.timestamp for tick in ticks} == {TARGET_TIMESTAMP}
    assert all(tick.validation_only for tick in ticks)
    assert all(tick.instrument_id.startswith('SYNTHETIC_CONTRACT:FRESH62:') for tick in ticks)
    assert len({tick.instrument_id for tick in ticks}) == 4

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(option_master=master, initial_capital=250_000_000.0, risk_guard_status_source=sources)
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap, strategy_keys=(('TRACK1_TAIL_DEFENSE', '1.2.0'),),
        run_id='Q25-A8-FRESH62-NO-LOOKAHEAD', synthetic_runtime_sources=sources,
        track4_greeks_provider=sources, risk_guard_status_source=sources,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime

    def freshness(_plan, _leg, _identity, command):
        observed = datetime.fromisoformat(TARGET_TIMESTAMP)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH, reason='FRESH62_CORRECTED_SOURCE_FIXTURE',
            policy_version='Q25-A8-FRESH62-v1', source='DERIVED_SCENARIO:FRESH61',
            tr_id='VALIDATION_ONLY_REPLAY', environment='VIRTUAL_VALIDATION_ONLY',
            instrument_id=command.instrument_id, symbol=command.broker_symbol,
            source_instant=observed, received_at=observed,
            evidence_sha256=_digest({'timestamp': TARGET_TIMESTAMP, 'instrument_id': command.instrument_id, 'manifest': manifest['output_sha256']}),
        )
    bridge.freshness_verdict_provider = freshness

    identities = {}
    for tick in ticks:
        _publish_contract_scoped_replay_quote(tick, option_master=master, market=bootstrap.bundle.market, order_book=vssf.order_book)
        sources.set_tick(tick)
        bootstrap.bundle.market.publish_replay_tick(tick)
        item = master.get_contract_identity(tick.instrument_id)
        identities[tick.instrument_id] = OptionInstrumentIdentity(
            item.shrn_iscd, item.shrn_iscd, item.expiry, item.option_type,
            Decimal(str(item.strike)), Decimal(str(item.contract_multiplier)),
            'SYNTHETIC:FRESH62_VALIDATION_MASTER',
        )

    group_id = 'FRESH62-FOUR-LEG-GROUP'
    legs = tuple(ExecutionLeg(
        leg_id=f"LEG-{i}", side='BUY', quantity=1,
        option_type=identity.option_type, strike=identity.strike,
        requested_price=Decimal(str(next(t.bid_price for t in ticks if t.instrument_id == instrument))) - Decimal('0.01'),
        instrument_identity=identity,
    ) for i, (instrument, identity) in enumerate(sorted(identities.items()), 1))
    entry_plan = MultiLegExecutionPlan(group_id=group_id, strategy_id=STRATEGY_ID, purpose='FRESH62_VALIDATION_ENTRY', legs=legs)
    entry = bridge.execute(entry_plan)
    assert entry.routed_legs == 4
    assert entry.pending_legs == 4
    base = vssf._now()
    for offset, report in enumerate(entry.reports, 1):
        command = bridge.pending_legs[report.client_order_id][2]
        identity = identities[command.instrument_id]
        fill_command = type('FillCommand', (), {
            **command.__dict__, 'option_type': identity.option_type,
            'strike': float(identity.strike), 'expiry': identity.expiry,
            'contract_multiplier': identity.contract_multiplier,
            'identity_source': identity.identity_source, 'symbol': identity.instrument_id,
        })()
        execution = vssf.execution_engine.execute_order(
            fill_command, float(command.requested_price), 1,
            timestamp=base + timedelta(seconds=offset),
        )
        vssf.account.apply_execution(execution)
    vssf.process_pending_orders()
    entry_updates = bridge.process_pending_quotes()
    assert len(entry_updates) == 4
    assert all(all(getattr(report, 'status', '') == 'FILLED' and getattr(report, 'rejected_reason', None) is None for report in update.reports) for update in entry_updates)
    assert len(bridge.position_lot_store.open_lots()) == 4
    assert len(bridge.position_lot_store.history()) == 4
    assert len(bridge.position_groups.all()) == 1

    close_plan = bridge.build_close_plan_from_open_lots(
        strategy_id=STRATEGY_ID, purpose='FRESH62_VALIDATION_TERMINAL_CLOSE',
        asset_type='OPTION', leg_id_prefix='FRESH62-CLOSE',
    )
    close = bridge.execute(close_plan, group_plan=entry_plan)
    assert close.routed_legs == 4
    assert all(getattr(report, 'rejected_reason', None) is None for report in close.reports)
    base = vssf._now()
    immediate_close_fills = 0
    for offset, report in enumerate(close.reports, 1):
        if report.client_order_id not in bridge.pending_legs:
            assert report.status == 'FILLED'
            immediate_close_fills += 1
            continue
        command = bridge.pending_legs[report.client_order_id][2]
        identity = identities[command.instrument_id]
        fill_command = type('FillCommand', (), {
            **command.__dict__, 'option_type': identity.option_type,
            'strike': float(identity.strike), 'expiry': identity.expiry,
            'contract_multiplier': identity.contract_multiplier,
            'identity_source': identity.identity_source, 'symbol': identity.instrument_id,
        })()
        execution = vssf.execution_engine.execute_order(
            fill_command, float(command.requested_price), 1,
            timestamp=base + timedelta(seconds=offset),
        )
        vssf.account.apply_execution(execution)
    vssf.process_pending_orders()
    close_updates = bridge.process_pending_quotes()
    assert len(close_updates) + immediate_close_fills == 4
    assert all(all(getattr(report, 'status', '') == 'FILLED' for report in update.reports) for update in close_updates)
    assert bridge.position_lot_store.open_lots() == ()
    assert len(bridge.position_lot_store.history()) == 4
    assert sum(event.quantity for event in bridge.position_lot_store.close_events()) == 4
    assert len({event.execution_id for event in bridge.position_lot_store.close_events()}) == 4
    assert bridge.pending_legs == {}
    assert vssf.account.positions == {}
    assert len(bridge.fee_ledger.snapshot(run_id=bridge.run_id)) == 8
    assert manifest['output_sha256'] == sha256((root / '20261013.jsonl').read_bytes()).hexdigest()
    assert source_report['after']['future_market_price_donors'] == 0
    assert all(row['scenario_metadata']['validation_only_no_lookahead'] is True for row in source_rows)
