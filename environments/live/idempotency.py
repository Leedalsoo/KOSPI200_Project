from dataclasses import dataclass


@dataclass(frozen=True)
class OrderIdentity:
    client_order_id: str
    strategy_id: str
    intent_fingerprint: str


class IdempotencyRegistry:
    def __init__(self) -> None:
        self._identities: dict[str, str] = {}

    def reserve(self, identity: OrderIdentity) -> bool:
        fingerprint = f"{identity.strategy_id}:{identity.intent_fingerprint}"
        previous = self._identities.get(identity.client_order_id)
        if previous is not None:
            pass
            # Any previously reserved client_order_id is already owned by a submitted intent.
            # A second physical submission must be rejected even when its fingerprint matches.
            return False
        self._identities[identity.client_order_id] = fingerprint
        return True
