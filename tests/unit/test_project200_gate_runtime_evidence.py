from verification import project200_gate


def test_runtime_evidence_blocked_is_not_reported_as_fail(monkeypatch):
    monkeypatch.setattr(
        project200_gate,
        "run",
        lambda cmd: (1, '{"status":"BLOCKED","error":"Live credentials incomplete"}\n'),
    )
    result = project200_gate.check_runtime_evidence()
    assert result.status == "BLOCKED"
    assert "Live credentials incomplete" in result.detail


def test_runtime_evidence_nonzero_without_blocked_status_is_fail(monkeypatch):
    monkeypatch.setattr(project200_gate, "run", lambda cmd: (1, '{"status":"FAIL"}\n'))
    result = project200_gate.check_runtime_evidence()
    assert result.status == "FAIL"
