from application.bootstrap import create_virtual_runtime_bootstrap
from core.strategy.standard_registry import STANDARD_STRATEGY_KEYS

bootstrap = create_virtual_runtime_bootstrap(initial_capital=1_000_000_000.0)
loop = bootstrap.automated_loop
tick = next(bootstrap.bundle.market.generate_tick_stream(total_days=1, ticks_per_day=1))
result = loop.last_result
view = bootstrap.ui_adapter.get_tab_detail("virtual_broker")
assert result is not None
assert result.tick_sequence == tick.seq_id == 1
assert len(STANDARD_STRATEGY_KEYS) == 9
assert result.signals >= 1
assert result.routed >= 1
assert result.filled >= 1
assert len(bootstrap.bundle.execution.reports()) >= 1
assert len(bootstrap.bundle.position.snapshot()) >= 1
assert len(view["recent_executions"]) >= 1
assert len(view["positions"]) >= 1
print("RUNTIME_CONTROLLER_NINE_STRATEGY_LOOP_PASS", result)
print("CONTROL_TOWER", {"executions":len(view["recent_executions"]), "positions":len(view["positions"]), "margin_used":view["margin_used"], "margin_available":view["margin_available"]})
print("CONTROLLER", bootstrap.runtime_controller.status())
