from uuid import uuid4

from contracts.risk import RiskApprovalToken, RiskEvaluationResult


def test_risk_approval_token_contract_is_legacy_independent():
    order_id = uuid4()
    token = RiskApprovalToken(
        order_id=order_id,
        timestamp_ns=123456789,
        signature="sig",
    )

    assert token.order_id == order_id
    assert token.timestamp_ns == 123456789
    assert token.signature == "sig"


def test_risk_approval_token_is_immutable():
    token = RiskApprovalToken(uuid4(), 1, "sig")

    try:
        token.signature = "changed"
    except Exception:
        pass
    else:
        raise AssertionError("RiskApprovalToken must be immutable")


def test_risk_evaluation_result_allow_contract():
    token = RiskApprovalToken(uuid4(), 10, "sig")
    result = RiskEvaluationResult(
        is_approved=True,
        decision="ALLOW",
        original_qty=3,
        approved_qty=3,
        required_margin=750000.0,
        estimated_margin_ratio=0.20,
        token=token,
    )

    assert result.is_approved is True
    assert result.decision == "ALLOW"
    assert result.original_qty == 3
    assert result.approved_qty == 3
    assert result.rejection_reason is None
    assert result.required_margin == 750000.0
    assert result.estimated_margin_ratio == 0.20
    assert result.token == token
    assert result.reduced_command is None


def test_risk_evaluation_result_reduce_contract():
    reduced_command = object()
    result = RiskEvaluationResult(
        is_approved=True,
        decision="REDUCE",
        original_qty=10,
        approved_qty=4,
        required_margin=1000000.0,
        estimated_margin_ratio=0.80,
        token=RiskApprovalToken(uuid4(), 20, "sig"),
        reduced_command=reduced_command,
    )

    assert result.is_approved is True
    assert result.decision == "REDUCE"
    assert result.approved_qty == 4
    assert result.reduced_command is reduced_command


def test_risk_evaluation_result_deny_contract():
    result = RiskEvaluationResult(
        is_approved=False,
        decision="DENY",
        original_qty=10,
        approved_qty=0,
        rejection_reason="POSITION_LIMIT",
    )

    assert result.is_approved is False
    assert result.decision == "DENY"
    assert result.approved_qty == 0
    assert result.rejection_reason == "POSITION_LIMIT"
    assert result.token is None
    assert result.reduced_command is None
