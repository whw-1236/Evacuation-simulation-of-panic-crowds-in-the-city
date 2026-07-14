"""Machine-check an IJDRR Markdown manuscript and its submission package.

The checker deliberately covers deterministic, auditable requirements only.  It
does not claim to validate scientific correctness, statistical evidence, image
resolution, font embedding, or the truth of bibliographic metadata.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote


SEVERITY_RANK = {"info": 0, "minor": 1, "major": 2, "blocker": 3}
EDITABLE_SUFFIXES = {".doc", ".docx", ".tex"}
FIGURE_SUFFIXES = {".eps", ".pdf", ".tif", ".tiff", ".png", ".jpg", ".jpeg"}
PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD|PLACEHOLDER|FIXME|XXX)\b|\?\?+", re.IGNORECASE)
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")


@dataclass(frozen=True)
class Issue:
    check_id: str
    severity: str
    message: str
    evidence: object | None = None


def _section(text: str, start: str, end: str | None = None) -> str | None:
    start_match = re.search(rf"(?im)^##?\s+{re.escape(start)}\s*$", text)
    if not start_match:
        return None
    tail = text[start_match.end() :]
    if end:
        end_match = re.search(rf"(?im)^##?\s+{re.escape(end)}\s*$", tail)
    else:
        end_match = re.search(r"(?m)^#{1,4}\s+", tail)
    return tail[: end_match.start() if end_match else None].strip()


def _split_references(text: str) -> tuple[str, str]:
    match = re.search(r"(?im)^#\s+References\s*$", text)
    if not match:
        return text, ""
    return text[: match.start()], text[match.end() :]


def _strip_nonprose_for_citations(text: str) -> str:
    """Remove code and LaTeX math so numeric intervals are not citations."""

    stripped = re.sub(r"(?ms)^```.*?^```\s*", " ", text)
    stripped = re.sub(r"`[^`\n]*`", " ", stripped)
    stripped = re.sub(r"(?s)\$\$.*?\$\$", " ", stripped)
    stripped = re.sub(r"(?s)\\\[.*?\\\]", " ", stripped)
    stripped = re.sub(r"(?s)\\\(.*?\\\)", " ", stripped)
    stripped = re.sub(r"(?s)(?<!\$)\$(?!\$).*?(?<!\$)\$(?!\$)", " ", stripped)
    return stripped


def _expand_citation_token(token: str) -> list[int]:
    numbers: list[int] = []
    for part in token.replace("–", "-").replace("—", "-").split(","):
        part = part.strip()
        range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if range_match:
            lower, upper = (int(value) for value in range_match.groups())
            if 0 < lower <= upper and upper - lower <= 500:
                numbers.extend(range(lower, upper + 1))
        elif part.isdigit() and int(part) > 0:
            numbers.append(int(part))
    return numbers


def extract_citations(body: str) -> tuple[list[int], list[int]]:
    prose = _strip_nonprose_for_citations(body)
    all_citations: list[int] = []
    first_order: list[int] = []
    seen: set[int] = set()
    pattern = re.compile(r"\[(\d+(?:\s*(?:,|-|–|—)\s*\d+)*)\]")
    for match in pattern.finditer(prose):
        for number in _expand_citation_token(match.group(1)):
            all_citations.append(number)
            if number not in seen:
                seen.add(number)
                first_order.append(number)
    return all_citations, first_order


def extract_reference_numbers(references: str) -> list[int]:
    return [int(match.group(1)) for match in re.finditer(r"(?m)^\[(\d+)\]\s+", references)]


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _heading_present(text: str, patterns: Iterable[str]) -> bool:
    headings = "\n".join(re.findall(r"(?im)^#{1,4}\s+(.+?)\s*$", text))
    return any(re.search(pattern, headings, re.IGNORECASE) for pattern in patterns)


def _artifact_paths(package_root: Path) -> list[Path]:
    if not package_root.exists():
        return []
    return [path for path in package_root.rglob("*") if path.is_file()]


def _relative_figure_path(raw_target: str, manuscript: Path) -> Path | None:
    target = raw_target.strip().strip("<>")
    target = target.split("#", 1)[0]
    if re.match(r"^[a-z][a-z0-9+.-]*://", target, re.IGNORECASE):
        return None
    target = unquote(target)
    candidate = Path(target)
    return candidate if candidate.is_absolute() else manuscript.parent / candidate


def _add(issues: list[Issue], check_id: str, severity: str, message: str, evidence: object = None) -> None:
    issues.append(Issue(check_id, severity, message, evidence))


def inspect_submission(
    manuscript: Path,
    *,
    package_root: Path | None = None,
    ai_used: bool = False,
    require_package_artifacts: bool = True,
) -> dict[str, object]:
    manuscript = manuscript.resolve()
    package_root = (package_root or manuscript.parent).resolve()
    text = manuscript.read_text(encoding="utf-8")
    body, references = _split_references(text)
    issues: list[Issue] = []

    abstract = _section(text, "Abstract", "Keywords")
    keywords_block = _section(text, "Keywords", "Highlights")
    highlights_block = _section(text, "Highlights", "1. Introduction")
    abstract_words = len(WORD_RE.findall(abstract or ""))
    keywords = [item.strip() for item in re.split(r"[;\n]", keywords_block or "") if item.strip()]
    highlights = [
        match.group(1).strip()
        for match in re.finditer(r"(?m)^\s*[-*]\s+(.+?)\s*$", highlights_block or "")
    ]

    abstract_heading = re.search(r"(?im)^##?\s+Abstract\s*$", text)
    title_page = text[: abstract_heading.start()] if abstract_heading else ""
    if not re.search(r"(?im)^\s*(?:authors?|by)\s*[:：]", title_page):
        _add(issues, "metadata.author_names_missing", "blocker", "No explicit author-name field precedes the Abstract.")
    if not re.search(
        r"(?im)^\s*(?:affiliations?|department|school|college|university|institute)\b", title_page
    ):
        _add(issues, "metadata.affiliations_missing", "blocker", "No explicit affiliation field precedes the Abstract.")
    if not re.search(r"(?im)corresponding\s+author", title_page):
        _add(
            issues,
            "metadata.corresponding_author_missing",
            "blocker",
            "No corresponding-author field precedes the Abstract.",
        )

    if abstract is None:
        _add(issues, "abstract.missing", "blocker", "The manuscript has no Abstract section.")
    elif abstract_words > 250:
        _add(
            issues,
            "abstract.word_limit",
            "major",
            f"The Abstract has {abstract_words} words; IJDRR permits at most 250.",
            {"words": abstract_words, "limit": 250, "excess": abstract_words - 250},
        )

    if not 1 <= len(keywords) <= 7:
        _add(
            issues,
            "keywords.count",
            "major",
            f"Found {len(keywords)} keywords; IJDRR requires 1-7.",
            {"count": len(keywords), "keywords": keywords},
        )

    if not 3 <= len(highlights) <= 5:
        _add(
            issues,
            "highlights.count",
            "major",
            f"Found {len(highlights)} Highlights; IJDRR expects 3-5.",
        )
    long_highlights = [
        {"index": index, "characters": len(item), "text": item}
        for index, item in enumerate(highlights, start=1)
        if len(item) > 85
    ]
    if long_highlights:
        _add(
            issues,
            "highlights.item_length",
            "major",
            f"{len(long_highlights)} Highlight(s) exceed 85 characters including spaces.",
            long_highlights,
        )

    major_sections = [int(value) for value in re.findall(r"(?m)^#\s+(\d+)\.\s+", text)]
    expected_sections = list(range(1, len(major_sections) + 1))
    if not major_sections or major_sections != expected_sections:
        _add(
            issues,
            "sections.major_numbering",
            "major",
            "Major article sections are not consecutively numbered from 1.",
            {"found": major_sections, "expected": expected_sections},
        )

    table_labels = re.findall(r"(?im)^\*{1,2}Table\s+([A-Za-z]?\d+(?:\.\d+)?[a-z]?)", body)
    simple_tables = [int(label) for label in table_labels if label.isdigit()]
    if table_labels and (len(simple_tables) != len(table_labels) or simple_tables != list(range(1, len(table_labels) + 1))):
        _add(
            issues,
            "tables.sequential_numbering",
            "major",
            "Main-text table captions are not numbered as one consecutive sequence.",
            {"found": table_labels},
        )

    figure_caption_numbers = [
        int(value) for value in re.findall(r"(?im)^\*{1,2}Fig(?:ure)?\.?\s*(\d+)\.", body)
    ]
    if figure_caption_numbers and figure_caption_numbers != list(range(1, len(figure_caption_numbers) + 1)):
        _add(
            issues,
            "figures.sequential_numbering",
            "major",
            "Main-text figure captions are not numbered as one consecutive sequence.",
            {"found": figure_caption_numbers},
        )

    image_targets = [match.group(1) for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", body)]
    missing_figures: list[str] = []
    unsupported_figures: list[str] = []
    for raw_target in image_targets:
        figure_path = _relative_figure_path(raw_target, manuscript)
        if figure_path is None:
            unsupported_figures.append(raw_target)
        elif not figure_path.is_file():
            missing_figures.append(raw_target)
        elif figure_path.suffix.lower() not in FIGURE_SUFFIXES:
            unsupported_figures.append(raw_target)
    if missing_figures:
        _add(
            issues,
            "figures.missing_files",
            "blocker",
            f"{len(missing_figures)} linked figure file(s) do not exist relative to the manuscript.",
            missing_figures,
        )
    if unsupported_figures:
        _add(
            issues,
            "figures.unsupported_or_external",
            "major",
            "Some linked figures are external or use a non-submission format.",
            unsupported_figures,
        )
    if len(figure_caption_numbers) != len(image_targets):
        _add(
            issues,
            "figures.caption_count",
            "major",
            "The number of figure captions does not match the number of linked figures.",
            {"captions": len(figure_caption_numbers), "images": len(image_targets)},
        )

    cited, first_order = extract_citations(body)
    reference_numbers = extract_reference_numbers(references)
    if not reference_numbers:
        _add(issues, "references.missing", "blocker", "No numbered reference list was found.")
    else:
        expected_refs = list(range(1, max(reference_numbers) + 1))
        if reference_numbers != expected_refs:
            _add(
                issues,
                "references.list_contiguous",
                "major",
                "Reference-list numbers are not a contiguous sequence from 1.",
                {"found": reference_numbers, "expected": expected_refs},
            )
        missing_from_list = sorted(set(cited) - set(reference_numbers))
        uncited = sorted(set(reference_numbers) - set(cited))
        if missing_from_list or uncited:
            _add(
                issues,
                "references.set_mismatch",
                "blocker",
                "In-text citations and reference-list entries are not bidirectionally complete.",
                {"missing_from_list": missing_from_list, "uncited_references": uncited},
            )
        if first_order != reference_numbers:
            _add(
                issues,
                "references.first_appearance_order",
                "major",
                "References are not numbered in order of first appearance.",
                {"first_appearance": first_order, "reference_list": reference_numbers},
            )

    preprint_refs = [
        int(match.group(1))
        for match in re.finditer(r"(?im)^\[(\d+)\].*(?:arXiv|\bpreprint\b).*$", references)
    ]
    if preprint_refs:
        _add(
            issues,
            "references.preprint_version_check",
            "minor",
            "Preprint references require a current check for later peer-reviewed versions.",
            preprint_refs,
        )
    web_without_access_date = [
        int(match.group(1))
        for match in re.finditer(r"(?im)^\[(\d+)\](?P<entry>.*https?://.*)$", references)
        if "doi.org/" not in match.group("entry").lower()
        and "arxiv.org/" not in match.group("entry").lower()
        and "accessed" not in match.group("entry").lower()
    ]
    if web_without_access_date:
        _add(
            issues,
            "references.web_access_dates",
            "major",
            "Web references without DOI/arXiv links are missing an accessed date.",
            web_without_access_date,
        )

    declaration_checks = (
        ("statements.data_availability", (r"data availability", r"availability of data"), "blocker", "Data-availability statement"),
        ("statements.credit", (r"CRediT", r"author contributions?"), "blocker", "CRediT author-contribution statement"),
        ("statements.funding", (r"funding", r"financial support"), "blocker", "Funding statement"),
        ("statements.competing_interests", (r"competing interests?", r"declaration of interests?", r"conflict of interests?"), "blocker", "Competing-interest statement"),
    )
    for check_id, patterns, severity, label in declaration_checks:
        if not _heading_present(body, patterns):
            _add(issues, check_id, severity, f"No {label} heading was found before References.")
    if ai_used and not _heading_present(body, (r"generative AI", r"AI-assisted technologies")):
        _add(
            issues,
            "statements.ai_disclosure",
            "blocker",
            "AI use was declared to the checker, but the manuscript has no AI-use disclosure heading.",
        )

    placeholder_hits = [
        {"line": _line_number(text, match.start()), "token": match.group(0)} for match in PLACEHOLDER_RE.finditer(text)
    ]
    if placeholder_hits:
        _add(issues, "manuscript.placeholders", "major", "Unresolved placeholder markers remain.", placeholder_hits)

    artifacts = _artifact_paths(package_root)
    artifact_names = [path.name for path in artifacts]
    if require_package_artifacts:
        editable_manuscripts = [
            path
            for path in artifacts
            if path.suffix.lower() in EDITABLE_SUFFIXES
            and re.search(r"manuscript|article|paper", path.stem, re.IGNORECASE)
        ]
        if not editable_manuscripts:
            _add(
                issues,
                "package.editable_manuscript",
                "blocker",
                "No editable `.doc/.docx/.tex` manuscript source was found in the package.",
            )
        separate_highlights = [
            path
            for path in artifacts
            if path.suffix.lower() in EDITABLE_SUFFIXES and "highlight" in path.stem.lower()
        ]
        if not separate_highlights:
            _add(
                issues,
                "highlights.separate_file",
                "major",
                "No separate editable Highlights file was found in the package.",
            )
        declaration_documents = [
            path
            for path in artifacts
            if path.suffix.lower() in {".doc", ".docx"}
            and re.search(r"declaration|competing|conflict", path.stem, re.IGNORECASE)
        ]
        if not declaration_documents:
            _add(
                issues,
                "package.competing_interest_document",
                "blocker",
                "No separate Word competing-interest declaration was found in the package.",
            )
        if re.search(r"\bSupplementary\b", body, re.IGNORECASE):
            supplement_files = [
                path
                for path in artifacts
                if path.suffix.lower() in EDITABLE_SUFFIXES
                and re.search(r"supplement", path.stem, re.IGNORECASE)
            ]
            if not supplement_files:
                _add(
                    issues,
                    "package.supplementary_editable_file",
                    "blocker",
                    "The manuscript cites supplementary material, but no separate editable supplement was found.",
                )
        generated_ai_candidates = [
            path.name
            for path in artifacts
            if re.search(r"chatgpt|dall[-_ ]?e|midjourney|imagegen", path.name, re.IGNORECASE)
            and path.suffix.lower() in FIGURE_SUFFIXES
        ]
        if generated_ai_candidates:
            _add(
                issues,
                "package.generative_ai_artwork_candidate",
                "blocker",
                "Possible generative-AI artwork is present in the package and requires removal/manual investigation.",
                generated_ai_candidates,
            )

    counts = {severity: sum(issue.severity == severity for issue in issues) for severity in SEVERITY_RANK}
    return {
        "schema_version": 1,
        "manuscript": str(manuscript),
        "package_root": str(package_root),
        "status": "PASS" if not any(issue.severity in {"blocker", "major"} for issue in issues) else "FAIL",
        "metrics": {
            "abstract_words": abstract_words,
            "keyword_count": len(keywords),
            "highlight_count": len(highlights),
            "highlight_characters": [len(item) for item in highlights],
            "major_sections": major_sections,
            "table_labels": table_labels,
            "figure_caption_numbers": figure_caption_numbers,
            "image_link_count": len(image_targets),
            "reference_count": len(reference_numbers),
            "unique_citation_count": len(set(cited)),
            "artifact_count": len(artifacts),
            "artifact_names": sorted(artifact_names),
        },
        "counts": counts,
        "issues": [asdict(issue) for issue in issues],
        "limitations": [
            "Scientific correctness and code-output-manuscript agreement are not checked.",
            "Bibliographic metadata and DOI authenticity are not verified online.",
            "Figure DPI, font embedding, final-size readability, and statistical validity require separate QA.",
            "Title-page detection expects explicit Markdown labels and must be rechecked in the final DOCX.",
        ],
    }


def _print_human(report: dict[str, object]) -> None:
    counts = report["counts"]
    print(f"IJDRR submission gate: {report['status']}")
    print(
        "blocker={blocker} major={major} minor={minor} info={info}".format(**counts)
    )
    for issue in report["issues"]:
        print(f"[{issue['severity'].upper()}] {issue['check_id']}: {issue['message']}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manuscript", type=Path, help="Markdown manuscript to inspect")
    parser.add_argument("--package-root", type=Path, help="Root of the submission package")
    parser.add_argument(
        "--ai-used",
        action="store_true",
        help="Require a generative-AI/AI-assisted manuscript-preparation disclosure",
    )
    parser.add_argument(
        "--draft-only",
        action="store_true",
        help="Skip separate submission-artifact checks and inspect manuscript content only",
    )
    parser.add_argument("--json-output", type=Path, help="Optional path for the machine-readable report")
    parser.add_argument(
        "--fail-on",
        choices=("blocker", "major", "minor", "never"),
        default="major",
        help="Smallest severity that produces exit code 1 (default: major)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        report = inspect_submission(
            args.manuscript,
            package_root=args.package_root,
            ai_used=args.ai_used,
            require_package_artifacts=not args.draft_only,
        )
    except (OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    _print_human(report)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.fail_on == "never":
        return 0
    threshold = SEVERITY_RANK[args.fail_on]
    return int(any(SEVERITY_RANK[issue["severity"]] >= threshold for issue in report["issues"]))


if __name__ == "__main__":
    raise SystemExit(main())
