"""Safety regressions across the PR11 boundary.

The generic envelope must not become a place where PR10's epistemic safeguards quietly
weaken: observation must not become causation, Q6 must not infer safety, Q9's wording
rules must hold, and a provider failure must never arrive as scientific support.
"""

from __future__ import annotations

import asyncio

import pytest

from virtualcell.core.evidence import EvidenceTier
from virtualcell.knowledge.backends.memory import InMemoryKnowledgeStore
from virtualcell.knowledge.sources.base import load_into
from virtualcell.knowledge.sources.immortalization_seed import ImmortalizationSeedSource
from virtualcell.literature.providers.base import ProviderError
from virtualcell.platform.bootstrap import default_registry
from virtualcell.platform.contracts import LiteratureStatus, ReasoningQuery
from virtualcell.platform.domains import UnknownDomainError
from virtualcell.platform.service import ReasoningService

_CAUSAL = ("causes", "proves", "demonstrates that", "establishes that")
_FORBIDDEN_P53 = ("without p53", "p53 loss", "p53 knockout", "p53 deletion")
_UNSAFE_SAFETY = ("non-oncogenic", "non oncogenic", "tumor-free", "tumour-free", "proven safe")


def _store() -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    load_into(ImmortalizationSeedSource(), store)
    return store


def _query(payload: dict, **service_kw):
    service = ReasoningService(_store(), default_registry(), **service_kw)
    return asyncio.run(service.query(ReasoningQuery.model_validate(payload)))


def _asserted(response) -> str:
    """Only the fields that make biological assertions (PR10b scope)."""
    return " ".join(
        [
            response.summary,
            *(c.statement for c in response.supporting_evidence),
            *(c.statement for c in response.contradicting_evidence),
        ]
    ).lower()


# --- observation is not causation --------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"domain": "immortalization", "task": "handle_hypothesis", "experiment": {}},
        {
            "domain": "immortalization",
            "task": "assess_state",
            "experiment": {"intent": "immortalization_assessment", "PDL_trend": "increasing"},
        },
    ],
)
def test_observational_evidence_is_not_promoted_to_causal(payload: dict) -> None:
    response = _query(payload)
    asserted = _asserted(response)
    for phrase in _CAUSAL:
        assert phrase not in asserted, f"causal overstatement: {phrase!r}"
    # Any weak mechanistic link stays below established after crossing the envelope.
    weak = [
        link
        for link in response.mechanistic_links
        if any("associated_with" in step or "suggests" in step for step in link.path)
    ]
    assert all(link.tier is not EvidenceTier.ESTABLISHED for link in weak)


# --- Q6: safety is validated, never inferred ---------------------------------


def test_q6_does_not_infer_non_oncogenicity() -> None:
    response = _query(
        {
            "domain": "immortalization",
            "task": "explain_mechanism",
            "experiment": {"construct": "TERT_plus_CDK4"},
        }
    )
    asserted = _asserted(response)
    for phrase in _UNSAFE_SAFETY:
        assert phrase not in asserted, f"Q6 asserts unsupported safety: {phrase!r}"
    guidance = " ".join([*response.limitations, *response.recommended_validation]).lower()
    assert "non-tumorigenicity" in guidance
    assert "viral oncogene" in guidance  # the defensible mechanistic distinction only


def test_q6_keeps_safety_validation_distinct_from_other_axes() -> None:
    """Tumorigenicity, genomic stability, differentiation/function and long-term PDL are
    four separate asks — collapsing them would let one stand in for another."""
    response = _query(
        {
            "domain": "immortalization",
            "task": "explain_mechanism",
            "experiment": {"construct": "TERT_plus_CDK4"},
        }
    )
    asked = " ".join(
        [*response.recommended_validation, *response.recommended_next_experiments]
    ).lower()
    guidance = " ".join(response.limitations).lower()

    assert "non-tumorigenicity" in guidance  # safety, stated as unvalidated
    assert "genomic stability" in asked or "karyotype" in asked
    assert "differentiation" in asked or "functionality" in asked
    assert "long-term" in asked or "proliferative" in asked
    # Genomic stability must not be presented as covering tumorigenicity.
    assert "genomic stability" not in guidance.split("non-tumorigenicity")[0][-40:]


# --- Q9: wording rules survive the envelope ----------------------------------


def test_q9_assertion_fields_carry_no_forbidden_p53_phrasing() -> None:
    response = _query({"domain": "immortalization", "task": "handle_hypothesis", "experiment": {}})
    asserted = _asserted(response)
    for phrase in _FORBIDDEN_P53:
        assert phrase not in asserted, f"Q9 asserts forbidden phrasing: {phrase!r}"
    assert "p53-independent" in asserted  # the correct framing is still stated
    assert response.decision_support.status == "insufficient_evidence"


