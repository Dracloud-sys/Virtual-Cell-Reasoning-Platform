"""The model-observation link cases: synthetic contract cases T1-T8 and the ERK regression.

Every model result comes from `run_logic_model` (view "window") on `build_server()`, or, for the
ERK case, from the stored window record of `logic_window_v0` (the model is not re-run). Every
comparison is `compare_model_observation` on `build_server()`. The tests import the builders
from here, so the cases recorded and the cases tested are the same inputs.

    python cases.py        # writes results.json
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from virtualcell.mcp.server import build_server

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent
REPO = HERE.parents[2]

RULE = {
    "comparison": "ratio",
    "increase_at_or_above": 1.5,
    "decrease_at_or_below": 0.67,
    "no_change_between": [0.9, 1.1],
    "declared_by": "researcher",
    "basis": "synthetic contract rule for these tests; not a biological threshold",
}


def call(server, tool: str, args: dict) -> dict:
    result = asyncio.run(server.call_tool(tool, args))
    if result.is_error:
        raise RuntimeError(" ".join(getattr(c, "text", "") for c in result.content))
    return result.structured_content


# --- synthetic model results (product path) ----------------------------------------------- #


def _sc(name, initial, inputs=None, clamps=None):
    return {"name": name, "initial": initial, "inputs": inputs or {}, "clamps": clamps or []}


def _on(value):
    return [{"start": 0, "end": None, "value": value}]


MODELS = {
    "follow": {
        "id": "follow",
        "components": [
            {"id": "U", "kind": "input"},
            {"id": "V", "kind": "input"},
            {"id": "X", "kind": "internal"},
        ],
        "rules": [{"id": "rX", "target": "X", "expr": {"var": "U"}}],
    },
    "hold": {
        "id": "hold",
        "components": [{"id": "X", "kind": "internal"}, {"id": "Q", "kind": "internal"}],
        "rules": [
            {"id": "rX", "target": "X", "expr": {"var": "X"}},
            {"id": "rQ", "target": "Q", "expr": {"var": "Q"}},
        ],
    },
    "norule": {"id": "norule", "components": [{"id": "Z", "kind": "internal"}], "rules": []},
}


def model_results(server) -> dict[str, dict]:
    """Window results the cases read. Each is one run_logic_model call."""

    def run(model, scenario, baseline, target, max_cases=256):
        args = {
            "model": MODELS[model],
            "scenario": scenario,
            "steps": 4,
            "view": "window",
            "window": {"first": 2, "last": 4, "targets": [target]},
            "max_cases": max_cases,
        }
        if baseline is not None:
            args["baseline"] = baseline
        return call(server, "run_logic_model", args)

    x0 = {"X": False}
    return {
        # X follows U: treated U on, baseline U off -> all_active vs all_inactive, {increase}.
        "up": run(
            "follow",
            _sc("T", x0, {"U": _on(True), "V": _on(True)}),
            _sc("B", x0, {"U": _on(False), "V": _on(True)}),
            "X",
        ),
        # Both sides U on, only V differs (X does not read V) -> {no_change}.
        "same": run(
            "follow",
            _sc("T", x0, {"U": _on(True), "V": _on(True)}),
            _sc("B", x0, {"U": _on(True), "V": _on(False)}),
            "X",
        ),
        # Scenario U off: X all_inactive (state claim).
        "off": run("follow", _sc("T", x0, {"U": _on(False), "V": _on(True)}), None, "X"),
        # X holds an unknown start; treated clamps X on -> X=0: {increase}; X=1: {no_change}.
        "multi": run(
            "hold",
            _sc(
                "T",
                {"X": "unknown", "Q": False},
                None,
                [{"target": "X", "value": True, "start": 0}],
            ),
            _sc("B", {"X": "unknown", "Q": False}),
            "X",
        ),
        # As multi, with a second unknown and only one case explored.
        "partial": run(
            "hold",
            _sc(
                "T",
                {"X": "unknown", "Q": "unknown"},
                None,
                [{"target": "X", "value": True, "start": 0}],
            ),
            _sc("B", {"X": "unknown", "Q": "unknown"}),
            "X",
            max_cases=1,
        ),
        # Z has no rule: not computed in the window.
        "nocomp": run("norule", _sc("T", {"Z": True}), None, "Z"),
    }


# --- synthetic observations ----------------------------------------------------------------- #


def run_record(
    arms: list[tuple[dict, list[Any]]],
    *,
    name: str = "signal",
    unit: str = "ratio",
    run_id: str = "synthetic:1",
    days: list[float] | None = None,
) -> dict:
    """One ExperimentRun: each arm's conditions with its readings, one observation per reading."""
    observations = []
    for i, (conditions, values) in enumerate(arms):
        for j, v in enumerate(values):
            quality, value = ("valid", v)
            if isinstance(v, str):
                quality, value = v, None
            observations.append(
                {
                    "observation_id": f"o{i}-{j}",
                    "time_point": {
                        "kind": "elapsed_time",
                        "value": (days[i] if days else 1.0),
                        "unit": "day",
                    },
                    "conditions": conditions,
                    "measurements": [
                        {"name": name, "value": value, "unit": unit, "quality": quality}
                    ],
                }
            )
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "provenance": {
            "origin_kind": "experiment",
            "acquisition_mode": "manual",
            "method": "synthetic",
            "recorded_at": "2026-10-07T00:00:00Z",
        },
        "observations": observations,
    }


