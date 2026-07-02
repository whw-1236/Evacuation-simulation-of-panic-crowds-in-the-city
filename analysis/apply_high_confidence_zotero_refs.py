# -*- coding: utf-8 -*-
"""Apply only high-confidence Zotero placeholder replacements to manuscript drafts.

The script intentionally keeps mixed or low-confidence placeholders in the text.
It also writes a short audit report with the remaining `[REF...]` tokens.
"""
from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path


PAPER_ROOT = Path(r"F:\IJDRR write\论文初稿模块")
REPORT_DIR = PAPER_ROOT / "论文修改建议"
TRACE_REPORT_DIR = (
    Path(__file__).resolve().parents[1] / "trace_output" / "reference_audit"
)


HIGH_CONFIDENCE_REFERENCES = {
    "30": {
        "zotero_key": "6ZELVKR2",
        "label": "Helbing, Farkas & Vicsek (2000)",
        "reference": (
            "Helbing D, Farkas I, Vicsek T. Simulating dynamical features of "
            "escape panic. Nature, 2000, 407: 487-490. "
            "doi:10.1038/35035023."
        ),
    },
    "31": {
        "zotero_key": "D84ADGKE",
        "label": "Ren et al. (2023)",
        "reference": (
            "Ren J, Mao Z, Gong M, Zuo S. Modified social force model "
            "considering emotional contagion for crowd evacuation simulation. "
            "International Journal of Disaster Risk Reduction, 2023."
        ),
    },
    "32": {
        "zotero_key": "VY68L8YI",
        "label": "Cao et al. (2017)",
        "reference": (
            "Cao M, Zhang G, Wang M, Lu D, Liu H. A method of emotion "
            "contagion for crowd evacuation. Physica A: Statistical Mechanics "
            "and its Applications, 2017. doi:10.1016/j.physa.2017.04.137."
        ),
    },
    "33": {
        "zotero_key": "LEWH57PQ",
        "label": "Esmalian et al. (2022)",
        "reference": (
            "Esmalian A, Wang W, Mostafavi A. Multi-agent modeling of "
            "hazard-household-infrastructure nexus for equitable resilience "
            "assessment. Computer-Aided Civil and Infrastructure Engineering, "
            "2022. doi:10.1111/mice.12818."
        ),
    },
    "34": {
        "zotero_key": "P362K7DD",
        "label": "Magoua & Li (2023)",
        "reference": (
            "Magoua J J, Li N. The human factor in the disaster resilience "
            "modeling of critical infrastructure systems. Reliability "
            "Engineering & System Safety, 2023. "
            "doi:10.1016/j.ress.2022.109073."
        ),
    },
    "35": {
        "zotero_key": "72UY8L6N",
        "label": "Yang et al. (2023)",
        "reference": (
            "Yang Y, Liu H, Zhong S, Liu K, Wang M, Huang Q. Agent-based "
            "societal impact modeling for infrastructure disruption and "
            "countermeasures analyses. Sustainable Cities and Society, 2023. "
            "doi:10.1016/j.scs.2023.104737."
        ),
    },
}


REPLACEMENTS = {
    "02_Related_Work_draft_v1.md": {
        "[REF: Helbing, Farkas & Vicsek, 2000]": "[30]",
        "[REF: Ren et al. — emotional-contagion SFM]": "[31]",
        "[REF: Cao et al.]": "[32]",
        "[REF: infrastructure-resilience refs]": "[33-35]",
    },
    "03_Methodology_draft_v1.md": {
        "[REF: Ren et al. — *Modified social force model considering emotional contagion*]": "[31]",
        "[REF: Ren et al.]": "[31]",
    },
}


LOW_CONFIDENCE_REASON = {
    "[REF]": "Generic marker; no source identity.",
    "[REF: ...]": "Draft-level generic marker; not a bibliographic item.",
    "[REF: Author, Year]": "Draft instruction placeholder; not a bibliographic item.",
    "[REF: Helbing & Molnár, 1995]": (
        "Zotero audit returns Helbing et al. 2000, not the original 1995 SFM paper."
    ),
    "[REF: Helbing & Molnár, 1995; Helbing et al., 2000]": (
        "Mixed placeholder; only the 2000 item is verified, while the 1995 item remains unresolved."
    ),
    "[REF: Moussaïd et al., 2009]": "Zotero match is a 2010 PLoS ONE item; year/source mismatch needs manual confirmation.",
    "[REF: Durupinar et al.; Zhou et al.]": "Candidate item authors do not match the placeholder authors.",
    "[REF: Durupinar/ASCRIBE]": "Candidate item does not verify the ASCRIBE source identity.",
    "[REF: Wang et al.; Helbing]": "Composite placeholder returns multiple plausible but non-equivalent items.",
    "[REF: Yuen et al., 2020; Billore & Anisimova, 2021]": "Audit only matches by year, not title or authors.",
    "[REF: Yuen et al., 2020]": "Audit only matches by year, not title or authors.",
    "[REF: panic-buying review]": "Current matches are evacuation panic papers, not panic-buying reviews.",
    "[REF: panic-buying segmentation study]": "Current matches are evacuation panic papers, not panic-buying segmentation studies.",
    "[REF: Rubin & Rogers, 2019, IJDRR 38:101226]": "Audit returns blackout-related but not exact Rubin & Rogers metadata.",
    "[REF: Manhattan-2019 resilience study, IJDRR]": "No exact Manhattan 2019 IJDRR item identified.",
    "[REF: Freeman, 1977]": "No Zotero match in current local library.",
    "[REF: Crucitti et al., 2006; Jenelius et al., 2006; disaster-network-centrality refs]": "No exact Zotero match in current local library.",
    "[REF: Lazarus & Folkman, 1984]": "No exact Lazarus & Folkman book item identified.",
    "[REF: Greenshields, 1934]": "Top audit candidate is a 2025 review/case study, not the 1934 source.",
    "[REF: panic-speed-factor study]": "Multiple high-scoring panic-speed candidates; exact empirical source not confirmed.",
    "[REF: Boeing, 2017]": "Audit matches only by year; OSMnx paper not confirmed in current Zotero audit.",
    "[REF: Lindell & Perry, 2012 *Protective Action Decision Model*]": "No Zotero match in current local library.",
    "[REF: Cova & Johnson, 2008 *traffic-shed evacuation*]": "Audit returns generic evacuation-choice items, not the named traffic-shed study.",
    "[REF: provincial DRM bureaus]": "Institutional data source placeholder; not a journal reference.",
}


