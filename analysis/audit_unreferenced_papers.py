from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(r"F:\IJDRR write\Crowds_sim\Evacuation-simulation-of-panic-crowds-in-the-city")
PAPER_DIR = Path(r"F:\IJDRR write\论文初稿模块")
MANUSCRIPT = PAPER_DIR / "IJDRR_main_manuscript_v2_refs_resolved.md"
BIB = ROOT / "zotero_export_refs.bib"
PDF_DIRS = [ROOT / "Reference", Path(r"F:\IJDRR write\参考文献")]
REPORT = PAPER_DIR / "unreferenced_papers_audit_2026-07-04.md"


def normalize(text: str) -> str:
    text = text.lower()
    text = text.replace("{", "").replace("}", "")
    text = text.replace("\\&", "&")
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_latex(text: str) -> str:
    text = text.replace("{", "").replace("}", "")
    text = text.replace("\\&", "&")
    text = text.replace("--", "-")
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def token_overlap(a: str, b: str) -> float:
    ta = {t for t in normalize(a).split() if len(t) > 2}
    tb = {t for t in normalize(b).split() if len(t) > 2}
    if not ta:
        return 0.0
    return len(ta & tb) / len(ta)


def looks_cited(title: str, ref_norms: list[str]) -> tuple[bool, float]:
    title_norm = normalize(title)
    if not title_norm:
        return False, 0.0
    best = 0.0
    for ref_norm in ref_norms:
        if title_norm in ref_norm:
            return True, 1.0
        ratio = SequenceMatcher(None, title_norm, ref_norm).ratio()
        overlap = token_overlap(title_norm, ref_norm)
        best = max(best, ratio, overlap)
        if overlap >= 0.72 or ratio >= 0.66:
            return True, best
    return False, best


def extract_references() -> list[str]:
    text = MANUSCRIPT.read_text(encoding="utf-8")
    refs_part = text.split("# References", 1)[1]
    refs = []
    for line in refs_part.splitlines():
        if re.match(r"^\[[0-9]+\]\s+", line.strip()):
            refs.append(line.strip())
    return refs


def parse_bib_entries() -> list[dict[str, str]]:
    text = BIB.read_text(encoding="utf-8", errors="ignore")
    chunks = re.split(r"\n(?=@)", text)
    entries = []
    for chunk in chunks:
        head = re.match(r"@(\w+)\{([^,]+),", chunk.strip())
        if not head:
            continue
        entry = {"type": head.group(1), "key": head.group(2)}
        for field in ["title", "year", "journal", "author", "doi"]:
            match = re.search(rf"\n\s*{field}\s*=\s*\{{(.*?)\}},", chunk, flags=re.S | re.I)
            if match:
                entry[field] = strip_latex(match.group(1))
        if "title" in entry:
            entries.append(entry)
    return entries


def extract_pdf_title(path: Path) -> tuple[str | None, str]:
    stem = path.stem
    number_match = re.match(r"^\[(\d+)\]\s*(.*)$", stem)
    number = number_match.group(1) if number_match else None
    title = number_match.group(2) if number_match else stem
    title = re.sub(r"^(笔记|批注|（批注）)\s*", "", title)
    return number, title.strip()


def collect_pdf_items(ref_norms: list[str]) -> list[dict[str, str | float | bool | None]]:
    seen = set()
    items = []
    for base in PDF_DIRS:
        if not base.exists():
            continue
        for path in base.rglob("*.pdf"):
            number, title = extract_pdf_title(path)
            key = normalize(title)
            if not key or key in seen:
                continue
            seen.add(key)
            cited, score = looks_cited(title, ref_norms)
            try:
                rel = path.relative_to(base)
            except ValueError:
                rel = path
            items.append(
                {
                    "number": number,
                    "title": title,
                    "base": str(base),
                    "relpath": str(rel),
                    "cited": cited,
                    "score": round(score, 3),
                    "category": str(rel.parent),
                }
            )
    return sorted(items, key=lambda x: (str(x["category"]), int(x["number"] or 9999), str(x["title"])))