def mapping(**kw) -> dict:
    base = {
        "experiment_id": "E",
        "readout": "signal",
        "measurement_name": "signal",
        "unit": "ratio",
        "treatment": {"arm": "T"},
        "reference": {"arm": "B"},
        "versus": "B",
        "rule": RULE,
    }
    base.update(kw)
    return base


def link(result: dict, *, claim="change", table=None, target=None, **kw) -> dict:
    corr = {
        "table": table if table is not None else [],
        "window_correspondence": "synthetic: the window stands for the measured time point",
        "baseline_stands_for": "B" if claim == "change" else None,
        "applies_to_experiment_ids": ["E"],
        "basis": "synthetic contract case",
        "stated_by": "researcher",
    }
    corr.update(kw.pop("correspondence", {}))
    w = result["window"]["request"]
    return {
        "id": kw.pop("id", "L"),
        "model": {
            "run_sha256": result["run_sha256"],
            "model_sha256": result["model_sha256"],
            "scenario": result["scenario"]["name"],
            "baseline": result["baseline"]["name"] if result["baseline"] else None,
            "window": {"first": w["first"], "last": w["last"]},
            "target": target or w["targets"][0],
            "claim": claim,
        },
        "observation": kw.pop("observation", mapping()),
        "correspondence": corr,
        "hypothesis_ids": ["H1"],
        "experiment_ids": ["E"],
        **kw,
    }


SAME = [{"model_value": v, "observed_value": v} for v in ("increase", "decrease", "no_change")]
UP = run_record([({"arm": "T"}, [2.0, 2.2]), ({"arm": "B"}, [1.0])])
DOWN = run_record([({"arm": "T"}, [0.5, 0.6]), ({"arm": "B"}, [1.0])])


