from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from pathlib import Path

import networkx as nx
import numpy as np
from scipy.stats import t as student_t


PROJECT = Path(__file__).resolve().parents[1]
HELPER = PROJECT / "analysis" / "shelter_aware_bc.py"
DEFAULT_FORMAL_ROOT = PROJECT / "trace_output" / "IJDRR_v7_strict_formal"
EXPECTED_MODEL_CONTRACT_VERSION = "ijdrr_strict_v1"
MIN_METRIC_SCHEMA_VERSION = 4
CITIES = [
    ("厦门市", "思明区"),
    ("沈阳市", "沈河区"),
    ("北京市", "东城区"),
]
METRIC_FIELDS = [
    "standard_node_bc_r_loaded",
    "shelter_aware_bc_r_loaded",
    "shelter_proximity_r_loaded",
    "edge_bc_r_loaded",
]


def parse_int_list(value: str) -> list[int]:
    values: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if item:
            values.append(int(item))
    if not values:
        raise argparse.ArgumentTypeError("expected at least one integer")
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute E6.6 k=200 centrality diagnostics from existing traces."
    )
    parser.add_argument(
        "--trace-dir",
        type=Path,
        default=DEFAULT_FORMAL_ROOT / "F2_home_dist_n5",
        help="Directory containing t15_* graph_on/edge_observations.csv runs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_FORMAL_ROOT / "E6_6_shelter_bc_k200_n5",
        help="Directory for e6_6_k200_summary.csv.",
    )
    parser.add_argument(
        "--home-distribution",
        choices=["poi", "uniform"],
        default="poi",
        help="Household-distribution tag to read from the trace directory.",
    )
    parser.add_argument(
        "--run-seeds",
        type=parse_int_list,
        default=parse_int_list("42,43,44,45,46"),
        help="Comma-separated simulation seeds to read.",
    )
    parser.add_argument(
        "--run-tag-template",
        default="{home_distribution}_seed{seed}",
        help=(
            "Run tag suffix in t15_city_district_TAG; defaults to the formal "
            "n=5 F2 convention."
        ),
    )
    parser.add_argument("--standard-bc-k", type=int, default=200)
    parser.add_argument(
        "--shelter-sample-sources",
        type=int,
        default=0,
        help="Source-node sample for shelter-aware BC; 0 means all non-shelter nodes.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--psychology-semantics",
        choices=("strict", "legacy"),
        default="strict",
        help="Only read runs produced under this psychology contract.",
    )
    return parser.parse_args()


def semantics_dir(base: Path, semantics: str) -> Path:
    leaf = f"psychology_{semantics}"
    return base if base.name == leaf else base / leaf


def validate_summary_semantics(summary: dict, expected: str, path: Path) -> None:
    if summary.get("model_contract_version") != EXPECTED_MODEL_CONTRACT_VERSION:
        raise ValueError(f"summary model_contract_version mismatch: {path}")
    try:
        schema_version = int(summary.get("metric_schema_version"))
    except (TypeError, ValueError):
        schema_version = -1
    if schema_version < MIN_METRIC_SCHEMA_VERSION:
        raise ValueError(f"summary metric_schema_version is too old: {path}")
    actual = summary.get("config", {}).get("psychology_semantics")
    if actual != expected:
        raise ValueError(
            f"summary psychology_semantics mismatch: expected={expected!r}, "
            f"actual={actual!r}, path={path}"
        )
    manifests = summary.get("manifest")
    if not isinstance(manifests, dict):
        raise ValueError(f"summary manifest missing: {path}")
    for graph_mode in ("off", "on"):
        manifest = manifests.get(graph_mode)
        actual = manifest.get("psychology_semantics") if isinstance(manifest, dict) else None
        if actual != expected:
            raise ValueError(
                f"{graph_mode} manifest psychology_semantics mismatch: "
                f"expected={expected!r}, actual={actual!r}, path={path}"
            )
        if manifest.get("model_contract_version") != EXPECTED_MODEL_CONTRACT_VERSION:
            raise ValueError(
                f"{graph_mode} manifest model_contract_version mismatch: {path}"
            )
        try:
            manifest_schema = int(manifest.get("metric_schema_version"))
        except (TypeError, ValueError):
            manifest_schema = -1
        if manifest_schema < MIN_METRIC_SCHEMA_VERSION:
            raise ValueError(
                f"{graph_mode} manifest metric_schema_version is too old: {path}"
            )


