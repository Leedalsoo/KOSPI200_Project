[Child Page] reconciler.py
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ReconciliationResult:
    matched: bool
    differences: tuple[str, ...]

class PaperReconciler:
    def compare(self, broker_snapshot, internal_snapshot) -> ReconciliationResult:
        differences = []
        if broker_snapshot is None or internal_snapshot is None:
            differences.append("missing_snapshot")
        elif getattr(broker_snapshot, "is_stale", False):
            differences.append("stale_broker_snapshot")
        return ReconciliationResult(not differences, tuple(differences))
```