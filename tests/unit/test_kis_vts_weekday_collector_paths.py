from pathlib import Path

from infrastructure.kis.kis_vts_weekday_collector import (
    DEFAULT_MARKET_DATA_DIR,
    ROOT,
    market_data_root_from_env,
)


def test_kis_collector_defaults_to_documented_market_data_root(monkeypatch):
    monkeypatch.delenv("PROJECT200_MARKET_DATA_DIR", raising=False)
    assert market_data_root_from_env() == ROOT / "data" / DEFAULT_MARKET_DATA_DIR


def test_kis_collector_respects_absolute_market_data_root(monkeypatch, tmp_path):
    configured = tmp_path / "authoritative-market-data"
    monkeypatch.setenv("PROJECT200_MARKET_DATA_DIR", str(configured))
    assert market_data_root_from_env() == configured


def test_kis_collector_respects_relative_market_data_root(monkeypatch):
    monkeypatch.setenv("PROJECT200_MARKET_DATA_DIR", "custom_market_data")
    assert market_data_root_from_env() == ROOT / "data" / "custom_market_data"


def test_collector_logging_creates_canonical_log_directory(monkeypatch, tmp_path):
    import logging.handlers

    from infrastructure.kis import kis_vts_weekday_collector as collector

    data_root = tmp_path / "data-root"
    log_path = data_root / "logs" / "collector.log"
    monkeypatch.setattr(collector, "DATA_ROOT", data_root)
    monkeypatch.setattr(collector, "LOG_PATH", log_path)
    logger = collector.configure_logging()
    try:
        assert log_path.parent.is_dir()
    finally:
        for handler in list(logger.handlers):
            if isinstance(handler, logging.handlers.RotatingFileHandler) and handler.baseFilename == str(log_path):
                logger.removeHandler(handler)
                handler.close()
