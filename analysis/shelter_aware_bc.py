# -*- coding: utf-8 -*-
"""Shelter-aware centrality prototype for the M4 discussion.

This script tests whether a shelter-aware shortest-path centrality is closer to
observed simulation load than standard node betweenness. It is intentionally a
post-processor: it reads an existing graph-on edge_observations.csv and does not
run a simulation.

Default input is the MML F2 POI run for Xiamen / Siming. Use --city/--district
and --home-distribution to run the same diagnostic for other M4 outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import osmnx as ox
from scipy.stats import pearsonr, spearmanr


ROOT = Path(__file__).resolve().parents[1]
MAP_DIR = ROOT / "simulation map data"
TRACE = ROOT / "trace_output"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Shelter-aware BC vs observed road load")
    p.add_argument("--city", default="厦门市")
    p.add_argument("--district", default="思明区")
    p.add_argument("--home-distribution", default="poi", choices=["poi", "uniform"])
    p.add_argument("--output-base", default="M4_MML_F2_home_dist")
    p.add_argument("--edge-csv", default=None)
    p.add_argument("--out-dir", default=None)
    p.add_argument(
        "--sample-sources",
        type=int,
        default=0,
        help="Number of source nodes for shelter-aware paths; 0 means all nodes.",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--standard-bc-k", type=int, default=200)
    return p.parse_args()


def safe_pearson(x: np.ndarray, y: np.ndarray) -> tuple[float | None, float | None]:
    if len(x) < 3 or float(np.std(x)) <= 1e-12 or float(np.std(y)) <= 1e-12:
        return None, None
    r, p = pearsonr(x, y)
    return float(r), float(p)


def safe_spearman(x: np.ndarray, y: np.ndarray) -> tuple[float | None, float | None]:
    if len(x) < 3 or float(np.std(x)) <= 1e-12 or float(np.std(y)) <= 1e-12:
        return None, None
    rho, p = spearmanr(x, y)
    return float(rho), float(p)


def load_shelter_points(city: str, district: str) -> list[tuple[float, float, str]]:
    csv_path = MAP_DIR / city / district / f"{district}POI" / "应急.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Shelter CSV not found: {csv_path}")

    points: list[tuple[float, float, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            if "管理局" in name:
                continue
            if not any(key in name for key in ("避难", "避灾", "紧急避", "应急")):
                continue
            try:
                lon = float(row["lon"])
                lat = float(row["lat"])
            except Exception:
                continue
            points.append((lon, lat, name))
    if not points:
        raise RuntimeError(f"No shelter-like points found in {csv_path}")
    return points


def largest_component_graph(graphml: Path) -> tuple[nx.MultiDiGraph, nx.Graph]:
    G = ox.io.load_graphml(graphml)
    UG_all = nx.Graph(G)
    largest = max(nx.connected_components(UG_all), key=len)
    UG = UG_all.subgraph(largest).copy()
    return G, UG


def snap_shelters(G: nx.MultiDiGraph, UG: nx.Graph, shelters) -> list:
    xs = [p[0] for p in shelters]
    ys = [p[1] for p in shelters]
    snapped = ox.distance.nearest_nodes(G, X=xs, Y=ys)
    nodes = []
    for n in snapped:
        if n in UG:
            nodes.append(n)
        elif str(n) in UG:
            nodes.append(str(n))
    return sorted(set(nodes), key=str)


def read_node_load(G: nx.MultiDiGraph, UG: nx.Graph, edge_csv: Path) -> dict:
    edge_obs: dict[tuple[str, str], float] = {}
    with edge_csv.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            u = str(row["u"])
            v = str(row["v"])
            edge_obs[(u, v)] = edge_obs.get((u, v), 0.0) + float(row["cum_occupancy"])

    node_load = {}
    for n in UG.nodes:
        n_str = str(n)
        load = 0.0
        neighbors = G.predecessors(n) if G.is_directed() and n in G else G.neighbors(n)
        for nb in neighbors:
            load += edge_obs.get((str(nb), n_str), 0.0)
        node_load[n] = load
    return node_load


def shelter_aware_centrality(
    UG: nx.Graph,
    shelter_nodes: list,
    sample_sources: int,
    seed: int,
) -> dict:
    nodes = list(UG.nodes)
    source_nodes = [n for n in nodes if n not in set(shelter_nodes)]
    if sample_sources and sample_sources < len(source_nodes):
        rng = random.Random(seed)
        source_nodes = rng.sample(source_nodes, sample_sources)

    print(f"[shelter-bc] sources={len(source_nodes)} shelters={len(shelter_nodes)}")
    t0 = time.time()
    paths = nx.multi_source_dijkstra_path(UG, shelter_nodes, weight="length")
    scores = {n: 0.0 for n in nodes}
    used = 0
    for src in source_nodes:
        path = paths.get(src)
        if not path or len(path) < 3:
            continue
        # path is nearest shelter -> src; internal nodes are still path[1:-1].
        for n in path[1:-1]:
            scores[n] += 1.0
        used += 1
    max_score = max(scores.values()) if scores else 0.0
    if max_score > 0:
        scores = {n: v / max_score for n, v in scores.items()}
    print(f"[shelter-bc] paths_used={used}, seconds={time.time() - t0:.1f}")
    return scores


def build_rows(nodes, standard_bc, shelter_bc, node_load) -> list[dict]:
    rows = []
    for n in nodes:
        rows.append(
            {
                "node": str(n),
                "standard_bc": float(standard_bc.get(n, 0.0)),
                "shelter_aware_bc": float(shelter_bc.get(n, 0.0)),
                "observed_load": float(node_load.get(n, 0.0)),
            }
        )
    return rows


def correlations(rows: list[dict]) -> dict:
    std = np.array([r["standard_bc"] for r in rows], dtype=float)
    sh = np.array([r["shelter_aware_bc"] for r in rows], dtype=float)
    load = np.array([r["observed_load"] for r in rows], dtype=float)
    mask = load > 0

    out = {
        "n_nodes": int(len(rows)),
        "n_loaded": int(mask.sum()),
        "standard_pearson_all": safe_pearson(std, load),
        "shelter_pearson_all": safe_pearson(sh, load),
        "standard_spearman_all": safe_spearman(std, load),
        "shelter_spearman_all": safe_spearman(sh, load),
        "standard_pearson_loaded": safe_pearson(std[mask], load[mask]),
        "shelter_pearson_loaded": safe_pearson(sh[mask], load[mask]),
    }
    return out


def write_outputs(rows: list[dict], summary: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "shelter_aware_bc_nodes.csv"
    json_path = out_dir / "correlation.json"
    png_path = out_dir / "correlation.png"

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    std = np.array([r["standard_bc"] for r in rows], dtype=float)
    sh = np.array([r["shelter_aware_bc"] for r in rows], dtype=float)
    load = np.array([r["observed_load"] for r in rows], dtype=float)
    r_std = summary["standard_pearson_loaded"][0]
    r_sh = summary["shelter_pearson_loaded"][0]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].scatter(std, load, s=8, alpha=0.35, color="#4C78A8")
    axes[0].set_title(f"Standard BC vs load (loaded r={r_std:.3f})" if r_std is not None else "Standard BC vs load")
    axes[0].set_xlabel("standard node betweenness")
    axes[0].set_ylabel("observed in-edge load")
    axes[0].grid(alpha=0.25)

    axes[1].scatter(sh, load, s=8, alpha=0.35, color="#2CA02C")
    axes[1].set_title(f"Shelter-aware BC vs load (loaded r={r_sh:.3f})" if r_sh is not None else "Shelter-aware BC vs load")
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
    graphml = ROOT / "road_graph_cache" / f"{args.city}_{args.district}.graphml"
    edge_csv = Path(args.edge_csv) if args.edge_csv else (
        TRACE
        / args.output_base
        / f"t15_{args.city}_{args.district}_{args.home_distribution}"
        / "graph_on"
        / "edge_observations.csv"
    )
    out_dir = Path(args.out_dir) if args.out_dir else (
        TRACE / args.output_base / "_shelter_aware" / f"{args.city}_{args.district}_{args.home_distribution}"
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
