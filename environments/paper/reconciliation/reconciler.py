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
        # TODO(PAPER): 수량/평단 비교는 Paper 구현 단계에서 추가
        return ReconciliationResult(not differences, tuple(differences))