def synthetic_cases(server) -> dict[str, dict]:
    r = model_results(server)
    vehicle = {
        "plan_reference": "vehicle",
        "observed_conditions": {"arm": "ctrl"},
        "applies_to": ["E"],
        "basis": "synthetic: ctrl is the vehicle arm",
        "stated_by": "host",
    }
    return {
        "T1_consistent": {
            "model_result": r["up"],
            "runs": [UP],
            "link": link(r["up"], table=SAME),
        },
        "T2_inconsistent": {
            "model_result": r["up"],
            "runs": [DOWN],
            "link": link(r["up"], table=SAME),
        },
        "T3_partial": {
            "model_result": r["multi"],
            "runs": [UP],
            "link": link(r["multi"], table=SAME),
        },
        "T4_meaning": {
            "model_result": r["same"],
            "runs": [UP],
            "link": link(
                r["same"], table=[{"model_value": "increase", "observed_value": "increase"}]
            ),
        },
        "T4b_magnitude": {
            "model_result": r["same"],
            "runs": [UP],
            "link": link(r["same"], table=SAME, correspondence={"asks": "magnitude"}),
        },
        "T5_detection": {
            "model_result": r["off"],
            "runs": [run_record([({"arm": "T"}, ["below_detection", "below_detection"])])],
            "link": link(
                r["off"],
                claim="state",
                table=[{"model_value": "active", "observed_value": "present"}],
                observation=mapping(reference=None, versus=None, rule=None),
            ),
        },
        "T6_reference_roles": {
            "model_result": r["up"],
            "runs": [
                run_record(
                    [
                        ({"agent": "U0126"}, [2.0]),
                        ({"agent": "DMSO"}, [1.0]),
                        ({"agent": "PBS"}, [1.0]),
                        ({"agent": "U0126"}, [0.2]),
                    ],
                    unit="ratio_to_PBS",
                    days=[1.0, 1.0, 1.0, 2.0],
                )
            ],
            "link": link(
                r["up"],
                table=SAME,
                observation=mapping(
                    unit="ratio_to_PBS",
                    treatment={"agent": "U0126"},
                    reference={"agent": "DMSO"},
                    versus="DMSO",
                    time_point={"kind": "elapsed_time", "value": 1.0, "unit": "day"},
                ),
                correspondence={"baseline_stands_for": "DMSO"},
            ),
        },
        "T6b_host_proposed_reference": {
            "model_result": r["up"],
            "runs": [run_record([({"arm": "T"}, [2.0]), ({"arm": "ctrl"}, [1.0])])],
            "link": link(
                r["up"],
                table=SAME,
                observation=mapping(
                    reference={"arm": "ctrl"}, versus="vehicle", reference_correspondence=vehicle
                ),
                correspondence={"baseline_stands_for": "vehicle"},
            ),
        },
        "T6c_baseline_differs": {
            "model_result": r["up"],
            "runs": [UP],
            "link": link(r["up"], table=SAME, correspondence={"baseline_stands_for": "untreated"}),
        },
        "T7_left_out": {
            "model_result": r["up"],
            "runs": [
                run_record([({"arm": "T"}, [2.0, "excluded", "missing"]), ({"arm": "B"}, [1.0])])
            ],
            "link": link(r["up"], table=SAME),
        },
        "T7b_no_rule": {
            "model_result": r["up"],
            "runs": [UP],
            "link": link(r["up"], table=SAME, observation=mapping(rule=None)),
        },
        "T7c_partial_exploration": {
            "model_result": r["partial"],
            "runs": [UP],
            "link": link(r["partial"], table=SAME),
        },
        "T7d_not_computed": {
            "model_result": r["nocomp"],
            "runs": [run_record([({"arm": "T"}, [2.0])])],
            "link": link(
                r["nocomp"],
                claim="state",
                table=[
                    {"model_value": "active", "observed_value": "present"},
                    {"model_value": "inactive", "observed_value": "absent"},
                ],
                observation=mapping(reference=None, versus=None, rule=None),
            ),
        },
    }


# --- the ERK regression (stored records; no re-run, no new data) --------------------------- #


