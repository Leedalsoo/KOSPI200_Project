from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from environments.virtual.bundle import VirtualEnvironmentBundle


@dataclass(frozen=True)
class VirtualAuthoritativeScope:
    """Composition-time identity of one authoritative VSSF runtime scope."""

    vssf_runtime: Any
    broker: Any
    account: Any
    position: Any
    execution: Any


class VirtualEnvironmentBuilder(Protocol):
    """Minimal Application composition contract for a Virtual Environment."""

    def build(self, config: Any, policy: Any) -> VirtualEnvironmentBundle:
        """Build one complete Virtual Environment Bundle within one composition scope."""


class VirtualAuthoritativeScopeFactory(Protocol):
    """Create the shared VSSF-derived state owner used by Virtual projections."""

    def create(self, config: Any, policy: Any) -> VirtualAuthoritativeScope:
        """Return one VSSF runtime and its directly derived Environment components."""
