from pathlib import Path

from contracts.futures_contract_master import FuturesProductType
from infrastructure.kis.futures_websocket_subscription_source import current_kospi200_futures_symbols


def test_current_kospi200_futures_symbols_comes_from_authoritative_master(tmp_path: Path) -> None:
    (tmp_path / "fo_idx_code_mts.mst").write_text(
        "\n".join(
            (
                "1|SSTD01|KRSTD01|F 202610| |00000.00|1|2001|KOSPI200",
                "1|SSTD02|KRSTD02|F 202612| |00000.00|2|2001|KOSPI200",
                "B|SMIN01|KRMIN01|F 202610| |00000.00|1|2001|KOSPI200",
                "B|SMIN02|KRMIN02|F 202612| |00000.00|2|2001|KOSPI200",
            )
        ),
        encoding="cp949",
    )

    assert current_kospi200_futures_symbols(tmp_path) == (
        (FuturesProductType.STANDARD, "SSTD01"),
        (FuturesProductType.MINI, "SMIN01"),
    )


def test_current_kospi200_futures_symbols_fails_closed_without_master(tmp_path: Path) -> None:
    try:
        current_kospi200_futures_symbols(tmp_path)
    except RuntimeError as exc:
        assert str(exc) == "KIS_FUTURES_MASTER_REQUIRED"
    else:
        raise AssertionError("missing futures master must fail closed")
