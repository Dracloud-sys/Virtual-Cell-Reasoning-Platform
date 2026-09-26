"""The report's text form, as one function rather than a block inside the CLI.

It lived inside `_cmd_research`, which meant the only way to see a report as text was to
run the command — and the only way to see the *same* report as JSON was to run the command
again, which is a second model call, a second bill and a different answer. Two renderings
of one run are not worth two runs.

So the rendering is here, the CLI calls it, and anything else that holds a `ResearchReport`
can call it too and get byte-identical output. That last part is the point: an operator
comparing a text rendering against a JSON one has to be looking at one run, not two.
"""

from __future__ import annotations

from virtualcell.research.contracts import ResearchReport


def render_report_text(report: ResearchReport) -> str:
    """Everything the report holds, in the order a reader needs it.

    Nothing is abridged. `--format text` is the default, so what this omits is what most
    readers never see — and an earlier version dropped exactly the fields that carry the
    warnings: which evidence *disagrees* with a hypothesis, and where a hypothesis is
    expected to hold at all. A design without its controls is not a design, and an
    over-extension nobody prints is an over-extension nobody acts on.
    """
    out: list[str] = [f"Q: {report.question}\n-> {report.restated_question}\n"]

    if report.assumptions:
        out.append("Assumptions:")
        out.extend(f"  - {item}" for item in report.assumptions)
        out.append("")

    for hypothesis in report.hypotheses:
        cited = ", ".join(hypothesis.supporting_evidence_ids) or "nothing supplied"
        out.append(f"[{hypothesis.id}] ({hypothesis.support.value}) {hypothesis.statement}")
        out.append(f"     supported by: {cited}")
        if hypothesis.contradicting_evidence_ids:
            out.append(f"     contradicted by: {', '.join(hypothesis.contradicting_evidence_ids)}")
        if hypothesis.applicability:
            out.append(f"     applies to: {hypothesis.applicability}")
    out.append("")

    for experiment in report.experiments:
        out.append(f"[{experiment.id}] {experiment.design}")
        if experiment.discriminates:
            out.append(f"     tells apart: {', '.join(experiment.discriminates)}")
        if experiment.controls:
            out.append(f"     controls: {', '.join(experiment.controls)}")
        if experiment.measurements:
            out.append(f"     measures: {', '.join(experiment.measurements)}")
        if experiment.timepoints:
            out.append(f"     timepoints: {', '.join(experiment.timepoints)}")
        for branch in experiment.branches:
            out.append(f"     if {branch.outcome}: {branch.implication}")
        if experiment.priority_rationale:
            out.append(f"     why first: {experiment.priority_rationale}")

    if report.open_items:
        out.append("\nOpen:")
        out.extend(f"  - {item}" for item in report.open_items)

    if report.integrity:
        out.append("\nIntegrity findings (checkable defects, not a judgement of the biology):")
        out.extend(
            f"  ! [{finding.code}] {finding.where}: {finding.detail}"
            for finding in report.integrity
        )

    prov = report.provenance
    out.append(
        f"\nproduced by {prov.backend} "
        f"({prov.model_served or prov.model or 'model unrecorded'}), "
        f"prompt {prov.prompt_version}, "
        f"{prov.evidence_offered} evidence item(s) offered"
    )
    if prov.input_tokens is not None or prov.output_tokens is not None:
        line = (
            f"  {prov.model_calls} model call(s), "
            f"{prov.input_tokens} in / {prov.output_tokens} out, "
            f"stop_reason {prov.stop_reason!r}"
        )
        if prov.elapsed_seconds is not None:
            # Measured, and labelled as measured. The configured per-request timeout and
            # the retry ceiling are settings; neither predicts this number.
            line += f", took {prov.elapsed_seconds:.1f}s"
        out.append(line)
    return "\n".join(out)
