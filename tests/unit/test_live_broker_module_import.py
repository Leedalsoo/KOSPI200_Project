import importlib
import typing


def test_live_broker_module_imports():
    module = importlib.import_module("environments.live.broker.kis_live_broker")
    assert hasattr(module, "LiveBrokerAdapter")


def test_live_broker_submit_annotations_resolve():
    module = importlib.import_module("environments.live.broker.kis_live_broker")
    hints = typing.get_type_hints(module.LiveBrokerAdapter.submit)
    assert "health" in hints
    assert "daily_pnl" in hints


def test_live_runtime_authoritative_composition_imports():
    importlib.import_module("application.composition.live_runtime_authoritative_composition")

def test_all_live_and_paper_annotations_resolve():
    """Python-version independent guard: Python 3.14+ defers annotation evaluation,
    so a missing import only shows up when annotations are resolved explicitly."""
    import inspect
    import pkgutil

    import environments.live as live_pkg
    import environments.paper as paper_pkg

    unresolved = []
    for pkg in (live_pkg, paper_pkg):
        for info in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
            try:
                module = importlib.import_module(info.name)
            except Exception as exc:  # import-time failure is also a failure
                unresolved.append(f"{info.name}: import {type(exc).__name__}")
                continue
            callables = []
            for _, cls in inspect.getmembers(module, inspect.isclass):
                if cls.__module__ == module.__name__:
                    callables += [fn for _, fn in inspect.getmembers(cls, inspect.isfunction)]
            callables += [
                fn for _, fn in inspect.getmembers(module, inspect.isfunction)
                if fn.__module__ == module.__name__
            ]
            for fn in callables:
                try:
                    typing.get_type_hints(fn)
                except Exception as exc:
                    unresolved.append(f"{info.name}.{fn.__qualname__}: {type(exc).__name__}")
    assert unresolved == []