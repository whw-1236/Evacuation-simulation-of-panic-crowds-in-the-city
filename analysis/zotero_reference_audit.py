# -*- coding: utf-8 -*-
"""Audit manuscript citation placeholders against a local Zotero library.

The script is read-only with respect to Zotero. It reads the local SQLite
database using immutable mode, scans manuscript Markdown files for ``[REF...]``
tokens, and writes candidate matches for manual confirmation.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = Path(
    r"C:\Users\Administrator\AppData\Roaming\Zotero\Zotero\Profiles\tzbbenrc.default"
)
DEFAULT_MANUSCRIPT_DIR = Path(r"F:\IJDRR write\论文初稿模块")
DEFAULT_OUT_DIR = ROOT / "trace_output" / "reference_audit"

REF_RE = re.compile(r"\[REF(?::[^\]]+)?\]|\bREF[0-9A-Za-z_-]+\b")

EXCLUDE_DIRS = {".venv", "论文修改建议"}
EXCLUDE_ITEM_TYPES = {"attachment", "annotation", "note"}

QUERY_HINTS = {
    "Helbing & Molnár": ["social force model", "helbing", "molnar"],
    "Helbing, Farkas & Vicsek": ["simulating dynamical features of escape panic", "escape panic"],
    "Moussaïd": ["moussaid", "behavioural mechanisms", "self-organization", "human crowds"],
    "Durupinar": ["durupinar", "ascribe", "ocean", "personality", "emotion contagion"],
    "Ren et al": ["modified social force model considering emotional contagion", "ren"],
    "Cao et al": ["emotion contagion", "crowd evacuation", "p-sis"],
    "Wang et al": ["emotion contagion", "panic", "crowd evacuation", "wang"],
    "Yuen": ["panic buying", "yuen", "scarcity"],
    "Billore": ["panic buying", "billore", "anisimova"],
    "Rubin & Rogers": ["power outage", "blackout", "rubin", "rogers"],
    "Manhattan": ["manhattan", "blackout", "resilience"],
    "infrastructure-resilience": ["infrastructure", "resilience", "disruption"],
    "Freeman": ["freeman", "betweenness", "centrality"],
    "Crucitti": ["crucitti", "jenelius", "centrality", "vulnerability"],
    "Greenshields": ["greenshields", "speed", "density"],
    "panic-speed": ["panic", "speed", "faster is slower"],
    "Boeing": ["boeing", "osmnx", "openstreetmap"],
    "Lazarus": ["lazarus", "folkman", "stress", "appraisal"],
    "Lindell": ["lindell", "perry", "protective action decision"],
    "Cova": ["cova", "johnson", "traffic-shed", "evacuation"],
    "provincial DRM": ["wenchuan", "henan", "evacuation", "survey"],
}


def read_zotero_data_dir(profile: Path) -> Path:
    prefs = profile / "prefs.js"
    if not prefs.exists():
        raise FileNotFoundError(f"Zotero prefs.js not found: {prefs}")
    text = prefs.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r'user_pref\("extensions\.zotero\.dataDir",\s*"([^"]+)"\);', text)
    if not match:
        return Path.home() / "Zotero"
    return Path(match.group(1).encode("utf-8").decode("unicode_escape"))


def sqlite_connect_immutable(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"Zotero SQLite database not found: {db_path}")
    uri = "file:" + str(db_path).replace("\\", "/") + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_items(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT i.itemID, i.key, it.typeName,
               MAX(CASE WHEN f.fieldName='title' THEN v.value END) AS title,
               MAX(CASE WHEN f.fieldName='date' THEN v.value END) AS date,
               MAX(CASE WHEN f.fieldName='DOI' THEN v.value END) AS doi,
               MAX(CASE WHEN f.fieldName='publicationTitle' THEN v.value END) AS publicationTitle,
               MAX(CASE WHEN f.fieldName='url' THEN v.value END) AS url
        FROM items i
        JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
        LEFT JOIN itemData id ON i.itemID = id.itemID
        LEFT JOIN fields f ON id.fieldID = f.fieldID
        LEFT JOIN itemDataValues v ON id.valueID = v.valueID
        GROUP BY i.itemID, i.key, it.typeName
        HAVING title IS NOT NULL
        ORDER BY lower(title)
        """
    ).fetchall()

    creators_by_item: dict[int, list[str]] = defaultdict(list)
    for row in conn.execute(
        """
        SELECT ic.itemID, c.firstName, c.lastName
        FROM itemCreators ic
        JOIN creators c ON ic.creatorID = c.creatorID
        ORDER BY ic.itemID, ic.orderIndex
        """
    ):
        name = " ".join(x for x in (row["firstName"], row["lastName"]) if x).strip()
        if name:
            creators_by_item[int(row["itemID"])].append(name)

    items: list[dict] = []
    for row in rows:
        item = dict(row)
        if item["typeName"] in EXCLUDE_ITEM_TYPES:
            continue
        item["creators"] = "; ".join(creators_by_item.get(int(item["itemID"]), []))
        item["year"] = extract_year(item.get("date") or "")
        item["search_blob"] = normalize(
            " ".join(
                str(item.get(k) or "")
                for k in ("title", "creators", "date", "doi", "publicationTitle", "url")
            )
        )
        items.append(item)
    return items


def extract_year(text: str) -> str:
    match = re.search(r"(19|20)\d{2}", text or "")
    return match.group(0) if match else ""


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("ï", "i").replace("ï", "i").replace("ı", "i")
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def scan_placeholders(manuscript_dir: Path) -> list[dict]:
    occurrences: list[dict] = []
    for path in sorted(manuscript_dir.rglob("*.md")):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        rel = path.relative_to(manuscript_dir)
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in REF_RE.finditer(line):
                context = re.sub(r"\s+", " ", line.strip())
                occurrences.append(
                    {
                        "file": str(rel),
                        "line": lineno,
                        "token": match.group(0),
                        "context": context[:260],
                    }
                )
    return occurrences