def test_q9_guidance_may_quote_a_forbidden_phrase_to_forbid_it() -> None:
    # The PR10b scorer correction, preserved: prohibiting a phrase is not asserting it.
    response = _query({"domain": "immortalization", "task": "handle_hypothesis", "experiment": {}})
    guidance = " ".join([*response.limitations, *response.overinterpretation_risks]).lower()
    assert "p53 loss" in guidance  # the guidance is present...
    assert "p53 loss" not in _asserted(response)  # ...and is not an assertion


def test_q9_established_context_and_hypotheses_stay_separated() -> None:
    response = _query({"domain": "immortalization", "task": "handle_hypothesis", "experiment": {}})
    tiers = [c.tier for c in response.supporting_evidence]
    assert EvidenceTier.ESTABLISHED in tiers and EvidenceTier.HYPOTHESIS in tiers
    # The reported spontaneous route stays a cited hypothesis, never established.
    spontaneous = [
        c for c in response.supporting_evidence if "p53-independent" in c.statement.lower()
    ]
    assert spontaneous and all(c.tier is EvidenceTier.HYPOTHESIS for c in spontaneous)
    assert all(c.citations for c in spontaneous)


# --- literature: a failure is never evidence ---------------------------------


class _FailingAgent:
    """A literature agent whose provider is down."""

    provider = type("P", (), {"name": "fake"})()

    async def run(self, inputs):
        raise ProviderError("provider unavailable")


class _TimingOutAgent:
    provider = type("P", (), {"name": "fake"})()

    async def run(self, inputs):
        raise TimeoutError("provider timed out")


def test_literature_disabled_performs_no_retrieval() -> None:
    class _Explode:
        provider = None

        async def run(self, inputs):  # pragma: no cover - must never be called
            raise AssertionError("literature must not be consulted when disabled")

    response = _query(
        {
            "domain": "immortalization",
            "task": "explain_mechanism",
            "experiment": {"construct": "TERT_only"},
            "allow_literature": False,
        },
        literature_agent=_Explode(),
    )
    assert response.literature.status is LiteratureStatus.NOT_REQUESTED
    assert response.literature.evidence == []


def test_requested_but_unwired_literature_is_unavailable_not_empty() -> None:
    response = _query(
        {
            "domain": "immortalization",
            "task": "explain_mechanism",
            "experiment": {"construct": "TERT_only"},
            "allow_literature": True,
        }
    )
    # "We could not look" must be distinguishable from "we looked and found nothing".
    assert response.literature.status is LiteratureStatus.UNAVAILABLE
    assert response.literature.status is not LiteratureStatus.ZERO_RESULTS
    assert response.literature.evidence == []


@pytest.mark.parametrize(
    "agent,expected",
    [
        (_FailingAgent(), LiteratureStatus.PROVIDER_ERROR),
        (_TimingOutAgent(), LiteratureStatus.TIMEOUT),
    ],
)
def test_provider_failure_never_becomes_evidence(agent, expected) -> None:
    response = _query(
        {
            "domain": "immortalization",
            "task": "explain_mechanism",
            "experiment": {"construct": "TERT_only"},
            "allow_literature": True,
            "target_measurements": ["TERT"],
        },
        literature_agent=agent,
    )
    assert response.literature.status is expected
    assert response.literature.evidence == []
    # The failure must not leak into the domain's scientific evidence either.
    assert all("provider" not in c.statement.lower() for c in response.supporting_evidence)
    # And the deterministic scientific content is still returned.
    assert response.summary and response.supporting_evidence


def _real_agent(provider):
    """The real LiteratureDiscoveryAgent, which catches ProviderError internally."""
    from virtualcell.agents.literature_discovery.agent import LiteratureDiscoveryAgent
    from virtualcell.core.agent import AgentContext

    return LiteratureDiscoveryAgent(AgentContext(services={"literature_provider": provider}))


class _DownProvider:
    """A provider whose search fails — the realistic outage the agent absorbs."""

    name = "fake"

    def search(self, query):
        raise ProviderError("search endpoint unavailable")

    def fetch_record(self, identifier):  # pragma: no cover - unused
        raise NotImplementedError

    def fetch_open_full_text(self, identifier):  # pragma: no cover - unused
        return None


