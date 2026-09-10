from typing import Protocol

from contracts.environment import EnvironmentLifecycle
from contracts.types import EnvironmentType


class StandardEnvironmentBundle(EnvironmentLifecycle, Protocol):
    """All four environments expose the same lifecycle and identity boundary."""

    environment: EnvironmentType
