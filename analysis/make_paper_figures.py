# -*- coding: utf-8 -*-
"""Create IJDRR-ready manuscript figures from existing simulation artifacts."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper_figures"

CITY_SPECS = [
    {
        "city": "北京市",
        "district": "东城区",
        "label": "Beijing / Dongcheng",
        "panel": "a",
    },
    {
        "city": "厦门市",
        "district": "思明区",
        "label": "Xiamen / Siming",
        "panel": "b",
    },
    {
        "city": "沈阳市",
        "district": "沈河区",
        "label": "Shenyang / Shenhe",
        "panel": "c",
    },
]

POI_STYLES = {
    "应急": {"label": "Shelter", "marker": "^", "color": "#0072B2", "size": 30, "z": 5},
    "商店": {"label": "Shop", "marker": "s", "color": "#D55E00", "size": 16, "z": 4},
    "医院": {"label": "Hospital", "marker": "P", "color": "#009E73", "size": 22, "z": 4},
    "学校": {"label": "School", "marker": "o", "color": "#CC79A7", "size": 10, "z": 3},
    "政府": {"label": "Government", "marker": "D", "color": "#E69F00", "size": 11, "z": 3},
    "工业": {"label": "Industrial", "marker": "x", "color": "#666666", "size": 12, "z": 3},
}

DISPLAY_ORDER = ["应急", "商店", "医院", "学校", "政府", "工业"]

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "axes.unicode_minus": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 150,
        "savefig.dpi": 300,
    }
)


def ensure_out() -> None:
    OUT.mkdir(parents=True, exist_ok=True)


def save_figure(fig: plt.Figure, stem: str) -> None:
    ensure_out()
    for ext in ("png", "pdf", "svg"):
        fig.savefig(OUT / f"{stem}.{ext}", bbox_inches="tight", facecolor="white")


def add_panel_label(ax: plt.Axes, label: str) -> None:
    ax.text(
        0.01,
        0.99,
        label,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=11,
        fontweight="bold",
    )


def box(ax: plt.Axes, xy, w, h, text, fc="#F7F7F7", ec="#3A3A3A", fs=8.5):
    patch = FancyBboxPatch(
        xy,
        w,
        h,
        boxstyle="round,pad=0.015,rounding_size=0.025",
        linewidth=1.0,
        edgecolor=ec,
        facecolor=fc,
    )
    ax.add_patch(patch)
    ax.text(xy[0] + w / 2, xy[1] + h / 2, text, ha="center", va="center", fontsize=fs)
    return patch


def arrow(ax: plt.Axes, start, end, color="#3A3A3A", lw=1.0, rad=0.0):
    arr = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=10,
        linewidth=lw,
        color=color,
        connectionstyle=f"arc3,rad={rad}",
    )
    ax.add_patch(arr)
    return arr


def make_fig1_framework() -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    box(ax, (0.04, 0.72), 0.22, 0.13, "Blackout exposure\nlighting, payment,\ncommunication loss", "#E8F1F2")
    box(ax, (0.36, 0.72), 0.24, 0.13, "Stress appraisal\n$\\sigma_i(t)$, emotion,\npanic contagion", "#F2F0E6")
    box(ax, (0.71, 0.72), 0.23, 0.13, "Tactical choice\nMNL over home,\nhoard, herd, flee", "#EBF2E9")

    box(ax, (0.06, 0.42), 0.22, 0.13, "Social-force motion\nrepulsion, desired\nvelocity, density", "#F7F7F7")
    box(ax, (0.38, 0.42), 0.22, 0.13, "Road/shelter graph\nsnap, shortest path,\ncongestion update", "#EEF0F7")
    box(ax, (0.70, 0.42), 0.24, 0.13, "Observed cascade\nflee share, herd share,\nedge load", "#F8ECEC")

    box(ax, (0.22, 0.12), 0.24, 0.12, "Information layer\nacquaintance updates,\nstore/shelter visibility", "#FEF6E4")
    box(ax, (0.56, 0.12), 0.24, 0.12, "Planning outputs\nbehavioural levers,\ndemand-aware centrality", "#EDE7F6")

    arrow(ax, (0.26, 0.785), (0.36, 0.785))
    arrow(ax, (0.60, 0.785), (0.71, 0.785))
    arrow(ax, (0.82, 0.72), (0.82, 0.55))
    arrow(ax, (0.70, 0.485), (0.60, 0.485))
    arrow(ax, (0.38, 0.485), (0.28, 0.485))
    arrow(ax, (0.17, 0.55), (0.17, 0.72), rad=-0.22)
    arrow(ax, (0.28, 0.18), (0.38, 0.42), color="#8A6D1D")
    arrow(ax, (0.46, 0.18), (0.71, 0.72), color="#8A6D1D", rad=0.18)
    arrow(ax, (0.82, 0.42), (0.68, 0.24), color="#6A51A3")

    ax.text(0.5, 0.96, "Network-embedded blackout crowd simulation", ha="center", va="center", fontsize=10.5)

    save_figure(fig, "Fig1_model_framework")
    plt.close(fig)


def read_graph(city: str, district: str) -> nx.Graph:
    return nx.read_graphml(ROOT / "road_graph_cache" / f"{city}_{district}.graphml")


def edge_segments(G: nx.Graph):
    nodes = G.nodes
    if G.is_multigraph():
        iterator = G.edges(keys=True)
        for u, v, _ in iterator:
            yield float(nodes[u]["x"]), float(nodes[u]["y"]), float(nodes[v]["x"]), float(nodes[v]["y"])
    else:
        for u, v in G.edges():
            yield float(nodes[u]["x"]), float(nodes[u]["y"]), float(nodes[v]["x"]), float(nodes[v]["y"])


def read_poi(city: str, district: str, category: str):
    poi_file = ROOT / "simulation map data" / city / district / f"{district}POI" / f"{category}.csv"
    if not poi_file.exists():
        return np.empty((0, 2), dtype=float)
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            rows = []
            with open(poi_file, "r", encoding=encoding, newline="") as f:
                rdr = csv.DictReader(f)
                for row in rdr:
                    try:
                        rows.append((float(row["lon"]), float(row["lat"])))
                    except (KeyError, TypeError, ValueError):
                        continue
            return np.asarray(rows, dtype=float) if rows else np.empty((0, 2), dtype=float)
        except UnicodeDecodeError:
            continue
    return np.empty((0, 2), dtype=float)


def graph_bounds(G: nx.Graph):
    xs = np.asarray([float(data["x"]) for _, data in G.nodes(data=True)], dtype=float)
    ys = np.asarray([float(data["y"]) for _, data in G.nodes(data=True)], dtype=float)
    xpad = max((xs.max() - xs.min()) * 0.04, 1e-6)
    ypad = max((ys.max() - ys.min()) * 0.04, 1e-6)
    return xs.min() - xpad, xs.max() + xpad, ys.min() - ypad, ys.max() + ypad


def clip_points_to_graph(pts: np.ndarray, bounds):
    if pts.size == 0:
        return pts
    xmin, xmax, ymin, ymax = bounds
    mask = (pts[:, 0] >= xmin) & (pts[:, 0] <= xmax) & (pts[:, 1] >= ymin) & (pts[:, 1] <= ymax)
    return pts[mask]


def make_fig2_spatial_context() -> None:
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 3.35))

    for ax, spec in zip(axes, CITY_SPECS):
        G = read_graph(spec["city"], spec["district"])
        bounds = graph_bounds(G)
        for x1, y1, x2, y2 in edge_segments(G):
            ax.plot([x1, x2], [y1, y2], color="#C8C8C8", linewidth=0.18, alpha=0.65, zorder=1)

        for cat in DISPLAY_ORDER:
            pts = clip_points_to_graph(read_poi(spec["city"], spec["district"], cat), bounds)
            if pts.size == 0:
                continue
            style = POI_STYLES[cat]
            alpha = 0.85 if cat in ("应急", "商店", "医院") else 0.45
            scatter_kwargs = {
                "s": style["size"],
                "marker": style["marker"],
                "color": style["color"],
                "linewidths": 0.25,
                "alpha": alpha,
                "zorder": style["z"],
            }
            if style["marker"] != "x":
                scatter_kwargs["edgecolors"] = "white"
            ax.scatter(pts[:, 0], pts[:, 1], **scatter_kwargs)

        add_panel_label(ax, spec["panel"])
        ax.set_title(f"{spec['label']}\n{G.number_of_nodes():,} nodes; {G.number_of_edges():,} edges", fontsize=8.2)
        ax.set_xlim(bounds[0], bounds[1])
        ax.set_ylim(bounds[2], bounds[3])
        ax.set_aspect("equal", adjustable="box")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_color("#777777")
            spine.set_linewidth(0.5)

    handles = [
        Line2D(
            [0],
            [0],
            marker=POI_STYLES[cat]["marker"],
            linestyle="None",
            label=POI_STYLES[cat]["label"],
            markerfacecolor=POI_STYLES[cat]["color"] if POI_STYLES[cat]["marker"] != "x" else "none",
            markeredgecolor=POI_STYLES[cat]["color"] if POI_STYLES[cat]["marker"] == "x" else "white",
            markersize=6,
        )
        for cat in DISPLAY_ORDER
    ]
    fig.legend(handles=handles, ncol=6, loc="lower center", bbox_to_anchor=(0.5, 0.02), frameon=False, fontsize=7.3)
    fig.suptitle("Road-network and POI substrate used by the graph-on simulations", fontsize=10.2)
    fig.subplots_adjust(left=0.035, right=0.995, top=0.78, bottom=0.18, wspace=0.10)
    save_figure(fig, "Fig2_study_area_network_poi")
    plt.close(fig)


def make_fig3_vis_gate() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.7), constrained_layout=True)

    for ax, mode in zip(axes, ("graph-off", "graph-on")):
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.set_title(mode, fontsize=11, fontweight="bold")

        if mode == "graph-off":
            box(ax, (0.07, 0.74), 0.36, 0.12, "Shelter node\nnot snapped", "#F3F3F3")
            box(ax, (0.57, 0.74), 0.34, 0.12, "$VIS_i=0$\n$V_{flee}=-\\infty$", "#F3F3F3")
            arrow(ax, (0.43, 0.80), (0.57, 0.80), color="#777777")
            box(ax, (0.10, 0.45), 0.78, 0.13, "Choice set\n$\\mathcal{K}_i=\\{home, hoard, herd\\}$", "#FFF6E6")
            box(ax, (0.18, 0.18), 0.23, 0.12, "Herd", "#E8E8E8")
            box(ax, (0.56, 0.18), 0.23, 0.12, "Home / hoard", "#E8E8E8")
            arrow(ax, (0.50, 0.45), (0.30, 0.30))
            arrow(ax, (0.50, 0.45), (0.68, 0.30))
            ax.text(0.5, 0.05, "No operational shelter-seeking action", ha="center", fontsize=8, color="#555555")
        else:
            box(ax, (0.07, 0.74), 0.36, 0.12, "Shelter node\nsnapped to graph", "#EAF4FB")
            box(ax, (0.57, 0.74), 0.34, 0.12, "$VIS_i=1$\nfinite $V_{flee}$", "#EAF4FB")
            arrow(ax, (0.43, 0.80), (0.57, 0.80), color="#0072B2")
            box(ax, (0.10, 0.45), 0.78, 0.13, "Choice set\n$\\mathcal{K}_i=\\{home, hoard, herd, flee\\}$", "#EAF7EA")
            box(ax, (0.12, 0.18), 0.20, 0.12, "Herd", "#E8E8E8")
            box(ax, (0.40, 0.18), 0.20, 0.12, "Flee", "#DFF0FF", ec="#0072B2")
            box(ax, (0.68, 0.18), 0.20, 0.12, "Home /\nhoard", "#E8E8E8")
            arrow(ax, (0.50, 0.45), (0.22, 0.30))
            arrow(ax, (0.50, 0.45), (0.50, 0.30), color="#0072B2", lw=1.4)
            arrow(ax, (0.50, 0.45), (0.78, 0.30))
            ax.text(0.5, 0.05, "Flee enters the softmax and draws probability from herd", ha="center", fontsize=8, color="#555555")

        ax.text(
            0.5,
            0.66,
            "$P_{ik}=\\exp(\\beta V_{ik})/\\sum_{m\\in\\mathcal{K}_i}\\exp(\\beta V_{im})$",
            ha="center",
            va="center",
            fontsize=7.8,
        )

    fig.suptitle("Visibility-conditioned MNL choice-set expansion", fontsize=10.5)
    save_figure(fig, "Fig3_mnl_vis_gate")
    plt.close(fig)


def node_load_from_edges(G: nx.Graph, edge_csv: Path):
    node_load = {str(n): 0.0 for n in G.nodes}
    with open(edge_csv, "r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            v = str(row.get("v", ""))
            try:
                node_load[v] = node_load.get(v, 0.0) + float(row.get("cum_occupancy", 0.0))
            except ValueError:
                continue
    return node_load


def compute_bc(G: nx.Graph):
    undirected = nx.Graph(G)
    for _, _, data in undirected.edges(data=True):
        try:
            data["length"] = float(data.get("length", 1.0))
        except (TypeError, ValueError):
            data["length"] = 1.0
    largest = max(nx.connected_components(undirected), key=len)
    main = undirected.subgraph(largest).copy()
    bc = nx.betweenness_centrality(main, k=min(200, main.number_of_nodes()), weight="length", seed=42)
    return main, bc


def pearson(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size < 3 or x.std() <= 1e-12 or y.std() <= 1e-12:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def make_fig6_bc_load() -> None:
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 3.05))

    for ax, spec in zip(axes, CITY_SPECS):
        G = read_graph(spec["city"], spec["district"])
        main, bc = compute_bc(G)
        edge_csv = (
            ROOT
            / "trace_output"
            / "M4_MML_F2_home_dist"
            / f"t15_{spec['city']}_{spec['district']}_poi"
            / "graph_on"
            / "edge_observations.csv"
        )
        load = node_load_from_edges(G, edge_csv)
        nodes = [n for n in main.nodes if n in bc]
        bc_arr = np.asarray([bc[n] for n in nodes], dtype=float)
        load_arr = np.asarray([load.get(str(n), 0.0) for n in nodes], dtype=float)
        loaded = load_arr > 0
        r_loaded = pearson(bc_arr[loaded], load_arr[loaded])

        ax.scatter(bc_arr, np.log10(load_arr + 1.0), s=4, color="#C7C7C7", alpha=0.45, linewidths=0)
        ax.scatter(
            bc_arr[loaded],
            np.log10(load_arr[loaded] + 1.0),
            s=9,
            color="#0072B2",
            alpha=0.65,
            linewidths=0,
            label="loaded nodes",
        )
        top_idx = np.argsort(-bc_arr)[:10]
        ax.scatter(
            bc_arr[top_idx],
            np.log10(load_arr[top_idx] + 1.0),
            s=22,
            color="#D55E00",
            alpha=0.95,
            edgecolors="white",
            linewidths=0.25,
            label="top-10 BC",
            zorder=4,
        )

        add_panel_label(ax, spec["panel"])
        ax.set_title(f"{spec['label']}\nloaded n={int(loaded.sum())}, r={r_loaded:+.3f}", fontsize=8.0)
        ax.tick_params(axis="both", labelsize=7.5)
        ax.grid(True, axis="both", alpha=0.25)

    handles = [
        Line2D([0], [0], marker="o", linestyle="None", color="#0072B2", label="loaded node", markersize=4),
        Line2D([0], [0], marker="o", linestyle="None", color="#D55E00", label="top-10 BC", markersize=5),
    ]
    fig.supxlabel("node betweenness", y=0.09, fontsize=8.8)
    fig.supylabel("observed load, log10(cum+1)", x=0.02, fontsize=8.8)
    fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.0), fontsize=8)
    fig.suptitle("Topology-only betweenness does not explain realised road load", fontsize=10.0)
    fig.subplots_adjust(left=0.09, right=0.995, top=0.73, bottom=0.24, wspace=0.20)
    save_figure(fig, "Fig6_bc_load_three_city")
    plt.close(fig)


def write_captions() -> None:
    ensure_out()
    captions = """# Proposed IJDRR Main-Text Figures

