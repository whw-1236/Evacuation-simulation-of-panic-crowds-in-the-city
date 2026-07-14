# -*- coding: utf-8 -*-
"""Run the literature-model validation ablation batches.

Design:
- V1: opinion mode auto/off/on x seeds 42-46 x sqrt profile
- V2: stress profile sqrt/log/linear x seeds 42-46 x auto opinion mode

The overlap auto x sqrt x seeds 42-46 is run once, so there are 25 unique tags.
Existing runs are skipped only when summary.json config matches the requested
seed, opinion mode, and outage-stress profile.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_BASE = (
    Path("IJDRR_v7_strict_formal") / "Event5_literature_validation_n5"
)
TRACE_BASE = ROOT / "trace_output" / DEFAULT_OUTPUT_BASE
CITY = "厦门市"
DISTRICT = "思明区"
TAG_PREFIX = "event5fix"
EXPECTED_MODEL_CONTRACT_VERSION = "ijdrr_strict_v1"
MIN_METRIC_SCHEMA_VERSION = 4


@dataclass(frozen=True)
class RunSpec:
    groups: tuple[str, ...]
    opinion_mode: str
    profile: str
    seed: int
    tag: str


def expected_specs() -> list[RunSpec]:
    by_tag: dict[str, dict[str, object]] = {}
    for seed in range(42, 47):
        for mode in ("auto", "off", "on"):
            tag = f"{TAG_PREFIX}_opinion_{mode}_sqrt_seed{seed}"
            by_tag.setdefault(
                tag,
                {
                    "groups": [],
                    "opinion_mode": mode,
                    "profile": "sqrt",
                    "seed": seed,
                },
            )["groups"].append("V1")
    for seed in range(42, 47):
        for profile in ("sqrt", "log", "linear"):
            tag = f"{TAG_PREFIX}_opinion_auto_{profile}_seed{seed}"
            by_tag.setdefault(
                tag,
                {
                    "groups": [],
                    "opinion_mode": "auto",
                    "profile": profile,
                    "seed": seed,
                },
            )["groups"].append("V2")

    specs = []
    for tag, data in by_tag.items():
        specs.append(
            RunSpec(
                groups=tuple(data["groups"]),
                opinion_mode=str(data["opinion_mode"]),
                profile=str(data["profile"]),
                seed=int(data["seed"]),
                tag=tag,
            )
        )
    return sorted(specs, key=lambda s: (s.seed, s.opinion_mode, s.profile, s.tag))


def semantics_dir(semantics: str) -> Path:
    return TRACE_BASE / f"psychology_{semantics}"


def run_dir(spec: RunSpec, semantics: str) -> Path:
    return semantics_dir(semantics) / f"t15_{CITY}_{DISTRICT}_{spec.tag}"


def validate_summary_semantics(data: dict, expected: str, path: Path) -> None:
    if data.get("model_contract_version") != EXPECTED_MODEL_CONTRACT_VERSION:
        raise RuntimeError(f"summary model_contract_version mismatch: {path}")
    try:
        schema_version = int(data.get("metric_schema_version"))
    except (TypeError, ValueError):
        schema_version = -1
    if schema_version < MIN_METRIC_SCHEMA_VERSION:
        raise RuntimeError(f"summary metric_schema_version is too old: {path}")
    actual = data.get("config", {}).get("psychology_semantics")
    if actual != expected:
        raise RuntimeError(
            f"summary psychology_semantics mismatch: expected={expected!r}, "
            f"actual={actual!r}, path={path}"
        )
    manifests = data.get("manifest")
    if not isinstance(manifests, dict):
        raise RuntimeError(f"summary manifest missing: {path}")
    for graph_mode in ("off", "on"):
        manifest = manifests.get(graph_mode)
        actual = manifest.get("psychology_semantics") if isinstance(manifest, dict) else None
        if actual != expected:
            raise RuntimeError(
                f"{graph_mode} manifest psychology_semantics mismatch: "
                f"expected={expected!r}, actual={actual!r}, path={path}"
            )
        if manifest.get("model_contract_version") != EXPECTED_MODEL_CONTRACT_VERSION:
            raise RuntimeError(
                f"{graph_mode} manifest model_contract_version mismatch: {path}"
            )
        try:
            manifest_schema = int(manifest.get("metric_schema_version"))
        except (TypeError, ValueError):
            manifest_schema = -1
        if manifest_schema < MIN_METRIC_SCHEMA_VERSION:
            raise RuntimeError(
                f"{graph_mode} manifest metric_schema_version is too old: {path}"
            )


def matching_summary(spec: RunSpec, semantics: str) -> bool:
    path = run_dir(spec, semantics) / "summary.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"unreadable summary: {path}") from exc
    validate_summary_semantics(data, semantics, path)
    cfg = data.get("config", {})
    return (
        cfg.get("seed") == spec.seed
        and cfg.get("opinion_mode") == spec.opinion_mode
        and cfg.get("outage_stress_profile") == spec.profile
        and cfg.get("tag") == spec.tag
        and cfg.get("psychology_semantics") == semantics
    )


def run_spec(
    spec: RunSpec, log_file: Path, semantics: str, output_base: str
) -> int:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_ablation.py"),
        "--seed",
        str(spec.seed),
        "--tag",
        spec.tag,
        "--output-base",
        output_base,
        "--opinion-mode",
        spec.opinion_mode,
        "--outage-stress-profile",
        spec.profile,
        "--psychology-semantics",
        semantics,
    ]
    with log_file.open("a", encoding="utf-8", errors="replace") as log:
        log.write("\n" + "=" * 100 + "\n")
        log.write(f"{datetime.now().isoformat()} RUN {spec}\n")
        log.write(" ".join(cmd) + "\n")
        log.flush()
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        log.write(f"\nRETURN_CODE {proc.returncode}\n")
    return int(proc.returncode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--psychology-semantics",
        choices=("strict", "legacy"),
        default="strict",
        help="Psychology ownership contract; strict is required for formal evidence.",
    )
    parser.add_argument(
        "--output-base",
        default=str(DEFAULT_OUTPUT_BASE),
        help="Trace output base, relative to trace_output or absolute.",
    )
    args = parser.parse_args()

    global TRACE_BASE
    output_base_path = Path(args.output_base)
    TRACE_BASE = (
        output_base_path
        if output_base_path.is_absolute()
        else ROOT / "trace_output" / output_base_path
    )
    run_root = semantics_dir(args.psychology_semantics)
    run_root.mkdir(parents=True, exist_ok=True)
    log_file = run_root / f"batch_literature_validation_{TAG_PREFIX}_2026-07-14.log"
    specs = expected_specs()
    pending = [
        spec for spec in specs if not matching_summary(spec, args.psychology_semantics)
    ]
    if args.limit is not None:
        pending = pending[: args.limit]

    print(f"[plan] expected_unique={len(specs)} pending={len(pending)}")
    for spec in pending:
        print(
            f"[pending] {spec.tag} seed={spec.seed} "
            f"mode={spec.opinion_mode} profile={spec.profile} "
            f"groups={'+'.join(spec.groups)}"
        )

    if args.dry_run:
        return 0

    failures: list[RunSpec] = []
    for idx, spec in enumerate(pending, start=1):
        print(f"[run {idx}/{len(pending)}] {spec.tag}")
        rc = run_spec(
            spec, log_file, args.psychology_semantics, args.output_base
        )
        if rc != 0 or not matching_summary(spec, args.psychology_semantics):
            failures.append(spec)
            print(f"[fail] {spec.tag} rc={rc}")
        else:
            print(f"[ok] {spec.tag}")

    if failures:
        print("[done] failures:")
        for spec in failures:
            print(f"  - {spec.tag}")
        return 1
    print("[done] all requested literature-validation runs complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