def query_terms_for_token(token: str) -> list[str]:
    token_norm = normalize(token)
    terms: list[str] = []
    for key, hints in QUERY_HINTS.items():
        if normalize(key).split()[0] in token_norm or any(normalize(h) in token_norm for h in hints):
            terms.extend(hints)
    if not terms:
        cleaned = token.replace("[REF:", "").replace("[REF]", "").replace("]", "")
        terms = [part.strip() for part in re.split(r"[;,/]", cleaned) if part.strip()]
    return [normalize(t) for t in terms if normalize(t)]


def score_item(token: str, item: dict) -> tuple[float, str]:
    terms = query_terms_for_token(token)
    blob = item["search_blob"]
    title = normalize(item.get("title") or "")
    creators = normalize(item.get("creators") or "")
    score = 0.0
    reasons: list[str] = []

    for term in terms:
        if not term:
            continue
        if term in title:
            score += 4.0
            reasons.append(f"title:{term}")
        elif term in blob:
            score += 2.0
            reasons.append(f"metadata:{term}")
        else:
            ratio = max(SequenceMatcher(None, term, title).ratio(), SequenceMatcher(None, term, creators).ratio())
            if ratio >= 0.72:
                score += ratio
                reasons.append(f"fuzzy:{term}:{ratio:.2f}")

    year = extract_year(token)
    if year and item.get("year") == year:
        score += 1.5
        reasons.append(f"year:{year}")

    return score, "; ".join(reasons)


def build_matches(occurrences: list[dict], items: list[dict], top_n: int) -> list[dict]:
    unique_tokens = sorted(Counter(o["token"] for o in occurrences))
    rows: list[dict] = []
    for token in unique_tokens:
        scored = []
        for item in items:
            score, reason = score_item(token, item)
            if score > 0:
                scored.append((score, reason, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        for rank, (score, reason, item) in enumerate(scored[:top_n], start=1):
            rows.append(
                {
                    "token": token,
                    "rank": rank,
                    "score": round(score, 3),
                    "reason": reason,
                    "zotero_key": item["key"],
                    "item_type": item["typeName"],
                    "title": item.get("title") or "",
                    "creators": item.get("creators") or "",
                    "year": item.get("year") or "",
                    "doi": item.get("doi") or "",
                    "publication": item.get("publicationTitle") or "",
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, occurrences: list[dict], match_rows: list[dict], db_path: Path) -> None:
    token_counts = Counter(o["token"] for o in occurrences)
    by_token: dict[str, list[dict]] = defaultdict(list)
    for row in match_rows:
        by_token[row["token"]].append(row)

    lines = [
        "# Zotero Reference Placeholder Audit",
        "",
        f"- Zotero database: `{db_path}`",
        f"- Placeholder occurrences: {len(occurrences)}",
        f"- Unique placeholder tokens: {len(token_counts)}",
        "",
        "## Candidate Matches",
        "",
        "| Token | Count | Rank | Score | Candidate | Year | DOI | Zotero key | Reason |",
        "|---|---:|---:|---:|---|---:|---|---|---|",
    ]
    for token in sorted(token_counts):
        rows = by_token.get(token, [])
        if not rows:
            lines.append(f"| `{token}` | {token_counts[token]} | - | 0 | **NO MATCH** |  |  |  | Check manually |")
            continue
        for row in rows:
            title = (row["title"] or "").replace("|", "\\|")
            doi = row["doi"] or ""
            reason = row["reason"].replace("|", "\\|")
            lines.append(
                f"| `{token}` | {token_counts[token]} | {row['rank']} | {row['score']} | "
                f"{title} | {row['year']} | {doi} | `{row['zotero_key']}` | {reason} |"
            )

    lines.extend(
        [
            "",
            "## Occurrences",
            "",
            "| File | Line | Token | Context |",
            "|---|---:|---|---|",
        ]
    )
    for occ in occurrences:
        context = occ["context"].replace("|", "\\|")
        lines.append(f"| `{occ['file']}` | {occ['line']} | `{occ['token']}` | {context} |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zotero-profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--manuscript-dir", default=str(DEFAULT_MANUSCRIPT_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--top-n", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    profile = Path(args.zotero_profile)
    manuscript_dir = Path(args.manuscript_dir)
    out_dir = Path(args.out_dir)

    data_dir = read_zotero_data_dir(profile)
    db_path = data_dir / "zotero.sqlite"
    conn = sqlite_connect_immutable(db_path)
    items = fetch_items(conn)
    occurrences = scan_placeholders(manuscript_dir)
    matches = build_matches(occurrences, items, args.top_n)

    item_fields = [
        "itemID",
        "key",
        "typeName",
        "title",
        "creators",
        "year",
        "date",
        "doi",
        "publicationTitle",
        "url",
    ]
    write_csv(out_dir / "zotero_items.csv", items, item_fields)
    match_fields = [
        "token",
        "rank",
        "score",
        "reason",
        "zotero_key",
        "item_type",
        "title",
        "creators",
        "year",
        "doi",
        "publication",
    ]
    write_csv(out_dir / "placeholder_matches.csv", matches, match_fields)
    write_csv(out_dir / "placeholder_occurrences.csv", occurrences, ["file", "line", "token", "context"])
    write_markdown(out_dir / "placeholder_matches.md", occurrences, matches, db_path)

    print(
        json.dumps(
            {
                "zotero_db": str(db_path),
                "items": len(items),
                "placeholder_occurrences": len(occurrences),
                "unique_tokens": len(set(o["token"] for o in occurrences)),
                "out_dir": str(out_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