REF_PATTERN = re.compile(r"\[REF[^\]]*\]")


def apply_replacements() -> list[dict[str, str | int]]:
    actions = []
    for filename, replacements in REPLACEMENTS.items():
        path = PAPER_ROOT / filename
        original = path.read_text(encoding="utf-8")
        updated = original
        for old, new in replacements.items():
            count = updated.count(old)
            if count:
                updated = updated.replace(old, new)
            actions.append(
                {
                    "file": filename,
                    "old": old,
                    "new": new,
                    "count": count,
                }
            )
        if updated != original:
            path.write_text(updated, encoding="utf-8")
    return actions


def scan_remaining_refs() -> tuple[Counter[str], dict[str, list[str]]]:
    counts: Counter[str] = Counter()
    locations: dict[str, list[str]] = defaultdict(list)
    for path in sorted(PAPER_ROOT.glob("*_draft_v1.md")):
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for token in REF_PATTERN.findall(line):
                counts[token] += 1
                if len(locations[token]) < 5:
                    locations[token].append(f"{path.name}:{line_no}")
    return counts, locations


def write_remaining_csv(counts: Counter[str], locations: dict[str, list[str]]) -> Path:
    TRACE_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = TRACE_REPORT_DIR / "remaining_low_confidence_refs_2026-07-02.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["token", "count", "locations", "reason"]
        )
        writer.writeheader()
        for token, count in sorted(counts.items()):
            writer.writerow(
                {
                    "token": token,
                    "count": count,
                    "locations": "; ".join(locations[token]),
                    "reason": LOW_CONFIDENCE_REASON.get(
                        token, "Unresolved placeholder; keep until exact Zotero/source match is confirmed."
                    ),
                }
            )
    return csv_path


def write_report(
    actions: list[dict[str, str | int]],
    counts: Counter[str],
    locations: dict[str, list[str]],
    csv_path: Path,
) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "P1-2_high_confidence_zotero_replacements_2026-07-02.md"
    trace_report_path = TRACE_REPORT_DIR / report_path.name

    lines = [
        "# P1-2 High-confidence Zotero replacements -- 2026-07-02",
        "",
        "## Replacement policy",
        "",
        "- Only exact, high-confidence Zotero matches were converted to numbered citations.",
        "- Low-confidence, mixed, or generic placeholders were retained as `[REF...]` and listed below.",
        "- Numbering continues after the previously established local MML references `[26]-[29]`.",
        "",
        "## Applied replacements",
        "",
        "| File | Placeholder | Citation | Count |",
        "|---|---|---:|---:|",
    ]
    for action in actions:
        if int(action["count"]) <= 0:
            continue
        lines.append(
            f"| `{action['file']}` | `{action['old']}` | {action['new']} | {action['count']} |"
        )

    lines.extend(
        [
            "",
            "## Numbered reference candidates",
            "",
            "| No. | Zotero key | Reference candidate |",
            "|---:|---|---|",
        ]
    )
    for no, item in HIGH_CONFIDENCE_REFERENCES.items():
        lines.append(
            f"| [{no}] | `{item['zotero_key']}` | {item['reference']} |"
        )

    lines.extend(
        [
            "",
            "## Remaining low-confidence placeholders",
            "",
            f"- Machine-readable list: `{csv_path}`.",
            "",
            "| Token | Count | Locations | Reason retained |",
            "|---|---:|---|---|",
        ]
    )
    for token, count in sorted(counts.items()):
        loc = "; ".join(locations[token])
        reason = LOW_CONFIDENCE_REASON.get(
            token, "Unresolved placeholder; keep until exact Zotero/source match is confirmed."
        )
        lines.append(f"| `{token}` | {count} | {loc} | {reason} |")

    text = "\n".join(lines) + "\n"
    report_path.write_text(text, encoding="utf-8")
    trace_report_path.write_text(text, encoding="utf-8")
    return report_path


def main() -> None:
    actions = apply_replacements()
    counts, locations = scan_remaining_refs()
    csv_path = write_remaining_csv(counts, locations)
    report_path = write_report(actions, counts, locations, csv_path)
    print(f"report={report_path}")
    print(f"remaining_csv={csv_path}")
    for action in actions:
        print(
            f"{action['file']}: {action['old']} -> {action['new']} "
            f"({action['count']})"
        )


if __name__ == "__main__":
    main()
