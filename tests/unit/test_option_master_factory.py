from application.composition import option_master_factory as factory


def test_production_calendar_defers_kis_loading_to_fallback(monkeypatch, tmp_path):
    captured = {}

    class FakeKISHolidayProvider:
        def __init__(self, *, auth_manager, auto_load, strict_mode, target_year):
            captured["provider_auto_load"] = auto_load

    class FakeKRXHolidayProvider:
        def __init__(self, *, cache_dir, source_loader):
            captured["cache_dir"] = cache_dir

    class FakeFallbackHolidayProvider:
        def __init__(self, *, kis_provider, krx_provider, enable_kis):
            captured["fallback_enable_kis"] = enable_kis

    monkeypatch.setattr(factory, "KISHolidayProvider", FakeKISHolidayProvider)
    monkeypatch.setattr(factory, "KRXHolidayProvider", FakeKRXHolidayProvider)
    monkeypatch.setattr(factory, "FallbackHolidayProvider", FakeFallbackHolidayProvider)

    factory.create_production_trading_calendar(
        auto_load_kis=True, target_year=2026, calendar_cache_dir=str(tmp_path)
    )

    # Fallback owns lazy source resolution, so factory construction must not call KIS.
    assert captured["provider_auto_load"] is False
    assert captured["fallback_enable_kis"] is True
