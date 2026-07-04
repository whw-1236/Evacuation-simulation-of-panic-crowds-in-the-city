"""Inspect generated DOCX files for manuscript review QA."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


RESIDUAL_MARKERS = (
    r"\tag",
    r"\varepsilon",
    r"\frac",
    r"\psi",
    r"\sigma",
    r"\mathbf",
    "[REF",
    "@@CIT",
)


def inspect_docx(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
    return {
        "file": path.name,
        "size": path.stat().st_size,
        "paragraphs": document_xml.count("<w:p"),
        "tables": document_xml.count("<w:tbl"),
        "images": len(media),
        "oMath": document_xml.count("<m:oMath"),
        "sSub": document_xml.count("<m:sSub"),
        "sSup": document_xml.count("<m:sSup"),
        "frac": document_xml.count("<m:f"),
        "residual": [marker for marker in RESIDUAL_MARKERS if marker in document_xml],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.docx:
        info = inspect_docx(path)
        print(
            "{file} size={size} paragraphs={paragraphs} tables={tables} "
            "images={images} oMath={oMath} sSub={sSub} sSup={sSup} "
            "frac={frac} residual={residual}".format(**info)
        )


if __name__ == "__main__":
    main()
