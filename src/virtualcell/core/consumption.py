"""Measurement-consumption transparency — what the reasoning did with what you submitted.

The gap this closes, recorded as finding 3 of PR16: a caller could submit a measurement and
get back a report **byte-identical** to not having submitted it. An unrecognised key was
accepted, preserved, and reached no reasoning; a typed axis handed in as ``unknown`` looked
exactly like one that drove the verdict. Nothing in a response distinguished a measurement
that was used from one that was ignored, so a user had no way to tell a silent typo from a
deliberate finding.

This module is the platform-wide **vocabulary** for that answer. It lives in ``core`` rather
than in ``platform`` for a structural reason, not a filing one: both the domain packs and the
canonical-experiment adapters need to speak it, and an adapter under ``agents`` importing from
``platform`` closes a dependency cycle (``platform.bootstrap`` imports the packs, which import
those adapters). ``core`` is the layer everything already depends on and which depends on
nothing, so the vocabulary belongs beside :mod:`virtualcell.core.evidence`.

It holds no biology:

* the *states* a submitted measurement can end up in — here, because a caller comparing two
  domains must read the same word to mean the same thing;
* *which* measurement is in which state — the domain pack's, because only the vertical knows
  that viability refines a call while lipid content decides one.

Two rules keep the ledger honest.

**Only submitted measurements appear.** An axis nobody sent is not "unconsumed", it is
absent, and the envelope already says so in ``missing_information``. Listing it here too
would make a gap look like a rejection.

**A flag is not a status.** ``USED_FOR_STATUS`` means the value contributed to the domain's
*verdict*. PR16 established that genomic stability and differentiation retention report
beside the status and never through it, so they are ``USED_FOR_GUIDANCE`` even though they
raise flags and change the recommended experiments. Collapsing the two would undo exactly
the separation PR16 was written to create.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class ConsumptionStatus(StrEnum):
    """What became of one submitted measurement.

    The order is deliberate: it runs from "this drove the answer" down to "this reached
    nothing", so a caller scanning a ledger reads the consequential entries first.
    """

    USED_FOR_STATUS = "used_for_status"
    """The value contributed to the domain's status verdict."""

    USED_FOR_GUIDANCE = "used_for_guidance"
    """The reasoning consulted the value, but not for the status — it fed flags, evidence,
    safety caveats, recommended validation or next experiments.

    This says the value *was read* for those purposes; it does not promise the value
    changed the output. Proving that would mean re-running the domain's rules with the
    value removed, which the pack must not do — packs declare policy, they never re-derive
    science."""

    NOT_APPLICABLE = "not_applicable"
    """Submitted and recognised, but this task or this reading has nothing to consult it
    for — a marker panel handed to a mechanism-explanation question, or an axis explicitly
    sent as ``unknown``."""

    UNSUPPORTED = "unsupported"
    """The domain does not recognise the name. The value is preserved on the input but
    reaches no reasoning. **This is the state that used to be invisible**, and the most
    common cause is a typo."""

    QUALITY_EXCLUDED = "quality_excluded"
    """Recognised, but acquisition quality kept it out of the reasoning — a canonical
    measurement whose QC verdict was not ``valid``. Distinct from ``NOT_APPLICABLE``: the
    platform wanted this value and could not trust it."""


_STATUS_BEARING = frozenset({ConsumptionStatus.USED_FOR_STATUS})

# States where the reasoning read the value, and so must be able to say what read it.
_CONSUMED = frozenset({ConsumptionStatus.USED_FOR_STATUS, ConsumptionStatus.USED_FOR_GUIDANCE})

# States that exist to explain an absence, and so must say why.
_MUST_EXPLAIN = frozenset(
    {
        ConsumptionStatus.NOT_APPLICABLE,
        ConsumptionStatus.UNSUPPORTED,
        ConsumptionStatus.QUALITY_EXCLUDED,
    }
)


