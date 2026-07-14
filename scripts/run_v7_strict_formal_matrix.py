# -*- coding: utf-8 -*-
"""Orchestrate the complete IJDRR v7 strict formal experiment matrix.

This module is deliberately a thin orchestration layer.  It does not
reimplement model logic: every stage delegates to an existing, provenance-
aware runner and then validates the resulting evidence contract.

The default matrix contains 640 model invocations and 1,130 realizations:

* baseline:   3 cities x 10 seeds, graph off/on;
* iia:        3 cities x 5 alpha values x 10 seeds, graph on only;
* population: 3 cities x 5 population sizes x 5 seeds, graph off/on;
* home:       3 cities x 2 home distributions x 5 seeds, graph off/on;
* e2:         3 cities x 11 presets x 10 seeds, graph off/on;
* event5:     5 unique Xiamen specifications x 5 seeds, graph off/on.

Examples
--------
Plan the complete matrix without launching a simulation::

    python scripts/run_v7_strict_formal_matrix.py --dry-run

Resume selected stages::

    python scripts/run_v7_strict_formal_matrix.py \
        --stages baseline iia --resume

Legacy semantics are never formal evidence.  They require both a separate
output root and the explicit ``--mechanism-audit`` acknowledgement.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_WRAPPER = PROJECT_ROOT / ".venv" / "run_in_crowds_env.ps1"
DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT / "trace_output" / "IJDRR_v7_strict_formal"
)
MANIFEST_JSON = "formal_matrix_manifest.json"
MANIFEST_CSV = "formal_matrix_manifest.csv"
MANIFEST_SCHEMA_VERSION = 1
MODEL_CONTRACT_VERSION = "ijdrr_strict_v1"
MIN_METRIC_SCHEMA_VERSION = 4

STAGE_ORDER = ("baseline", "iia", "population", "home", "e2", "event5")
CITIES = (
    ("厦门市", "思明区"),
    ("沈阳市", "沈河区"),
    ("北京市", "东城区"),
)
BASELINE_SEEDS = tuple(range(42, 52))
N5_SEEDS = tuple(range(42, 47))
IIA_ALPHAS = (-7, -6, -5, -4, -3)
POPULATION_VALUES = (200, 500, 800, 1500, 3000)
HOME_DISTRIBUTIONS = ("poi", "uniform")
E2_PRESETS = (
    "none",
    "hard_switch",
    "soft_switch",
    "no_info_network",
    "distance_only_store",
    "no_inertia",
    "no_hysteresis",
    "no_outcome_feedback",
    "no_behavior_demo",
    "i1_minimal",
    "no_flee",
)
EVENT5_UNIQUE_SPECS = (
    "opinion_auto__stress_sqrt",
    "opinion_off__stress_sqrt",
    "opinion_on__stress_sqrt",
    "opinion_auto__stress_log",
    "opinion_auto__stress_linear",
)


@dataclass(frozen=True)
class StagePlan:
    """One auditable formal-matrix stage."""

    name: str
    design: str
    expected_invocations: int
    expected_realizations: int
    output_path: Path
    command: tuple[str, ...]
    validation_mode: str
    reuse_relation: str


def _python_command(script_name: str, *arguments: str) -> tuple[str, ...]:
    if ENV_WRAPPER.exists():
        return (
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ENV_WRAPPER),
            str(PROJECT_ROOT / "scripts" / script_name),
            *arguments,
        )
    return (
        sys.executable,
        "-u",
        str(PROJECT_ROOT / "scripts" / script_name),
        *arguments,
    )


def build_stage_plans(
    output_root: Path | str,
    psychology_semantics: str = "strict",
) -> dict[str, StagePlan]:
    """Build the canonical six-stage plan without executing it."""

    root = Path(output_root).resolve()
    semantics_args = ("--psychology-semantics", psychology_semantics)

    baseline_output = root / "F4_multi_seed_n10"
    iia_output = root / "E6_IIA_alpha_flee_n10"
    population_output = root / "F7_N_scan_n5"
    home_output = root / "F2_home_dist_n5"
    e2_output = root / "E2_ablation_matrix_n10"
    event5_output = root / "Event5_literature_validation_n5"

    plans = {
        "baseline": StagePlan(
            name="baseline",
            design="F4: 3 cities x seeds 42-51 x paired graph off/on",
            expected_invocations=len(CITIES) * len(BASELINE_SEEDS),
            expected_realizations=len(CITIES) * len(BASELINE_SEEDS) * 2,
            output_path=baseline_output,
            command=_python_command(
                "run_f4_multi_seed.py",
                "--seeds",
                "42-51",
                "--output-base",
                str(baseline_output),
                *semantics_args,
            ),
            validation_mode="strict_run_contract",
            reuse_relation=(
                "Canonical reference stage. Parameter overlap with population "
                "N=800, home=poi, E2=none, and Event5 auto/sqrt is conceptual "
                "only; stage-specific tags/provenance forbid file reuse."
            ),
        ),
        "iia": StagePlan(
            name="iia",
            design=(
                "E6.1b: alpha_flee=-7..-3 x 3 cities x seeds 42-51; "
                "graph-on all-four-alternatives sample"
            ),
            expected_invocations=(
                len(IIA_ALPHAS) * len(CITIES) * len(BASELINE_SEEDS)
            ),
            expected_realizations=(
                len(IIA_ALPHAS) * len(CITIES) * len(BASELINE_SEEDS)
            ),
            output_path=iia_output,
            command=_python_command(
                "run_e6_iia_test.py",
                "--alphas",
                *(str(value) for value in IIA_ALPHAS),
                "--seeds",
                *(str(value) for value in BASELINE_SEEDS),
                "--cities",
                *(city for city, _district in CITIES),
                "--output-base",
                str(iia_output),
                *semantics_args,
            ),
            validation_mode="iia_self_manifest",
            reuse_relation=(
                "No baseline files reused: IIA is graph-on-only and records "
                "tail shares under a distinct alpha sweep/cache contract."
            ),
        ),
        "population": StagePlan(
            name="population",
            design=(
                "F7: N={200,500,800,1500,3000} x 3 cities x seeds 42-46 "
                "x paired graph off/on"
            ),
            expected_invocations=(
                len(POPULATION_VALUES) * len(CITIES) * len(N5_SEEDS)
            ),
            expected_realizations=(
                len(POPULATION_VALUES) * len(CITIES) * len(N5_SEEDS) * 2
            ),
            output_path=population_output,
            command=_python_command(
                "run_f7_n_scan.py",
                "--seeds",
                "42-46",
                "--n-values",
                ",".join(str(value) for value in POPULATION_VALUES),
                "--output-base",
                str(population_output),
                *semantics_args,
            ),
            validation_mode="strict_run_contract",
            reuse_relation=(
                "N=800/seeds42-46 overlaps baseline parameters, but is rerun "
                "under F7-specific tags so the population curve is auditable."
            ),
        ),
        "home": StagePlan(
            name="home",
            design=(
                "F2: home={poi,uniform} x 3 cities x seeds 42-46 x paired "
                "graph off/on"
            ),
            expected_invocations=(
                len(HOME_DISTRIBUTIONS) * len(CITIES) * len(N5_SEEDS)
            ),
            expected_realizations=(
                len(HOME_DISTRIBUTIONS) * len(CITIES) * len(N5_SEEDS) * 2
            ),
            output_path=home_output,
            command=_python_command(
                "run_f2_home_dist.py",
                "--seeds",
                "42-46",
                "--output-base",
                str(home_output),
                *semantics_args,
            ),
            validation_mode="strict_run_contract",
            reuse_relation=(
                "poi/seeds42-46 overlaps baseline parameters, but is rerun "
                "under F2-specific tags; uniform is the independent contrast."
            ),
        ),
        "e2": StagePlan(
            name="e2",
            design=(
                "E2: 11 switch presets x 3 cities x seeds 42-51 x paired "
                "graph off/on"
            ),
            expected_invocations=(
                len(E2_PRESETS) * len(CITIES) * len(BASELINE_SEEDS)
            ),
            expected_realizations=(
                len(E2_PRESETS) * len(CITIES) * len(BASELINE_SEEDS) * 2
            ),
            output_path=e2_output,
            command=_python_command(
                "run_e2_ablation_matrix.py",
                "--cities",
                "all",
                "--seeds",
                "42-51",
                "--ablations",
                ",".join(E2_PRESETS),
                "--output-base",
                str(e2_output),
                *semantics_args,
            ),
            validation_mode="strict_run_contract",
            reuse_relation=(
                "The none preset overlaps baseline parameters but is retained "
                "as an E2-tagged cell to preserve a complete paired ablation grid."
            ),
        ),
        "event5": StagePlan(
            name="event5",
            design=(
                "Event 5: 5 unique opinion/stress specifications x Xiamen x "
                "seeds 42-46 x paired graph off/on"
            ),
            expected_invocations=len(EVENT5_UNIQUE_SPECS) * len(N5_SEEDS),
            expected_realizations=len(EVENT5_UNIQUE_SPECS) * len(N5_SEEDS) * 2,
            output_path=event5_output,
            command=_python_command(
                "run_literature_validation_batches.py",
                "--output-base",
                str(event5_output),
                *semantics_args,
            ),
            validation_mode="strict_run_contract",
            reuse_relation=(
                "Within Event 5, auto/sqrt belongs to both V1 and V2 and is "
                "run once: 30 nominal cells become 25 unique invocations. "
                "No baseline file is reused because Event5 tags are distinct."
            ),
        ),
    }
    return {name: plans[name] for name in STAGE_ORDER}


def matrix_totals(plans: Iterable[StagePlan]) -> dict[str, int]:
    values = list(plans)
    return {
        "expected_invocations": sum(p.expected_invocations for p in values),
        "expected_realizations": sum(p.expected_realizations for p in values),
        "runner_commands": len(values),
    }


def _parse_stage_selection(raw_values: Sequence[str]) -> tuple[str, ...]:
    requested: list[str] = []
    for raw in raw_values:
        requested.extend(value.strip().lower() for value in raw.split(","))
    requested = [value for value in requested if value]
    if not requested or requested == ["all"]:
        return STAGE_ORDER
    unknown = sorted(set(requested) - set(STAGE_ORDER))
    if unknown:
        raise ValueError(
            f"unknown stage(s): {', '.join(unknown)}; valid={','.join(STAGE_ORDER)}"
        )
    return tuple(name for name in STAGE_ORDER if name in set(requested))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _command_text(command: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(command))


def _initial_states(
    plans: dict[str, StagePlan], selected: set[str], dry_run: bool
) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "status": (
                "planned_dry_run"
                if name in selected and dry_run
                else "planned"
                if name in selected
                else "not_selected"
            ),
            "observed_invocations": 0,
            "observed_realizations": 0,
            "started_at_utc": "",
            "completed_at_utc": "",
            "validation_report": "",
            "error": "",
        }
        for name in plans
    }


def _stage_record(
    plan: StagePlan,
    selected: set[str],
    state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "stage": plan.name,
        "selected": plan.name in selected,
        "design": plan.design,
        "expected_invocations": plan.expected_invocations,
        "expected_realizations": plan.expected_realizations,
        "runner_command_count": 1,
        "output_path": str(plan.output_path),
        "command": _command_text(plan.command),
        "command_argv": list(plan.command),
        "validation_mode": plan.validation_mode,
        "reuse_relation": plan.reuse_relation,
        **state,
    }


CSV_FIELDS = (
    "manifest_schema_version",
    "psychology_semantics",
    "formal_evidence_eligible",
    "stage",
    "selected",
    "design",
    "expected_invocations",
    "expected_realizations",
    "runner_command_count",
    "observed_invocations",
    "observed_realizations",
    "output_path",
    "command",
    "command_argv",
    "validation_mode",
    "validation_report",
    "reuse_relation",
    "status",
    "started_at_utc",
    "completed_at_utc",
    "error",
)


def _write_manifests(
    *,
    output_root: Path,
    plans: dict[str, StagePlan],
    selected: set[str],
    states: dict[str, dict[str, Any]],
    psychology_semantics: str,
    dry_run: bool,
    resume: bool,
    mechanism_audit: bool,
    created_at_utc: str,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    records = [
        _stage_record(plans[name], selected, states[name]) for name in STAGE_ORDER
    ]
    full_totals = matrix_totals(plans.values())
    selected_totals = matrix_totals(
        plans[name] for name in STAGE_ORDER if name in selected
    )
    payload = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "matrix_id": "IJDRR_v7_strict_formal_matrix",
        "created_at_utc": created_at_utc,
        "updated_at_utc": _utc_now(),
        "psychology_semantics": psychology_semantics,
        "formal_evidence_eligible": psychology_semantics == "strict",
        "run_mode": (
            "formal_evidence"
            if psychology_semantics == "strict"
            else "mechanism_audit_only"
        ),
        "mechanism_audit_acknowledged": bool(mechanism_audit),
        "dry_run": bool(dry_run),
        "resume_requested": bool(resume),
        "stage_order": list(STAGE_ORDER),
        "full_matrix_totals": full_totals,
        "selected_matrix_totals": selected_totals,
        "stages": records,
    }

    json_path = output_root / MANIFEST_JSON
    json_tmp = json_path.with_suffix(json_path.suffix + ".tmp")
    json_tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    json_tmp.replace(json_path)

    csv_path = output_root / MANIFEST_CSV
    csv_tmp = csv_path.with_suffix(csv_path.suffix + ".tmp")
    with csv_tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in records:
            row = {
                "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
                "psychology_semantics": psychology_semantics,
                "formal_evidence_eligible": psychology_semantics == "strict",
                **record,
            }
            row["command_argv"] = json.dumps(
                row["command_argv"], ensure_ascii=False
            )
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})
    csv_tmp.replace(csv_path)


def _semantics_root(plan: StagePlan, semantics: str) -> Path:
    return plan.output_path / f"psychology_{semantics}"


def _standard_observed(plan: StagePlan, semantics: str) -> tuple[int, int]:
    root = _semantics_root(plan, semantics)
    count = sum(1 for _path in root.glob("t15_*/summary.json"))
    return count, count * 2


def _iia_observed(plan: StagePlan, semantics: str) -> tuple[int, int]:
    root = _semantics_root(plan, semantics)
    count = sum(1 for _path in root.rglob("tail_shares.json"))
    return count, count


def _observed(plan: StagePlan, semantics: str) -> tuple[int, int]:
    if plan.validation_mode == "iia_self_manifest":
        return _iia_observed(plan, semantics)
    return _standard_observed(plan, semantics)


def _run_checked(command: Sequence[str]) -> None:
    print(f"[exec] {_command_text(command)}", flush=True)
    subprocess.run(list(command), cwd=PROJECT_ROOT, check=True)


def _validate_standard_stage(plan: StagePlan, semantics: str) -> Path:
    observed, observed_realizations = _standard_observed(plan, semantics)
    if observed != plan.expected_invocations:
        raise RuntimeError(
            f"{plan.name}: strict summary count={observed}, "
            f"expected={plan.expected_invocations}"
        )
    if observed_realizations != plan.expected_realizations:
        raise RuntimeError(
            f"{plan.name}: realization count={observed_realizations}, "
            f"expected={plan.expected_realizations}"
        )

    report_path = plan.output_path / f"{semantics}_contract_validation.json"
    command = _python_command(
        "validate_strict_run_contract.py",
        "--root",
        str(plan.output_path),
        "--psychology-semantics",
        semantics,
        "--report",
        str(report_path),
    )
    _run_checked(command)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"{plan.name}: unreadable validator report {report_path}"
        ) from exc
    if (
        report.get("run_count") != plan.expected_invocations
        or report.get("passed") != plan.expected_invocations
        or report.get("failed") != 0
        or report.get("psychology_semantics") != semantics
    ):
        raise RuntimeError(
            f"{plan.name}: validator report does not certify the complete matrix"
        )
    return report_path


def _read_iia_manifest(plan: StagePlan, semantics: str) -> dict[str, Any]:
    path = _semantics_root(plan, semantics) / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"IIA manifest is unreadable: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"IIA manifest root is not an object: {path}")
    return data


def _iia_looks_complete(plan: StagePlan, semantics: str) -> bool:
    try:
        data = _read_iia_manifest(plan, semantics)
    except RuntimeError:
        return False
    observed, _realizations = _iia_observed(plan, semantics)
    return (
        data.get("status") == "complete"
        and data.get("psychology_semantics") == semantics
        and data.get("expected_run_count") == plan.expected_invocations
        and data.get("observed_run_count") == plan.expected_invocations
        and observed == plan.expected_invocations
    )


def _validate_iia_stage(plan: StagePlan, semantics: str) -> Path:
    # The IIA runner's aggregate-only path validates every cache identity,
    # enforces the complete city x seed x alpha grid, and rewrites its own
    # manifest only after successful aggregation.
    _run_checked((*plan.command, "--aggregate-only"))
    data = _read_iia_manifest(plan, semantics)
    observed, observed_realizations = _iia_observed(plan, semantics)
    configuration = data.get("configuration", {})
    expected_cities = [
        {"city": city, "district": district} for city, district in CITIES
    ]
    checks = {
        "status": data.get("status") == "complete",
        "semantics": data.get("psychology_semantics") == semantics,
        "model_contract": (
            data.get("model_contract_version") == MODEL_CONTRACT_VERSION
        ),
        "metric_schema": int(data.get("metric_schema_version", 0) or 0)
        >= MIN_METRIC_SCHEMA_VERSION,
        "expected_count": (
            data.get("expected_run_count") == plan.expected_invocations
        ),
        "observed_count": (
            data.get("observed_run_count") == plan.expected_invocations
            and observed == plan.expected_invocations
            and observed_realizations == plan.expected_realizations
        ),
        "alphas": configuration.get("alphas")
        == [float(value) for value in IIA_ALPHAS],
        "seeds": configuration.get("seeds") == list(BASELINE_SEEDS),
        "cities": configuration.get("cities") == expected_cities,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise RuntimeError(
            "IIA self-manifest does not certify the complete formal grid: "
            + ", ".join(failed)
        )
    return _semantics_root(plan, semantics) / "manifest.json"


def _stage_has_artifacts(plan: StagePlan) -> bool:
    return plan.output_path.exists() and any(plan.output_path.iterdir())


def _execute_stage(
    plan: StagePlan,
    *,
    psychology_semantics: str,
    resume: bool,
) -> tuple[bool, Path]:
    """Execute/validate a stage; return (reused_complete_stage, report_path)."""

    if not resume and _stage_has_artifacts(plan):
        raise RuntimeError(
            f"{plan.name}: output already contains artifacts; use --resume "
            f"after verifying the intended root: {plan.output_path}"
        )

    observed, _realizations = _observed(plan, psychology_semantics)
    if observed > plan.expected_invocations:
        raise RuntimeError(
            f"{plan.name}: found {observed} strict-semantic records, more than "
            f"the expected {plan.expected_invocations}"
        )

    if resume and observed == plan.expected_invocations:
        if plan.validation_mode == "iia_self_manifest":
            if _iia_looks_complete(plan, psychology_semantics):
                report = _validate_iia_stage(plan, psychology_semantics)
                return True, report
        else:
            report = _validate_standard_stage(plan, psychology_semantics)
            return True, report

    _run_checked(plan.command)
    if plan.validation_mode == "iia_self_manifest":
        report = _validate_iia_stage(plan, psychology_semantics)
    else:
        report = _validate_standard_stage(plan, psychology_semantics)
    return False, report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the auditable IJDRR v7 strict formal matrix."
    )
    parser.add_argument(
        "--stages",
        nargs="+",
        default=list(STAGE_ORDER),
        help=(
            "Stages to execute (space- or comma-separated): "
            + ",".join(STAGE_ORDER)
            + "; defaults to all."
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Formal output root; defaults to trace_output/IJDRR_v7_strict_formal.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write manifests and print the plan without launching subprocesses.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume partial stages and validate/reuse complete strict outputs.",
    )
    parser.add_argument(
        "--psychology-semantics",
        choices=("strict", "legacy"),
        default="strict",
        help="Formal evidence defaults to and requires strict semantics.",
    )
    parser.add_argument(
        "--mechanism-audit",
        action="store_true",
        help=(
            "Explicitly acknowledge that non-strict outputs are mechanism-audit "
            "artifacts only and cannot support the v7 formal manuscript."
        ),
    )
    args = parser.parse_args(argv)
    try:
        args.stage_names = _parse_stage_selection(args.stages)
    except ValueError as exc:
        parser.error(str(exc))

    if args.psychology_semantics != "strict" and not args.mechanism_audit:
        parser.error(
            "non-strict semantics are rejected for formal evidence; add "
            "--mechanism-audit and use a separate --output-root only for an "
            "explicit mechanism audit"
        )
    if args.psychology_semantics == "strict" and args.mechanism_audit:
        parser.error("--mechanism-audit is only valid with non-strict semantics")
    if (
        args.psychology_semantics != "strict"
        and args.output_root.resolve() == DEFAULT_OUTPUT_ROOT.resolve()
    ):
        parser.error(
            "legacy mechanism audits must use a separate --output-root; the "
            "formal strict root is protected"
        )
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_root = args.output_root.resolve()
    plans = build_stage_plans(output_root, args.psychology_semantics)
    selected = set(args.stage_names)
    states = _initial_states(plans, selected, args.dry_run)
    created_at = _utc_now()

    # Freeze the complete design before any model subprocess is launched.
    _write_manifests(
        output_root=output_root,
        plans=plans,
        selected=selected,
        states=states,
        psychology_semantics=args.psychology_semantics,
        dry_run=args.dry_run,
        resume=args.resume,
        mechanism_audit=args.mechanism_audit,
        created_at_utc=created_at,
    )

    full = matrix_totals(plans.values())
    chosen = matrix_totals(plans[name] for name in args.stage_names)
    print(
        "[matrix] full="
        f"{full['expected_invocations']} invocations/"
        f"{full['expected_realizations']} realizations; selected="
        f"{chosen['expected_invocations']}/"
        f"{chosen['expected_realizations']}",
        flush=True,
    )
    for name in args.stage_names:
        plan = plans[name]
        print(
            f"[plan:{name}] {plan.expected_invocations} invocations / "
            f"{plan.expected_realizations} realizations -> {plan.output_path}",
            flush=True,
        )
        print(f"  {_command_text(plan.command)}", flush=True)

    if args.dry_run:
        print(f"[dry-run] manifests written under {output_root}", flush=True)
        return 0

    for name in args.stage_names:
        plan = plans[name]
        state = states[name]
        state["status"] = "running"
        state["started_at_utc"] = _utc_now()
        _write_manifests(
            output_root=output_root,
            plans=plans,
            selected=selected,
            states=states,
            psychology_semantics=args.psychology_semantics,
            dry_run=args.dry_run,
            resume=args.resume,
            mechanism_audit=args.mechanism_audit,
            created_at_utc=created_at,
        )
        try:
            reused, report = _execute_stage(
                plan,
                psychology_semantics=args.psychology_semantics,
                resume=args.resume,
            )
            observed, realizations = _observed(
                plan, args.psychology_semantics
            )
            state.update(
                {
                    "status": "complete_reused" if reused else "complete",
                    "observed_invocations": observed,
                    "observed_realizations": realizations,
                    "completed_at_utc": _utc_now(),
                    "validation_report": str(report),
                    "error": "",
                }
            )
        except (Exception, KeyboardInterrupt) as exc:
            observed, realizations = _observed(
                plan, args.psychology_semantics
            )
            state.update(
                {
                    "status": "failed",
                    "observed_invocations": observed,
                    "observed_realizations": realizations,
                    "completed_at_utc": _utc_now(),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            _write_manifests(
                output_root=output_root,
                plans=plans,
                selected=selected,
                states=states,
                psychology_semantics=args.psychology_semantics,
                dry_run=args.dry_run,
                resume=args.resume,
                mechanism_audit=args.mechanism_audit,
                created_at_utc=created_at,
            )
            raise

        _write_manifests(
            output_root=output_root,
            plans=plans,
            selected=selected,
            states=states,
            psychology_semantics=args.psychology_semantics,
            dry_run=args.dry_run,
            resume=args.resume,
            mechanism_audit=args.mechanism_audit,
            created_at_utc=created_at,
        )
        print(f"[complete:{name}] {state['status']}", flush=True)

    print(f"[done] formal matrix manifest: {output_root / MANIFEST_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
