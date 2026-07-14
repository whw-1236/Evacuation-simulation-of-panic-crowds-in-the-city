"""Tests for the deterministic IJDRR manuscript/package submission gate."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_ijdrr_submission.py"
SPEC = importlib.util.spec_from_file_location("check_ijdrr_submission", SCRIPT)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


PASSING_MANUSCRIPT = r"""# A concise disaster-risk-reduction title

Authors: Alice Zhang; Bo Li
Affiliations: Department of Safety Science, Example University, China
Corresponding author: Alice Zhang; alice@example.edu; Full postal address

## Abstract

This study develops and tests a reproducible evacuation model. Paired simulations show
that the intervention changes route choice while uncertainty remains bounded. The
results support a demand-aware planning recommendation within the tested scenario.

## Keywords

Blackout; evacuation; simulation

## Highlights

- A reproducible model couples stress, choice and evacuation routing
- Paired simulations quantify route-choice changes across fixed seeds
- Demand-aware planning outperforms a topology-only screening proxy

# 1. Introduction

Prior work motivates the model [1,2]. The state is bounded by \(\sigma\in[0,1]\).

**Table 1.** Minimal example table.

| Variable | Value |
|---|---:|
| n | 10 |

![Fig. 1](figures/Figure_1.pdf)

*Fig. 1. A verified programmatic result figure.*

# 2. Methods

The complete procedure is reproducible.

# 3. Results

The paired comparison supports the bounded claim.

# 4. Discussion

The result is limited to the tested scenario.

# 5. Conclusion

Demand-aware screening is recommended for this scenario.

## Data availability

Data and code are deposited in a named repository with a persistent identifier.

## CRediT author statement

Alice Zhang: Conceptualization, Software, Writing. Bo Li: Supervision, Validation.

## Funding

This research did not receive any specific grant.

## Declaration of competing interests

The authors declare that they have no known competing interests.

## Declaration of generative AI and AI-assisted technologies in manuscript preparation

The authors used an AI-assisted tool for language and format checking, reviewed all
outputs, and take full responsibility for the content.

# References

[1] A. Author, First verified article, Journal 1 (2024) 1-10. https://doi.org/10.1000/one.

[2] B. Author, Second verified article, Journal 2 (2025) 11-20. https://doi.org/10.1000/two.
"""


def _write_passing_package(tmp_path: Path) -> Path:
    manuscript = tmp_path / "IJDRR_manuscript_v7.md"
    manuscript.write_text(PASSING_MANUSCRIPT, encoding="utf-8")
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "Figure_1.pdf").write_bytes(b"%PDF-test")
    (tmp_path / "IJDRR_manuscript_v7.docx").write_bytes(b"docx-placeholder")
    (tmp_path / "IJDRR_highlights_v7.docx").write_bytes(b"docx-placeholder")
    (tmp_path / "IJDRR_declaration_of_interests.docx").write_bytes(b"docx-placeholder")
    return manuscript


def test_passing_synthetic_package_has_no_gate_issues(tmp_path: Path):
    manuscript = _write_passing_package(tmp_path)

    report = gate.inspect_submission(manuscript, package_root=tmp_path, ai_used=True)

    assert report["status"] == "PASS"
    assert report["counts"] == {"info": 0, "minor": 0, "major": 0, "blocker": 0}
    assert report["metrics"]["reference_count"] == 2
    assert report["metrics"]["unique_citation_count"] == 2


def test_math_interval_is_not_parsed_as_a_citation():
    body = r"The state satisfies \(x\in[0,1]\), as established in [1,3-4]."

    citations, first_order = gate.extract_citations(body)

    assert citations == [1, 3, 4]
    assert first_order == [1, 3, 4]


def test_citation_parser_ignores_inline_code_fences_and_all_supported_math():
    body = r"""
