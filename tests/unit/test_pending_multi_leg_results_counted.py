from types import SimpleNamespace

from application.composition.automated_virtual_trading_loop import summarize_pending_multi_leg_results


def test_pending_multi_leg_fills_are_counted_and_execution_ids_are_preserved():
    results = (
        SimpleNamespace(
            strategy_id="track9_event_overnight_insurance",
            routed_legs=1,
            filled_legs=1,
            reports=(SimpleNamespace(execution_id="EXEC-CALL"),),
        ),
        SimpleNamespace(
            strategy_id="track5_gap_divergence",
            routed_legs=1,
            filled_legs=0,
            reports=(SimpleNamespace(execution_id="EXEC-NEW"),),
        ),
    )

    routed, filled, execution_ids = summarize_pending_multi_leg_results(results)

    assert routed == 2
    assert filled == 1
    assert execution_ids == ("EXEC-CALL", "EXEC-NEW")


def test_pending_multi_leg_result_without_reports_has_zero_fill_and_no_ids():
    results = (SimpleNamespace(routed_legs=0, filled_legs=0, reports=()),)

    assert summarize_pending_multi_leg_results(results) == (0, 0, ())