def erk_cases() -> dict[str, dict]:
    window = json.loads((DOCS / "logic_window_v0" / "window_results.json").read_text())
    stored = json.loads((DOCS / "logic_biology_v1" / "results.json").read_text())
    case = json.loads((DOCS / "logic_biology_v1" / "prereg" / "case.json").read_text())
    extracted = json.loads((DOCS / "erk_pmek_measurement_v0" / "extracted.json").read_text())
    key = "M2_feedback_on_RAS/KRAS"
    pair = case["comparisons"]["KRAS"]
    model_result = {
        "model_id": "M2_feedback_on_RAS",
        "model_sha256": window[key]["model_sha256"],
        "run_sha256": window[key]["run_sha256"],
        "scenario": pair["scenario"],
        "baseline": pair["baseline"],
        "cases_explored": stored[key]["cases_explored"],
        "cases_total": stored[key]["cases_total"],
        "exploration_complete": stored[key]["exploration_complete"],
        "window": window[key]["window"],
    }
    rows = {r["line"]: r for r in extracted["fig6B"]["rows"]}
    picked = [rows[14], rows[6], rows[19]]  # HCT116: U0126 50 uM, DMSO, PBS (lines in df6B)
    observations = []
    for r in picked:
        conditions = {"cell_line": r["cell_line"], "agent": r["agent"]}
        if r["agent"] == "U0126":
            conditions["concentration_uM"] = r["concentration_uM"]
        observations.append(
            {
                "observation_id": f"df6B-line-{r['line']}",
                # 24 h: from the results text ("24 h post-inhibition"); the file states no time.
                "time_point": {"kind": "elapsed_time", "value": 24.0, "unit": "hour"},
                "conditions": conditions,
                "measurements": [
                    {
                        "name": "pMek1_S217_S221",
                        "value": float(r["value"]),
                        "unit": "ratio_to_PBS",
                        "quality": "valid",
                    }
                ],
            }
        )
    run = {
        "schema_version": "1.0",
        "run_id": "literature:pmc3130559-fig6b-hct116",
        "provenance": {
            "origin_kind": "experiment",
            "acquisition_mode": "imported",
            "method": "Bio-Plex",
            "source_system": "PMC3130559 msb201127-df6B.txt (author-normalised, ratio to PBS)",
        },
        "observations": observations,
    }
    observation = {
        "experiment_id": "fig6B",
        "readout": "pMEK1_S217_S221_BioPlex",
        "measurement_name": "pMek1_S217_S221",
        "unit": "ratio_to_PBS",
        "treatment": {"cell_line": "HCT116", "agent": "U0126", "concentration_uM": "50"},
        "reference": {"cell_line": "HCT116", "agent": "DMSO"},
        "versus": "DMSO",
    }
    base = {
        "id": "erk-m2-kras-pmek",
        "model": {
            "run_sha256": model_result["run_sha256"],
            "model_sha256": model_result["model_sha256"],
            "scenario": pair["scenario"],
            "baseline": pair["baseline"],
            "window": {"first": 18, "last": 24},
            "target": "pMEK1_S217_S221_BioPlex",
            "claim": "change",
        },
        "observation": observation,
        "readout_spec": {"name": "pMEK1_S217_S221_BioPlex", "assay": "Bio-Plex"},
        "experiment_ids": ["fig6B"],
    }
    corr = {
        "window_correspondence": (
            "host assumption, unverified: logical steps 18-24 stand for the 24 h measurement"
        ),
        "baseline_stands_for": "DMSO",
        "applies_to_experiment_ids": ["fig6B"],
        "basis": "erk_pmek_measurement_v0 review_r1: DMSO is a comparison arm; PBS is the "
        "normalisation reference",
        "assumptions": ["the model's MEKi input stands for 50 uM U0126 (post hoc choice)"],
        "stated_by": "host",
    }
    return {
        "E1_magnitude": {
            "model_result": model_result,
            "runs": [run],
            "link": {**base, "correspondence": {**corr, "asks": "magnitude", "table": []}},
        },
        "E2_category": {
            "model_result": model_result,
            "runs": [run],
            "link": {
                **base,
                "correspondence": {
                    **corr,
                    "asks": "category",
                    "table": [{"model_value": "increase", "observed_value": "increase"}],
                },
            },
        },
    }


def summary(out: dict) -> dict:
    return {
        k: out[k]
        for k in (
            "comparison_id",
            "comparability",
            "reasons",
            "needs",
            "relation",
            "result",
            "explored_result",
            "if_accepted",
            "observation_meaning",
            "correspondence_accepted",
            "scientific_validity_checked",
        )
    } | {
        "model_values": out["model_claim"]["model_values"],
        "model_applies_to": out["model_claim"]["applies_to"],
        "observed": out["observation"]["observed"],
        "observation_status": out["observation"]["status"],
        "observation_reasons": out["observation"]["reasons"],
        "treatment_values": out["observation"]["treatment_values"],
        "reference_values": out["observation"]["reference_values"],
        "left_out": out["observation"]["left_out"],
    }


def main() -> None:
    server = build_server()
    cases = synthetic_cases(server) | erk_cases()
    results = {
        name: summary(call(server, "compare_model_observation", args))
        for name, args in cases.items()
    }
    (HERE / "results.json").write_text(
        json.dumps(results, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "src"],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    ).stdout.strip()
    run = {
        "code": {"git_head": head, "src_uncommitted_changes": bool(dirty)},
        "results_sha256": hashlib.sha256((HERE / "results.json").read_bytes()).hexdigest(),
        "inputs_sha256": hashlib.sha256(
            json.dumps(cases, sort_keys=True, default=str).encode()
        ).hexdigest(),
        "cases": len(cases),
    }
    (HERE / "run.json").write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {k: (v["comparability"], v["result"], v["relation"]) for k, v in results.items()},
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
