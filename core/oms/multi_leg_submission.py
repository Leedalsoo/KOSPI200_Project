from __future__ import annotations

from typing import Any, Callable, Sequence

from contracts.types import BrokerOrderCommand, OrderIntent


class MultiLegSubmissionError(RuntimeError):
    pass


CommandMapper = Callable[[OrderIntent], BrokerOrderCommand]
TokenSupplier = Callable[[OrderIntent, BrokerOrderCommand], Any]


def submit_multi_leg_intents(
    intents: Sequence[OrderIntent],
    *,
    to_broker_command: CommandMapper,
    approval_token_for: TokenSupplier,
    order_router: Any,
) -> tuple[Any, ...]:
    """Submit already-approved intents in declared plan order.

    This is intentionally a transport seam, not an atomic execution engine.
    It does not infer, reorder, compensate, unwind, or synthesize risk tokens.
    """
    if not intents:
        raise MultiLegSubmissionError("MULTI_LEG_INTENTS_REQUIRED")
    if order_router is None or not callable(getattr(order_router, "register_and_route", None)):
        raise MultiLegSubmissionError("ORDER_ROUTER_REQUIRED")

    group_id = intents[0].group_id
    if not group_id:
        raise MultiLegSubmissionError("GROUP_ID_REQUIRED")
    if len({intent.group_id for intent in intents}) != 1:
        raise MultiLegSubmissionError("GROUP_ID_MISMATCH")
    if len({intent.leg_id for intent in intents}) != len(intents) or any(not i.leg_id for i in intents):
        raise MultiLegSubmissionError("UNIQUE_LEG_ID_REQUIRED")

    responses = []
    for intent in intents:
        command = to_broker_command(intent)
        if command is None:
            raise MultiLegSubmissionError("BROKER_COMMAND_REQUIRED")
        if command.group_id != intent.group_id or command.leg_id != intent.leg_id:
            raise MultiLegSubmissionError("GROUP_LEG_PROVENANCE_MISMATCH")
        token = approval_token_for(intent, command)
        if token is None:
            raise MultiLegSubmissionError("RISK_APPROVAL_TOKEN_REQUIRED")
        responses.append(order_router.register_and_route(command, token))
    return tuple(responses)