def load_helper():
    spec = importlib.util.spec_from_file_location("shelter_aware_bc", HELPER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def read_edge_load(edge_csv: Path) -> dict[tuple[str, str], float]:
    edge_obs: dict[tuple[str, str], float] = {}
    with edge_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            u = str(row["u"])
            v = str(row["v"])
            edge_obs[(u, v)] = edge_obs.get((u, v), 0.0) + float(row["cum_occupancy"])
    return edge_obs


def edge_load_arrays(UG: nx.Graph, edge_obs: dict[tuple[str, str], float], edge_bc: dict):
    scores = []
    loads = []
    for u, v in UG.edges():
        scores.append(float(edge_bc.get((u, v), edge_bc.get((v, u), 0.0))))
        loads.append(
            edge_obs.get((str(u), str(v)), 0.0)
            + edge_obs.get((str(v), str(u)), 0.0)
        )
    return np.asarray(scores, dtype=float), np.asarray(loads, dtype=float)


def run_tag(args: argparse.Namespace, run_seed: int) -> str:
    return args.run_tag_template.format(
        home_distribution=args.home_distribution,
        seed=run_seed,
    )


def compute_city(
    helper,
    args: argparse.Namespace,
    city: str,
    district: str,
    run_seed: int,
) -> dict:
    graphml = PROJECT / "road_graph_cache" / f"{city}_{district}.graphml"
    tag = run_tag(args, run_seed)
    run_dir = args.trace_dir / f"t15_{city}_{district}_{tag}"
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing summary: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    validate_summary_semantics(summary, args.psychology_semantics, summary_path)
    config = summary.get("config", {})
    expected_config = {
        "city": city,
        "district": district,
        "seed": run_seed,
        "tag": tag,
        "home_distribution": args.home_distribution,
    }
    mismatches = {
        key: (expected, config.get(key))
        for key, expected in expected_config.items()
        if config.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"summary config mismatch: {mismatches}, path={summary_path}")
    edge_csv = (
        run_dir
        / "graph_on"
        / "edge_observations.csv"
    )
    if not edge_csv.exists():
        raise FileNotFoundError(f"Missing edge observations: {edge_csv}")

    G, UG = helper.largest_component_graph(graphml)
    node_load = helper.read_node_load(G, UG, edge_csv)
    standard_bc = nx.betweenness_centrality(
        UG,
        k=min(args.standard_bc_k, UG.number_of_nodes()),
        weight="length",
        seed=args.seed,
    )

    shelters = helper.load_shelter_points(city, district)
    shelter_nodes = helper.snap_shelters(G, UG, shelters)
    shelter_bc = helper.shelter_aware_centrality(
        UG,
        shelter_nodes=shelter_nodes,
        sample_sources=args.shelter_sample_sources,
        seed=args.seed,
    )
    shelter_dist = nx.multi_source_dijkstra_path_length(UG, shelter_nodes, weight="length")
    shelter_proximity = {
        node: 1.0 / (1.0 + float(shelter_dist.get(node, np.inf)))
        if np.isfinite(float(shelter_dist.get(node, np.inf)))
        else 0.0
        for node in UG.nodes
    }

    nodes = list(UG.nodes)
    load = np.array([node_load[node] for node in nodes], dtype=float)
    loaded = load > 0
    standard = np.array([standard_bc.get(node, 0.0) for node in nodes], dtype=float)
    shelter = np.array([shelter_bc.get(node, 0.0) for node in nodes], dtype=float)
    proximity = np.array([shelter_proximity.get(node, 0.0) for node in nodes], dtype=float)

    edge_obs = read_edge_load(edge_csv)
    edge_bc = nx.edge_betweenness_centrality(
        UG,
        k=min(args.standard_bc_k, UG.number_of_nodes()),
        weight="length",
        seed=args.seed,
    )
    edge_scores, edge_loads = edge_load_arrays(UG, edge_obs, edge_bc)
    edge_loaded = edge_loads > 0

    r_node_loaded, p_node_loaded = helper.safe_pearson(standard[loaded], load[loaded])
    r_shelter_loaded, p_shelter_loaded = helper.safe_pearson(shelter[loaded], load[loaded])
    r_prox_loaded, p_prox_loaded = helper.safe_pearson(proximity[loaded], load[loaded])
    r_edge_loaded, p_edge_loaded = helper.safe_pearson(
        edge_scores[edge_loaded], edge_loads[edge_loaded]
    )

    return {
        "city": city,
        "district": district,
        "home_distribution": args.home_distribution,
        "run_seed": run_seed,
        "run_tag": tag,
        "psychology_semantics": args.psychology_semantics,
        "n_loaded_nodes": int(loaded.sum()),
        "standard_node_bc_r_loaded": r_node_loaded,
        "standard_node_bc_p_loaded": p_node_loaded,
        "shelter_aware_bc_r_loaded": r_shelter_loaded,
        "shelter_aware_bc_p_loaded": p_shelter_loaded,
        "shelter_proximity_r_loaded": r_prox_loaded,
        "shelter_proximity_p_loaded": p_prox_loaded,
        "n_loaded_edges": int(edge_loaded.sum()),
        "edge_bc_r_loaded": r_edge_loaded,
        "edge_bc_p_loaded": p_edge_loaded,
        "standard_bc_k": args.standard_bc_k,
        "shelter_sample_sources": args.shelter_sample_sources or "all",
        "bc_seed": args.seed,
    }


def mean_ci(values: list[float | None]) -> tuple[float | None, float | None, float | None, int]:
    clean = [float(value) for value in values if value is not None and np.isfinite(value)]
    n = len(clean)
    if n == 0:
        return None, None, None, 0
    mean = float(np.mean(clean))
    if n == 1:
        return mean, None, None, 1
    tcrit = float(student_t.ppf(0.975, n - 1))
    half_width = float(tcrit * np.std(clean, ddof=1) / np.sqrt(n))
    return mean, mean - half_width, mean + half_width, n


def fisher_r_ci(
    values: list[float | None],
) -> tuple[float | None, float | None, float | None, int]:
    """Student-t interval for replicate correlations in Fisher-z space."""
    clean = np.asarray([
        float(value) for value in values
        if value is not None and np.isfinite(value)
    ], dtype=float)
    n = len(clean)
    if n == 0:
        return None, None, None, 0
    if np.any((clean < -1.0) | (clean > 1.0)):
        raise ValueError(f"correlation outside [-1, 1]: {clean.tolist()}")
    lower = np.nextafter(-1.0, 0.0)
    upper = np.nextafter(1.0, 0.0)
    clipped = np.clip(clean, lower, upper)
    z_values = np.arctanh(clipped)
    mean_z = float(np.mean(z_values))
    mean_r = float(np.tanh(mean_z))
    if n == 1:
        return mean_r, None, None, 1
    tcrit = float(student_t.ppf(0.975, n - 1))
    half_width_z = float(tcrit * np.std(z_values, ddof=1) / np.sqrt(n))
    return (
        mean_r,
        float(np.tanh(mean_z - half_width_z)),
        float(np.tanh(mean_z + half_width_z)),
        n,
    )


def aggregate_rows(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        key = (row["city"], row["district"], row["home_distribution"])
        grouped.setdefault(key, []).append(row)

    out = []
    for (city, district, home_distribution), group in sorted(grouped.items()):
        run_seeds = [int(row["run_seed"]) for row in group]
        if len(run_seeds) != len(set(run_seeds)):
            raise ValueError(
                f"duplicate run seeds for {city}/{district}/{home_distribution}: "
                f"{run_seeds}"
            )
        semantics = {row["psychology_semantics"] for row in group}
        if len(semantics) != 1:
            raise ValueError(
                f"mixed psychology semantics for {city}/{district}/"
                f"{home_distribution}: {sorted(semantics)}"
            )
        agg = {
            "city": city,
            "district": district,
            "home_distribution": home_distribution,
            "n_runs": len(group),
            "psychology_semantics": group[0]["psychology_semantics"],
            "correlation_ci_method": (
                "Fisher-z transform; arithmetic mean and two-sided Student-t "
                "95% CI in z-space (df=n-1); tanh back-transform"
            ),
        }
        for field in METRIC_FIELDS:
            values = [row[field] for row in group]
            mean, lo, hi, n = fisher_r_ci(values)
            if n != len(group):
                raise ValueError(
                    f"missing/non-finite correlation for {city}/{district}/"
                    f"{home_distribution}, metric={field}: n={n}/{len(group)}"
                )
            agg[f"{field}_mean"] = mean
            agg[f"{field}_ci95_lo"] = lo
            agg[f"{field}_ci95_hi"] = hi
            agg[f"{field}_n"] = n
        out.append(agg)
    return out


def main() -> int:
    args = parse_args()
    args.trace_dir = semantics_dir(args.trace_dir, args.psychology_semantics)
    args.output_dir = semantics_dir(args.output_dir, args.psychology_semantics)
    helper = load_helper()
    rows = [
        compute_city(helper, args, city, district, run_seed)
        for city, district in CITIES
        for run_seed in args.run_seeds
    ]
    aggregate = aggregate_rows(rows)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_csv = args.output_dir / "e6_6_k200_summary.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    out_ci_csv = args.output_dir / "e6_6_k200_summary_ci.csv"
    with out_ci_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(aggregate[0].keys()))
        writer.writeheader()
        writer.writerows(aggregate)

    print(out_csv)
    print(out_ci_csv)
    for row in rows:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
