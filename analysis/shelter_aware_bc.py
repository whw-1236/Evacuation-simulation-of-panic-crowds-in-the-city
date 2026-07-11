# -*- coding: utf-8 -*-
"""Shelter-aware centrality prototype for the M4/E6.6 discussion.

This post-processor compares standard graph betweenness with a shelter-aware
centrality against observed graph-on road load. It reads existing
``edge_observations.csv`` outputs and does not run a simulation.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import random
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
MAP_DIR = ROOT / "simulation map data"
TRACE = ROOT / "trace_output"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

matplotlib = None
plt = None
nx = None
np = None
ox = None
pearsonr = None
spearmanr = None
_shelter_loader = None


def ensure_dependencies() -> None:
    global matplotlib, plt, nx, np, ox, pearsonr, spearmanr
    if nx is not None:
        return

    import matplotlib as _matplotlib

    _matplotlib.use("Agg")
    import matplotlib.pyplot as _plt
    import networkx as _nx
    import numpy as _np
    import osmnx as _ox
    from scipy.stats import pearsonr as _pearsonr
    from scipy.stats import spearmanr as _spearmanr

    _matplotlib.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "DejaVu Sans",
    ]
    _matplotlib.rcParams["axes.unicode_minus"] = False

    matplotlib = _matplotlib
    plt = _plt
    nx = _nx
    np = _np
    ox = _ox
    pearsonr = _pearsonr
    spearmanr = _spearmanr


def load_shelter_loader():
    global _shelter_loader
    if _shelter_loader is not None:
        return _shelter_loader

    path = ROOT / "core" / "shelter_loader.py"
    spec = importlib.util.spec_from_file_location("shelter_loader_direct", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    _shelter_loader = module
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shelter-aware BC vs observed road load")
    parser.add_argument("--city", default="厦门市")
    parser.add_argument("--district", default="思明区")
    parser.add_argument("--home-distribution", default="poi", choices=["poi", "uniform"])
    parser.add_argument("--output-base", default="M4_MML_F2_home_dist")
    parser.add_argument("--edge-csv", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument(
        "--sample-sources",
        type=int,
        default=0,
        help="Number of source nodes for shelter-aware paths; 0 means all nodes.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--standard-bc-k", type=int, default=200)
    return parser.parse_args()


def safe_pearson(x: np.ndarray, y: np.ndarray) -> tuple[float | None, float | None]:
    ensure_dependencies()
    if len(x) < 3 or float(np.std(x)) <= 1e-12 or float(np.std(y)) <= 1e-12:
        return None, None
    r, p = pearsonr(x, y)
    return float(r), float(p)


def safe_spearman(x: np.ndarray, y: np.ndarray) -> tuple[float | None, float | None]:
    ensure_dependencies()
    if len(x) < 3 or float(np.std(x)) <= 1e-12 or float(np.std(y)) <= 1e-12:
        return None, None
    rho, p = spearmanr(x, y)
    return float(rho), float(p)


def load_shelter_points(city: str, district: str) -> list[tuple[float, float, str]]:
    shelter_loader = load_shelter_loader()
    shelters = shelter_loader.load_shelters(str(MAP_DIR), city, district)
    points: list[tuple[float, float, str]] = []
    for shelter in shelters:
        try:
            lon = float(shelter["lon"])
            lat = float(shelter["lat"])
        except Exception:
            continue
        name = str(shelter.get("name") or "")
        points.append((lon, lat, name))
    if not points:
        raise RuntimeError(f"No shelter-like points found for {city}/{district}")
    return points


def largest_component_graph(graphml: Path) -> tuple[nx.MultiDiGraph, nx.Graph]:
    ensure_dependencies()
    G = ox.io.load_graphml(graphml)
    UG_all = nx.Graph(G)
    largest = max(nx.connected_components(UG_all), key=len)
    UG = UG_all.subgraph(largest).copy()
    return G, UG


def snap_shelters(G: nx.MultiDiGraph, UG: nx.Graph, shelters) -> list:
    ensure_dependencies()
    xs = [p[0] for p in shelters]
    ys = [p[1] for p in shelters]
    snapped = ox.distance.nearest_nodes(G, X=xs, Y=ys)
    nodes = []
    for node in snapped:
        if node in UG:
            nodes.append(node)
        elif str(node) in UG:
            nodes.append(str(node))
    return sorted(set(nodes), key=str)


def read_node_load(G: nx.MultiDiGraph, UG: nx.Graph, edge_csv: Path) -> dict:
    if not edge_csv.exists():
        raise FileNotFoundError(f"edge observations not found: {edge_csv}")

    edge_obs: dict[tuple[str, str], float] = {}
    with edge_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            u = str(row["u"])
            v = str(row["v"])
            edge_obs[(u, v)] = edge_obs.get((u, v), 0.0) + float(row["cum_occupancy"])

    node_load = {}
    for node in UG.nodes:
        node_str = str(node)
        load = 0.0
        neighbors = G.predecessors(node) if G.is_directed() and node in G else G.neighbors(node)
        for neighbor in neighbors:
            load += edge_obs.get((str(neighbor), node_str), 0.0)
        node_load[node] = load
    return node_load


def shelter_aware_centrality(
    UG: nx.Graph,
    shelter_nodes: list,
    sample_sources: int,
    seed: int,
) -> dict:
    ensure_dependencies()
    nodes = list(UG.nodes)
    shelter_set = set(shelter_nodes)
    source_nodes = [node for node in nodes if node not in shelter_set]
    if sample_sources and sample_sources < len(source_nodes):
        rng = random.Random(seed)
        source_nodes = rng.sample(source_nodes, sample_sources)

    print(f"[shelter-bc] sources={len(source_nodes)} shelters={len(shelter_nodes)}")
    started = time.time()
    paths = nx.multi_source_dijkstra_path(UG, shelter_nodes, weight="length")
    scores = {node: 0.0 for node in nodes}
    used = 0
    for src in source_nodes:
        path = paths.get(src)
        if not path or len(path) < 3:
            continue
        for node in path[1:-1]:
            scores[node] += 1.0
        used += 1
    max_score = max(scores.values()) if scores else 0.0
    if max_score > 0:
        scores = {node: value / max_score for node, value in scores.items()}
    print(f"[shelter-bc] paths_used={used}, seconds={time.time() - started:.1f}")
    return scores


def build_rows(nodes, standard_bc, shelter_bc, node_load) -> list[dict]:
    rows = []
    for node in nodes:
        rows.append(
            {
                "node": str(node),
                "standard_bc": float(standard_bc.get(node, 0.0)),
                "shelter_aware_bc": float(shelter_bc.get(node, 0.0)),
                "observed_load": float(node_load.get(node, 0.0)),
            }
        )
    return rows


def correlations(rows: list[dict]) -> dict:
    ensure_dependencies()
    standard = np.array([row["standard_bc"] for row in rows], dtype=float)
    shelter = np.array([row["shelter_aware_bc"] for row in rows], dtype=float)
    load = np.array([row["observed_load"] for row in rows], dtype=float)
    loaded = load > 0

    return {
        "n_nodes": int(len(rows)),
        "n_loaded": int(loaded.sum()),
        "standard_pearson_all": safe_pearson(standard, load),
        "shelter_pearson_all": safe_pearson(shelter, load),
        "standard_spearman_all": safe_spearman(standard, load),
        "shelter_spearman_all": safe_spearman(shelter, load),
        "standard_pearson_loaded": safe_pearson(standard[loaded], load[loaded]),
        "shelter_pearson_loaded": safe_pearson(shelter[loaded], load[loaded]),
        "standard_spearman_loaded": safe_spearman(standard[loaded], load[loaded]),
        "shelter_spearman_loaded": safe_spearman(shelter[loaded], load[loaded]),
    }


def write_outputs(rows: list[dict], summary: dict, out_dir: Path) -> None:
    ensure_dependencies()
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "shelter_aware_bc_nodes.csv"
    json_path = out_dir / "correlation.json"
    png_path = out_dir / "correlation.png"

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    standard = np.array([row["standard_bc"] for row in rows], dtype=float)
    shelter = np.array([row["shelter_aware_bc"] for row in rows], dtype=float)
    load = np.array([row["observed_load"] for row in rows], dtype=float)
    r_standard = summary["standard_pearson_loaded"][0]
    r_shelter = summary["shelter_pearson_loaded"][0]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].scatter(standard, load, s=8, alpha=0.35, color="#4C78A8")
    axes[0].set_title(
        f"Standard BC vs load (loaded r={r_standard:.3f})"
        if r_standard is not None
        else "Standard BC vs load"
    )
    axes[0].set_xlabel("standard node betweenness")
    axes[0].set_ylabel("observed in-edge load")
    axes[0].grid(alpha=0.25)

    axes[1].scatter(shelter, load, s=8, alpha=0.35, color="#2CA02C")
    axes[1].set_title(
        f"Shelter-aware BC vs load (loaded r={r_shelter:.3f})"
        if r_shelter is not None
        else "Shelter-aware BC vs load"
    )
    axes[1].set_xlabel("shelter-aware centrality")
    axes[1].set_ylabel("observed in-edge load")
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(png_path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    print(f"[csv] saved {csv_path}")
    print(f"[json] saved {json_path}")
    print(f"[plot] saved {png_path}")


def main() -> None:
    args = parse_args()
    ensure_dependencies()
    graphml = ROOT / "road_graph_cache" / f"{args.city}_{args.district}.graphml"
    edge_csv = (
        Path(args.edge_csv)
        if args.edge_csv
        else TRACE
        / args.output_base
        / f"t15_{args.city}_{args.district}_{args.home_distribution}"
        / "graph_on"
        / "edge_observations.csv"
    )
    out_dir = (
        Path(args.out_dir)
        if args.out_dir
        else TRACE
        / args.output_base
        / "_shelter_aware"
        / f"{args.city}_{args.district}_{args.home_distribution}"
    )

    print(f"[city] {args.city}/{args.district} ({args.home_distribution})")
    print(f"[graph] {graphml}")
    print(f"[edges] {edge_csv}")
    G, UG = largest_component_graph(graphml)
    shelters = load_shelter_points(args.city, args.district)
    shelter_nodes = snap_shelters(G, UG, shelters)
    if not shelter_nodes:
        raise RuntimeError("No shelter nodes snapped into the largest component")
    node_load = read_node_load(G, UG, edge_csv)

    print("[standard-bc] computing sampled Brandes betweenness")
    standard_bc = nx.betweenness_centrality(
        UG,
        k=min(args.standard_bc_k, UG.number_of_nodes()),
        weight="length",
        seed=args.seed,
    )
    shelter_bc = shelter_aware_centrality(
        UG,
        shelter_nodes=shelter_nodes,
        sample_sources=args.sample_sources,
        seed=args.seed,
    )

    rows = build_rows(list(UG.nodes), standard_bc, shelter_bc, node_load)
    summary = correlations(rows)
    summary.update(
        {
            "city": args.city,
            "district": args.district,
            "home_distribution": args.home_distribution,
            "n_shelter_points": len(shelters),
            "n_shelter_nodes": len(shelter_nodes),
            "sample_sources": args.sample_sources or "all",
            "edge_csv": str(edge_csv),
        }
    )

    print("[summary]")
    for key in (
        "standard_pearson_loaded",
        "shelter_pearson_loaded",
        "standard_spearman_all",
        "shelter_spearman_all",
    ):
        print(f"  {key}: {summary[key]}")
    write_outputs(rows, summary, out_dir)


if __name__ == "__main__":
    main()
