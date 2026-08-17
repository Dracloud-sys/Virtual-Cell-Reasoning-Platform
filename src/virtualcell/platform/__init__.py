"""Domain-neutral query and reasoning boundary (PR11).

VCRP is a general biological experiment reasoning platform. This package is the seam
that keeps it one: a generic request/response contract, a domain registry, and a single
application service that every interface calls. Immortalization is registered here as
the first reference domain pack, not as the platform's subject.
"""

from __future__ import annotations

from virtualcell.core.consumption import (
    ConsumptionLedger,
    ConsumptionReport,
    ConsumptionStatus,
    MeasurementConsumption,
)
from virtualcell.platform.bootstrap import default_registry
from virtualcell.platform.contracts import (
    DecisionSupport,
    ExplanationLevel,
    LiteratureOutcome,
    LiteratureStatus,
    QueryProvenance,
    ReasoningQuery,
    ReasoningResponse,
)
from virtualcell.platform.domains import (
    DomainError,
    DomainPack,
    DomainRegistry,
    QueryValidationError,
    UnknownDomainError,
    UnsupportedTaskError,
)
from virtualcell.platform.service import ReasoningService

__all__ = [
    "ConsumptionLedger",
    "ConsumptionReport",
    "ConsumptionStatus",
    "DecisionSupport",
    "DomainError",
    "DomainPack",
    "DomainRegistry",
    "ExplanationLevel",
    "LiteratureOutcome",
    "LiteratureStatus",
    "MeasurementConsumption",
    "QueryProvenance",
    "QueryValidationError",
    "ReasoningQuery",
    "ReasoningResponse",
    "ReasoningService",
    "UnknownDomainError",
    "UnsupportedTaskError",
    "default_registry",
]