## Fig. 1. Model framework
Network-embedded blackout crowd simulation framework. The model couples blackout exposure, stress appraisal, an MNL tactical-choice layer, social-force movement and graph-routed shelter/road dynamics. The closed loop shows how stress changes tactical choice, choice changes movement and realised movement feeds back into density-mediated stress and road-load outcomes.

## Fig. 2. Study-area spatial substrates
Road-network and POI substrates used by the graph-on simulations for Beijing/Dongcheng, Xiamen/Siming and Shenyang/Shenhe. Grey lines denote OSM road-graph edges; markers show emergency shelters, shops, hospitals and other POI classes used by the behavioural-choice and routing layers. This figure should be placed in the experimental-design section before the graph-off/graph-on protocol.

## Fig. 3. MNL visibility gate
Visibility-conditioned choice-set expansion in the MNL tactical-choice layer. In graph-off, no shelter node is snapped to the road graph and the flee alternative is removed from the choice set by setting V_flee to negative infinity. In graph-on, the shelter alternative becomes visible and finite, so flee competes with home, hoard and herd in the same softmax denominator and can substitute away from herding.

## Fig. 6. BC-load mismatch
Three-city comparison between topology-only node betweenness centrality and realised graph-on road load. The y-axis uses log10(cumulative load + 1) for visibility, while the reported r is Pearson correlation on nodes with non-zero observed load. The weak city-level correlations indicate that topology-only BC is a poor proxy for behaviourally generated road demand under the active shelter-seeking cascade.
"""
    (OUT / "figure_captions.md").write_text(captions, encoding="utf-8")


def main() -> None:
    ensure_out()
    make_fig1_framework()
    make_fig2_spatial_context()
    make_fig3_vis_gate()
    make_fig6_bc_load()
    write_captions()
    print(f"[done] paper figures written to {OUT}")


if __name__ == "__main__":
    main()