Real evidence [1, 3–5].
`array[9]`
```python
fake = [10]
```
\(x\in[0,1]\) and \[y\in[20,21]\] and $z\in[30,31]$.
"""

    citations, first_order = gate.extract_citations(body)

    assert citations == [1, 3, 4, 5]
    assert first_order == [1, 3, 4, 5]


@pytest.mark.parametrize("word_count, should_fail", [(250, False), (251, True)])
def test_abstract_word_limit_is_inclusive(tmp_path: Path, word_count: int, should_fail: bool):
    manuscript = _write_passing_package(tmp_path)
    text = manuscript.read_text(encoding="utf-8")
    start = text.index("## Abstract") + len("## Abstract")
    end = text.index("## Keywords")
    text = text[:start] + "\n\n" + " ".join(["word"] * word_count) + "\n\n" + text[end:]
    manuscript.write_text(text, encoding="utf-8")

    report = gate.inspect_submission(manuscript, package_root=tmp_path, ai_used=True)
    issues = {issue["check_id"]: issue for issue in report["issues"]}

    assert ("abstract.word_limit" in issues) is should_fail
    if should_fail:
        assert issues["abstract.word_limit"]["evidence"] == {
            "words": 251,
            "limit": 250,
            "excess": 1,
        }


@pytest.mark.parametrize("characters, should_fail", [(85, False), (86, True)])
def test_highlight_character_limit_is_inclusive(tmp_path: Path, characters: int, should_fail: bool):
    manuscript = _write_passing_package(tmp_path)
    text = manuscript.read_text(encoding="utf-8")
    text = text.replace(
        "A reproducible model couples stress, choice and evacuation routing",
        "x" * characters,
    )
    manuscript.write_text(text, encoding="utf-8")

    report = gate.inspect_submission(manuscript, package_root=tmp_path, ai_used=True)
    issues = {issue["check_id"]: issue for issue in report["issues"]}

    assert ("highlights.item_length" in issues) is should_fail
    if should_fail:
        assert issues["highlights.item_length"]["evidence"][0]["characters"] == 86


def test_ai_disclosure_is_required_only_when_ai_used(tmp_path: Path):
    manuscript = _write_passing_package(tmp_path)
    text = manuscript.read_text(encoding="utf-8").replace(
        "## Declaration of generative AI and AI-assisted technologies in manuscript preparation",
        "## Tool-use note",
    )
    manuscript.write_text(text, encoding="utf-8")

    without_ai_requirement = gate.inspect_submission(manuscript, package_root=tmp_path, ai_used=False)
    with_ai_requirement = gate.inspect_submission(manuscript, package_root=tmp_path, ai_used=True)

    assert "statements.ai_disclosure" not in {
        issue["check_id"] for issue in without_ai_requirement["issues"]
    }
    assert "statements.ai_disclosure" in {issue["check_id"] for issue in with_ai_requirement["issues"]}


def test_package_artifact_checks_can_be_disabled_for_draft_only(tmp_path: Path):
    manuscript = tmp_path / "draft.md"
    manuscript.write_text(PASSING_MANUSCRIPT, encoding="utf-8")
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "Figure_1.pdf").write_bytes(b"%PDF-test")

    full = gate.inspect_submission(manuscript, package_root=tmp_path, ai_used=True)
    draft_only = gate.inspect_submission(
        manuscript,
        package_root=tmp_path,
        ai_used=True,
        require_package_artifacts=False,
    )
    full_ids = {issue["check_id"] for issue in full["issues"]}
    draft_ids = {issue["check_id"] for issue in draft_only["issues"]}

    assert "package.editable_manuscript" in full_ids
    assert "package.competing_interest_document" in full_ids
    assert "highlights.separate_file" in full_ids
    assert not any(check_id.startswith("package.") for check_id in draft_ids)
    assert "highlights.separate_file" not in draft_ids


def test_possible_generative_ai_artwork_is_blocked(tmp_path: Path):
    manuscript = _write_passing_package(tmp_path)
    (tmp_path / "figures" / "ChatGPT Image.png").write_bytes(b"not-a-submission-image")

    report = gate.inspect_submission(manuscript, package_root=tmp_path, ai_used=True)
    issue = next(
        issue for issue in report["issues"] if issue["check_id"] == "package.generative_ai_artwork_candidate"
    )

    assert issue["severity"] == "blocker"
    assert issue["evidence"] == ["ChatGPT Image.png"]


def test_gate_reports_length_order_link_and_declaration_failures(tmp_path: Path):
    manuscript = tmp_path / "bad.md"
    long_abstract = " ".join(["word"] * 251)
    manuscript.write_text(
        PASSING_MANUSCRIPT
        .replace(
            "This study develops and tests a reproducible evacuation model. Paired simulations show\n"
            "that the intervention changes route choice while uncertainty remains bounded. The\n"
            "results support a demand-aware planning recommendation within the tested scenario.",
            long_abstract,
        )
        .replace("Prior work motivates the model [1,2].", "Prior work motivates the model [2,1].")
        .replace("figures/Figure_1.pdf", "figures/missing.pdf")
        .replace("## Data availability", "## Removed data section")
        .replace("## CRediT author statement", "## Removed contribution section")
        .replace("## Funding", "## Removed support section")
        .replace("## Declaration of competing interests", "## Removed interests section"),
        encoding="utf-8",
    )

    report = gate.inspect_submission(
        manuscript,
        package_root=tmp_path,
        ai_used=True,
        require_package_artifacts=False,
    )
    ids = {issue["check_id"] for issue in report["issues"]}

    assert report["status"] == "FAIL"
    assert "abstract.word_limit" in ids
    assert "references.first_appearance_order" in ids
    assert "figures.missing_files" in ids
    assert "statements.data_availability" in ids
    assert "statements.credit" in ids
    assert "statements.funding" in ids
    assert "statements.competing_interests" in ids


def test_current_v6_known_defects_are_machine_detected():
    workspace = ROOT.parents[1]
    manuscript = (
        workspace
        / "论文初稿模块"
        / "main"
        / "7.9"
        / "event5fix_manuscript_v6_emotion_chain_2026-07-09"
        / "IJDRR_main_manuscript_v6_emotion_chain.md"
    )
    if not manuscript.is_file():
        pytest.skip("Workspace manuscript is not part of a standalone repository checkout")

    report = gate.inspect_submission(
        manuscript,
        package_root=manuscript.parent,
        ai_used=True,
        require_package_artifacts=True,
    )
    ids = {issue["check_id"] for issue in report["issues"]}

    assert report["metrics"]["abstract_words"] == 276
    assert report["metrics"]["keyword_count"] == 7
    assert report["metrics"]["highlight_characters"] == [89, 79, 90, 58, 69]
    assert report["metrics"]["reference_count"] == 48
    assert report["metrics"]["unique_citation_count"] == 48
    assert {
        "abstract.word_limit",
        "highlights.item_length",
        "tables.sequential_numbering",
        "figures.missing_files",
        "references.first_appearance_order",
        "metadata.author_names_missing",
        "statements.data_availability",
        "statements.credit",
        "statements.funding",
        "statements.competing_interests",
        "statements.ai_disclosure",
        "package.editable_manuscript",
        "package.competing_interest_document",
        "package.supplementary_editable_file",
    }.issubset(ids)
