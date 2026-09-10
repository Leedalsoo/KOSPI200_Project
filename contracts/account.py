from typing import Protocol

from contracts.types import AccountSnapshot


class AccountProvider(Protocol):
    """Environment-neutral account state provider."""

    def snapshot(self) -> AccountSnapshot: ...