def priority_label(title: str, category: str) -> str:
    text = normalize(title + " " + category)
    high_keywords = [
        "blackout",
        "power outage",
        "communication",
        "disinformation",
        "infrastructure",
        "macroscale",
        "city evacuation",
        "urban layout",
        "road blockage",
        "tsunami",
        "flood",
        "agent based",
        "human behaviour",
        "power grid",
    ]
    if any(k in text for k in high_keywords):
        return "High"
    if any(k in text for k in ["social force", "panic", "crowd", "pedestrian", "group"]):
        return "Medium"
    return "Low"


def main() -> int:
    refs = extract_references()
    ref_norms = [normalize(ref) for ref in refs]

    bib_entries = parse_bib_entries()
    bib_unreferenced = []
    for entry in bib_entries:
        cited, score = looks_cited(entry["title"], ref_norms)
        if not cited:
            item = dict(entry)
            item["score"] = f"{score:.3f}"
            bib_unreferenced.append(item)

    pdf_items = collect_pdf_items(ref_norms)
    pdf_unreferenced = [item for item in pdf_items if not item["cited"]]
    by_category = defaultdict(list)
    for item in pdf_unreferenced:
        by_category[str(item["category"])].append(item)

    high_pdf = [item for item in pdf_unreferenced if priority_label(str(item["title"]), str(item["category"])) == "High"]

    lines = []
    lines.append("# Unreferenced-paper audit for IJDRR manuscript")
    lines.append("")
    lines.append(f"- Manuscript checked: `{MANUSCRIPT}`")
    lines.append(f"- Current reference-list count: **{len(refs)}**")
    lines.append(f"- Zotero export entries checked: **{len(bib_entries)}**")
    lines.append(f"- Zotero entries not matched to current reference list: **{len(bib_unreferenced)}**")
    lines.append(f"- Unique local PDF titles checked: **{len(pdf_items)}**")
    lines.append(f"- Local PDF titles not matched to current reference list: **{len(pdf_unreferenced)}**")
    lines.append("")
    lines.append("## High-priority local PDFs to consider citing")
    lines.append("")
    if high_pdf:
        lines.append("| Local no. | Title | Folder | Why it matters |")
        lines.append("|---|---|---|---|")
        for item in high_pdf:
            lines.append(
                f"| {item['number'] or ''} | {item['title']} | `{item['category']}` | Closely related to blackout/social behaviour, infrastructure disruption, outdoor/city evacuation, or hazard-network spatial modelling. |"
            )
    else:
        lines.append("No high-priority unmatched local PDFs detected by keyword screen.")
    lines.append("")
    lines.append("## Zotero export entries not currently cited")
    lines.append("")
    lines.append("| Key | Year | Title | Journal |")
    lines.append("|---|---:|---|---|")
    for entry in bib_unreferenced:
        lines.append(
            f"| `{entry.get('key','')}` | {entry.get('year','')} | {entry.get('title','')} | {entry.get('journal','')} |"
        )
    lines.append("")
    lines.append("## Local PDF titles not currently cited")
    lines.append("")
    for category in sorted(by_category):
        lines.append(f"### {category}")
        lines.append("")
        lines.append("| Local no. | Priority | Title | Relative path |")
        lines.append("|---|---|---|---|")
        for item in by_category[category]:
            priority = priority_label(str(item["title"]), str(item["category"]))
            lines.append(
                f"| {item['number'] or ''} | {priority} | {item['title']} | `{item['relpath']}` |"
            )
        lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append(
        "The match is title-based and conservative: items are marked as cited only when their title closely matches the current References section. "
        "Chinese shorthand filenames and note PDFs may require manual confirmation before deletion or exclusion."
    )

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"references={len(refs)}")
    print(f"bib_entries={len(bib_entries)}")
    print(f"bib_unreferenced={len(bib_unreferenced)}")
    print(f"pdf_unique={len(pdf_items)}")
    print(f"pdf_unreferenced={len(pdf_unreferenced)}")
    print(f"report={REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
