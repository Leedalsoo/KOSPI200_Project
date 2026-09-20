from pathlib import Path

from verification import project200_gate


ROOT = Path(__file__).resolve().parents[2]


def test_strategy_proposals_do_not_embed_literal_operational_quantity_one() -> None:
    patterns = project200_gate.FORBIDDEN_OPERATIONAL_PATTERNS + [
        r"\bproposed_quantity\s*=\s*1\b",
        r"\bproposed_quantity\s*:\s*int\s*=\s*1\b",
    ]
    for relative_path in (
        "core/strategy/track1_tail_defense.py",
        "core/strategy/track2_asymmetric_trap.py",
    ):
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        assert not any(project200_gate.re.search(pattern, text) for pattern in patterns), relative_path