class MeasurementConsumption(BaseModel):
    """One submitted measurement and what the reasoning did with it."""

    model_config = ConfigDict(frozen=True)

    submitted_as: str
    """Exactly the key the caller sent, so a typo is visible in the caller's own spelling."""

    canonical_name: str | None = None
    """The platform/domain name it resolved to.

    ``None`` **if and only if** the status is ``UNSUPPORTED``. That biconditional is the
    contract: a name the domain recognises resolved to something even when nothing read it,
    so ``not_applicable`` and ``quality_excluded`` carry it too. Leaving it empty there would
    make "we know this axis and had nothing to use it for" indistinguishable from "we have
    never heard of this", which is the single distinction the ledger exists to draw."""

    status: ConsumptionStatus

    used_for: list[str] = Field(default_factory=list)
    """The axes or purposes that read the value — ``candidate_status``,
    ``flag:functionality_compromised``, ``next_experiment``. Empty when nothing read it."""

    reason: str | None = None
    """Why the value did not reach the reasoning, in the caller's terms.

    Required on every non-consumed state and **forbidden on the consumed ones**: a value that
    was used has no "why not", and a reason sitting beside ``used_for_status`` would read as a
    caveat on a verdict that does not have one."""

    provenance: str | None = None
    """Where the value came from — ``query.experiment``, ``canonical_run:<run_id>``,
    ``observations[3]``. Auditable, and never evidence in itself."""

    @model_validator(mode="after")
    def _fields_must_agree_with_the_status(self) -> MeasurementConsumption:
        """Reject field combinations that contradict the state they claim to be in.

        Enforced on the model rather than in :class:`ConsumptionLedger` because this is a
        platform contract: anything that can construct a ``MeasurementConsumption`` — a
        future pack, a deserialised HTTP payload, a test fixture — must be unable to express
        ``unsupported`` with a canonical name, or ``used_for_status`` with nothing that used
        it. A contract that holds only when the convenience builder is used is a convention,
        not a contract.

        Same rule the platform applies elsewhere: ``LiteratureOutcome`` refuses evidence on a
        failed retrieval structurally rather than by asking callers to remember.
        """
        if self.status is ConsumptionStatus.UNSUPPORTED:
            if self.canonical_name is not None:
                raise ValueError(
                    "an unsupported measurement resolved to no canonical name, so "
                    f"canonical_name must be None (got {self.canonical_name!r})"
                )
        elif self.canonical_name is None:
            raise ValueError(
                f"status {self.status.value!r} means the name was recognised, so "
                "canonical_name is required"
            )

        if self.status in _CONSUMED:
            if not self.used_for:
                raise ValueError(
                    f"status {self.status.value!r} claims the value was read; used_for must "
                    "name at least one axis or purpose that read it"
                )
            if self.reason is not None:
                raise ValueError(
                    f"status {self.status.value!r} means the value was used; 'reason' "
                    "explains why a value was *not* used and must be omitted"
                )
        else:
            if self.used_for:
                raise ValueError(
                    f"status {self.status.value!r} means nothing read the value, so "
                    f"used_for must be empty (got {self.used_for})"
                )
            if not (self.reason or "").strip():
                raise ValueError(
                    f"status {self.status.value!r} explains an absence and must say why; "
                    "'reason' is required and cannot be blank"
                )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def affected_status(self) -> bool:
        """Whether this value could have moved the domain's verdict.

        Derived rather than stored so it cannot contradict ``status`` — which is also why
        "guidance never affects the status" needs no validator: it is not representable.
        One authority per fact, the same rule PR16 applied to genomic stability and karyotype.
        """
        return self.status in _STATUS_BEARING