def test_agent_absorbed_provider_error_is_still_reported_as_failure() -> None:
    """The bug this guards: the discovery agent catches ProviderError and returns a
    bundle, so the failure is *not* an exception here. It must still be reported as a
    provider error, never as a genuine zero-result search."""
    response = _query(
        {
            "domain": "immortalization",
            "task": "explain_mechanism",
            "experiment": {"construct": "TERT_only"},
            "allow_literature": True,
            "target_measurements": ["TERT"],
        },
        literature_agent=_real_agent(_DownProvider()),
    )
    assert response.literature.status is LiteratureStatus.PROVIDER_ERROR
    assert response.literature.status is not LiteratureStatus.ZERO_RESULTS
    assert response.literature.evidence == []


def test_explicit_literature_request_is_not_skipped_by_a_knowledge_base_hit() -> None:
    """The store is seeded with curated TERT, so a KB-first flow would never consult
    literature. An explicit request must still reach the provider."""
    response = _query(
        {
            "domain": "immortalization",
            "task": "explain_mechanism",
            "experiment": {"construct": "TERT_only"},
            "allow_literature": True,
            "target_measurements": ["TERT"],
        },
        literature_agent=_real_agent(_DownProvider()),
    )
    # Reaching PROVIDER_ERROR at all proves the provider was actually contacted.
    assert response.literature.status is LiteratureStatus.PROVIDER_ERROR


def test_successful_literature_stays_weak_and_separate(jats_xml) -> None:
    """On success the evidence arrives — but weak, cited, and never merged into the
    domain's own supporting evidence."""
    from datetime import UTC, datetime

    from virtualcell.literature.contracts import (
        ArticleIdentifier,
        ArticleRecord,
        LiteratureSearchResult,
        ProviderProvenance,
    )

    class _WorkingProvider:
        name = "fake"

        def search(self, query):
            record = ArticleRecord(
                identifiers=ArticleIdentifier(pmcid="PMC1", pmid="1", provider_id="PMC1"),
                title="TERT",
                abstract="TERT",
                is_open_access=True,
                has_full_text=True,
                provider="fake",
                retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
            )
            return LiteratureSearchResult(
                provenance=ProviderProvenance(
                    provider="fake",
                    query_sent="q",
                    retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
                    hit_count=1,
                ),
                articles=[record],
            )

        def fetch_record(self, identifier):  # pragma: no cover - unused
            raise NotImplementedError

        def fetch_open_full_text(self, identifier):
            return jats_xml

    response = _query(
        {
            "domain": "immortalization",
            "task": "explain_mechanism",
            "experiment": {"construct": "TERT_only"},
            "allow_literature": True,
            "target_measurements": ["TERT"],
        },
        literature_agent=_real_agent(_WorkingProvider()),
    )

    assert response.literature.status is LiteratureStatus.SUCCESS
    assert response.literature.evidence
    # Weak by construction, with citations, and NOT mixed into the domain's evidence.
    assert all(c.tier is EvidenceTier.HYPOTHESIS for c in response.literature.evidence)
    assert all(c.citations for c in response.literature.evidence)
    domain_statements = {c.statement for c in response.supporting_evidence}
    assert not domain_statements & {c.statement for c in response.literature.evidence}


def test_provider_failure_leaves_scientific_content_deterministic() -> None:
    payload = {
        "domain": "immortalization",
        "task": "explain_mechanism",
        "experiment": {"construct": "TERT_only"},
        "allow_literature": True,
    }
    failed = _query(payload, literature_agent=_FailingAgent())
    offline = _query({**payload, "allow_literature": False})
    assert failed.summary == offline.summary
    assert [c.model_dump() for c in failed.supporting_evidence] == [
        c.model_dump() for c in offline.supporting_evidence
    ]


# --- domain isolation ---------------------------------------------------------


def test_unsupported_domain_cannot_use_immortalization_reasoning() -> None:
    with pytest.raises(UnknownDomainError):
        _query(
            {
                "domain": "adipogenesis",
                "task": "assess_state",
                "experiment": {"intent": "immortalization_assessment"},
            }
        )


def test_explanation_level_does_not_alter_scientific_content() -> None:
    """PR11 limitation, pinned: the level is provenance, not a content switch — so it
    cannot silently soften claims for a non-expert audience."""
    base = {
        "domain": "immortalization",
        "task": "explain_mechanism",
        "experiment": {"construct": "TERT_plus_CDK4"},
    }
    novice = _query({**base, "explanation_level": "novice"})
    expert = _query({**base, "explanation_level": "expert"})

    assert novice.summary == expert.summary
    assert [c.model_dump() for c in novice.supporting_evidence] == [
        c.model_dump() for c in expert.supporting_evidence
    ]
    assert novice.limitations == expert.limitations
    # But it is preserved for later layers.
    assert novice.provenance.explanation_level.value == "novice"
    assert expert.provenance.explanation_level.value == "expert"
