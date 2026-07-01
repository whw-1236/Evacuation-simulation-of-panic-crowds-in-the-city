# -*- coding: utf-8 -*-
"""Build a reproducibility manifest for the M4 manuscript artifacts.

The script does not run simulations. It records the files that feed the
manuscript's Section 5 tables/figures, plus the current SwitchParams defaults.
Outputs are written under trace_output/ so they remain data artifacts rather
than source-controlled code.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "trace_output"

def load_switch_params_class():
    """Load SwitchParams without importing core.__init__ and GIS dependencies."""
    module_path = ROOT / "core" / "behavior_switching.py"
    spec = importlib.util.spec_from_file_location("behavior_switching_manifest", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SwitchParams


SwitchParams = load_switch_params_class()


ARTIFACTS = [
    {
        "id": "table_5_1",
        "role": "MML F4 multi-seed aggregate CI",
        "path": "trace_output/M4_MML_F4_multi_seed/aggregate_ci.csv",
        "used_by": ["Table 5.1", "Fig. 5.1", "Result 5.1"],
    },
    {
        "id": "figure_5_1",
        "role": "MML F4 grouped errorbar figure",
        "path": "trace_output/M4_MML_F4_multi_seed/errorbar.png",
        "used_by": ["Fig. 5.1"],
    },
    {
        "id": "table_5_2",
        "role": "MML F7 population-size scan",
        "path": "trace_output/M4_MML_F7_N_scan/n_curve.csv",
        "used_by": ["Table 5.2", "Fig. 5.2", "Result 5.2"],
    },
    {
        "id": "figure_5_2",
        "role": "MML F7 N-curve figure",
        "path": "trace_output/M4_MML_F7_N_scan/n_curve.png",
        "used_by": ["Fig. 5.2"],
    },
    {
        "id": "table_5_3",
        "role": "MML F2 centrality-vs-load comparison; poi rows feed E6.4, uniform rows feed E6.5",
        "path": "trace_output/M4_MML_F2_home_dist/r_compare.csv",
        "used_by": ["Table 5.3 top / E6.4", "Table 5.3 bottom / E6.5", "Result 5.3"],
    },
    {
        "id": "figure_5_3",
        "role": "Xiamen BC-load correlation panel",
        "glob": "trace_output/M4_MML_F2_home_dist/_corr/*_poi/correlation.png",
        "prefer": "厦门市_思明区_poi",
        "used_by": ["Fig. 5.3"],
    },
    {
        "id": "table_s1",
        "role": "Legacy sigmoid F4 aggregate CI",
        "path": "trace_output/M4_F4_multi_seed/aggregate_ci.csv",
        "used_by": ["Table S1"],
    },
    {
        "id": "table_s2",
        "role": "Legacy sigmoid F7 population-size scan",
        "path": "trace_output/M4_F7_N_scan/n_curve.csv",
        "used_by": ["Table S2"],
    },
    {
        "id": "table_s3",
        "role": "Legacy sigmoid F2 centrality-vs-load comparison",
        "path": "trace_output/M4_F2_home_dist/r_compare.csv",
        "used_by": ["Table S3"],
    },
    {
        "id": "figure_s1",
        "role": "Legacy sigmoid theta_flee phase-transition scan",
        "path": "trace_output/M4_F5_theta_flee/theta_curve.png",
        "used_by": ["Fig. S1"],
    },
    {
        "id": "table_s_theta",
        "role": "Legacy sigmoid theta_flee phase-transition data",
        "path": "trace_output/M4_F5_theta_flee/theta_curve.csv",
        "used_by": ["Fig. S1"],
    },
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def csv_shape(path: Path) -> dict[str, int] | None:
    if path.suffix.lower() != ".csv":
        return None
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return {"rows": 0, "columns": 0}
    return {"rows": max(0, len(rows) - 1), "columns": len(rows[0])}


def git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def inspect_artifact(item: dict) -> dict:
    rec = dict(item)
    if "glob" in item:
        matches = sorted(ROOT.glob(item["glob"]))
        prefer = item.get("prefer")
        if prefer:
            preferred = [p for p in matches if prefer in str(p)]
            if preferred:
                matches = preferred
        if matches:
            path = matches[0]
            rec["path"] = str(path.relative_to(ROOT)).replace("\\", "/")
        else:
            rec["path"] = item["glob"]
            rec["exists"] = False
            return rec
    else:
        path = ROOT / item["path"]
    rec["exists"] = path.exists()
    if not path.exists():
        return rec

    stat = path.stat()
    rec.update(
        {
            "bytes": stat.st_size,
            "modified_utc": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
            "sha256": sha256(path),
        }
    )
    shape = csv_shape(path)
    if shape is not None:
        rec["csv_shape"] = shape
    return rec


def write_markdown(manifest: dict, out_path: Path) -> None:
    lines = [
        "# M4 artifact manifest",
        "",
        f"- Generated UTC: `{manifest['generated_utc']}`",
        f"- Git commit: `{manifest.get('git_commit') or 'unknown'}`",
        f"- Missing artifacts: `{len(manifest['missing_artifacts'])}`",
        "",
        "| ID | Used by | Exists | Size | SHA256 prefix | Path |",
        "|---|---|---:|---:|---|---|",
    ]
    for item in manifest["artifacts"]:
        sha = item.get("sha256", "")[:12]
        used_by = ", ".join(item.get("used_by", []))
        lines.append(
            f"| `{item['id']}` | {used_by} | {item['exists']} | "
            f"{item.get('bytes', '')} | `{sha}` | `{item['path']}` |"
        )
    lines.extend(
        [
            "",
            "## SwitchParams snapshot",
            "",
            "```json",
            json.dumps(manifest["switch_params"], ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    TRACE.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "root": str(ROOT),
        "switch_params": asdict(SwitchParams()),
        "artifacts": [inspect_artifact(item) for item in ARTIFACTS],
    }
    manifest["missing_artifacts"] = [
        item["id"] for item in manifest["artifacts"] if not item["exists"]
    ]

    json_path = TRACE / "M4_artifact_manifest.json"
    md_path = TRACE / "M4_artifact_manifest.md"
    json_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_markdown(manifest, md_path)
    print(f"[manifest] saved {json_path}")
    print(f"[manifest] saved {md_path}")
    if manifest["missing_artifacts"]:
        print("[manifest] missing:", ", ".join(manifest["missing_artifacts"]))


if __name__ == "__main__":
    main()