class ConsumptionReport(BaseModel):
    """Every submitted measurement, and what became of each.

    Defaults to empty, so a domain that has not declared a policy yet reports nothing rather
    than reporting something wrong — and every existing caller keeps working unchanged.
    """

    entries: list[MeasurementConsumption] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unsupported(self) -> list[str]:
        """Names the domain did not recognise. Promoted to the top level because it is the
        one state a caller should almost always act on: it usually means a typo, and it is
        the state that was previously invisible."""
        return [e.submitted_as for e in self.entries if e.status is ConsumptionStatus.UNSUPPORTED]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_inputs(self) -> list[str]:
        """Canonical names that contributed to the verdict — the auditable answer to
        "what was this call actually based on?"."""
        return [e.canonical_name or e.submitted_as for e in self.entries if e.affected_status]

    def by_status(self, status: ConsumptionStatus) -> list[MeasurementConsumption]:
        return [entry for entry in self.entries if entry.status is status]


class ConsumptionLedger:
    """Builder a domain pack fills while adapting a request.

    Deliberately not clever. It records what the pack declares and preserves submission
    order; it computes nothing, infers nothing, and knows no domain. Order is the caller's
    own, so an entry is easy to find against the request that produced it.
    """

    def __init__(self, *, provenance: str | None = None) -> None:
        self._entries: list[MeasurementConsumption] = []
        self._default_provenance = provenance

    def record(
        self,
        submitted_as: str,
        status: ConsumptionStatus,
        *,
        canonical_name: str | None = None,
        used_for: list[str] | None = None,
        reason: str | None = None,
        provenance: str | None = None,
    ) -> ConsumptionLedger:
        """Record one measurement. Returns self so a pack can chain."""
        self._entries.append(
            MeasurementConsumption(
                submitted_as=submitted_as,
                canonical_name=canonical_name,
                status=status,
                used_for=list(used_for or []),
                reason=reason,
                provenance=provenance or self._default_provenance,
            )
        )
        return self

    def used_for_status(
        self, submitted_as: str, *, canonical_name: str | None = None, used_for: list[str], **kw
    ) -> ConsumptionLedger:
        return self.record(
            submitted_as,
            ConsumptionStatus.USED_FOR_STATUS,
            canonical_name=canonical_name or submitted_as,
            used_for=used_for,
            **kw,
        )

    def used_for_guidance(
        self, submitted_as: str, *, canonical_name: str | None = None, used_for: list[str], **kw
    ) -> ConsumptionLedger:
        return self.record(
            submitted_as,
            ConsumptionStatus.USED_FOR_GUIDANCE,
            canonical_name=canonical_name or submitted_as,
            used_for=used_for,
            **kw,
        )

    def not_applicable(
        self, submitted_as: str, *, reason: str, canonical_name: str | None = None, **kw
    ) -> ConsumptionLedger:
        # Defaults to the submitted name: the domain recognised this key, and saying so is
        # what separates "nothing to use it for" from "never heard of it".
        return self.record(
            submitted_as,
            ConsumptionStatus.NOT_APPLICABLE,
            canonical_name=canonical_name or submitted_as,
            reason=reason,
            **kw,
        )

    def unsupported(
        self, submitted_as: str, *, reason: str | None = None, **kw
    ) -> ConsumptionLedger:
        return self.record(
            submitted_as,
            ConsumptionStatus.UNSUPPORTED,
            reason=reason or "this domain does not recognise the measurement name",
            **kw,
        )

    def quality_excluded(
        self, submitted_as: str, *, reason: str, canonical_name: str | None = None, **kw
    ) -> ConsumptionLedger:
        # Provenance is not forced here. On the canonical path it is always available and
        # always set (`run_consumption` names the observation index), but a general model
        # that refused an entry without it would block any producer that cannot supply one.
        return self.record(
            submitted_as,
            ConsumptionStatus.QUALITY_EXCLUDED,
            canonical_name=canonical_name or submitted_as,
            reason=reason,
            **kw,
        )

    def report(self) -> ConsumptionReport:
        return ConsumptionReport(entries=list(self._entries))
