"""`provenance.pack` is a compatibility surface, so its value is pinned on the product path.

PR15 expanded the vertical and briefly renamed `PACK_ID` to `adipogenesis.v1` on the grounds
that the pack was no longer minimal. That is true and beside the point: this string ships on
every response, so anything already keying off it — stored reports, downstream filters, a
consumer's fixtures — reads a rename as a *different pack*. Renaming it is a provenance-policy
change with its own migration, not a side effect of growing a domain.

Pinned here rather than in `test_second_domain_reach.py` because that file is about a domain
reaching the interfaces. This one is about a promise made to whoever is already reading the
answers, which is a different reason for a test to exist and should fail with a different
message.
"""

from __future__ import annotations

import asyncio

from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.platform.bootstrap import default_registry, seed_registered_domains
from virtualcell.platform.contracts import ReasoningQuery, ReasoningResponse
from virtualcell.platform.packs.adipogenesis import PACK_ID

PINNED_PACK_ID = "adipogenesis.minimal.v1"

ASSESS = {
    "domain": "adipogenesis",
    "task": "assess_state",
    "experiment": {"PPARG": "high", "CEBPA": "high", "lipid_accumulation": "high"},
}
MECHANISM = {"domain": "adipogenesis", "task": "explain_mechanism", "experiment": {}}


def _service(payload: dict) -> ReasoningResponse:
    store = InMemoryKnowledgeStore()
    seed_registered_domains(store)
    from virtualcell.platform.service import ReasoningService

    service = ReasoningService(store, default_registry())
    return asyncio.run(service.query(ReasoningQuery.model_validate(payload)))


def test_the_pack_identifier_callers_already_have_is_unchanged() -> None:
    """One fact, one test: the identifier on the wire is the one consumers already hold.

    Checked through the shipped service rather than by reading the constant, because what a
    consumer depends on is the value that *arrives*, and on both tasks — a rename that spared
    one route would still break the other.
    """
    assert PACK_ID == PINNED_PACK_ID  # the constant...
    for payload in (ASSESS, MECHANISM):  # ...and what actually ships, on every task
        assert _service(payload).provenance.pack == PINNED_PACK_ID
