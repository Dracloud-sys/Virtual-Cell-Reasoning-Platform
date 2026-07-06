"""Dynamic simulation interface.

The cell is modeled as a state that evolves over discrete time steps under an
environment. v0.1 defines the data structures and the ``SimulationEngine`` protocol;
concrete engines (ODE, agent-based, ML-surrogate) arrive in later releases.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class CellState(BaseModel):
    """A snapshot of cellular state at a point in time.

    Fields are intentionally open (dict-valued layers) so the schema can grow with
    the biological hierarchy without breaking the interface.
    """

    time: float = 0.0
    transcriptome: dict[str, float] = Field(default_factory=dict)
    proteome: dict[str, float] = Field(default_factory=dict)
    metabolome: dict[str, float] = Field(default_factory=dict)
    phenotype: dict[str, float] = Field(default_factory=dict)


class TimeStep(BaseModel):
    """One step of a simulation trajectory."""

    index: int
    dt: float
    state: CellState


@runtime_checkable
class SimulationEngine(Protocol):
    """Advances a :class:`CellState` through time under an environment."""

    def step(self, state: CellState, dt: float, environment: dict[str, float]) -> CellState:
        """Return the next state after advancing by ``dt``."""
        ...

    def run(
        self,
        initial: CellState,
        steps: int,
        dt: float,
        environment: dict[str, float] | None = None,
    ) -> list[TimeStep]:
        """Return the full trajectory of ``steps`` steps."""
        ...
