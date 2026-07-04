from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from zipfile import ZipFile

import pywintypes
import win32com.client as win32


PAPER_DIR = Path(r"F:\IJDRR write\论文初稿模块")
TARGETS = [
    PAPER_DIR / "IJDRR_main_manuscript_v2_refs_resolved.md",
    PAPER_DIR / "IJDRR_full_paper_v2_refs_resolved.md",
]

WD_FORMAT_DOCX = 16
WD_ALIGN_LEFT = 0
WD_ALIGN_CENTER = 1
WD_COLLAPSE_END = 0
WD_STORY = 6
WD_AUTOFIT_WINDOW = 2
WD_STYLE_NORMAL = -1
WD_STYLE_HEADING = {1: -2, 2: -3, 3: -4}


INLINE_MATH_RE = re.compile(r"\\\((.+?)\\\)")
IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<path>[^)]+)\)")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


def com_retry(func, attempts: int = 30, delay: float = 0.15):
    last_exc = None
    for _ in range(attempts):
        try:
            return func()
        except pywintypes.com_error as exc:
            last_exc = exc
            time.sleep(delay)
    raise last_exc


def clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text


def strip_caption_marks(text: str) -> tuple[str, bool]:
    stripped = text.strip()
    if len(stripped) >= 2 and stripped.startswith("*") and stripped.endswith("*"):
        return clean_text(stripped[1:-1]), True
    return clean_text(text), False


def split_table_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [clean_text(cell.strip()) for cell in line.split("|")]


def resolve_image(md_path: Path, raw_path: str) -> Path:
    raw_path = raw_path.replace("/", "\\")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return (md_path.parent / candidate).resolve()


def prepare_math(math: str) -> tuple[str, str | None]:
    math = math.strip()
    tag = None
    match = re.search(r"\\tag\{([^}]+)\}", math)
    if match:
        tag = match.group(1)
        math = math[: match.start()] + math[match.end() :]
    math = re.sub(r"\\begin\{aligned\}", "", math)
    math = re.sub(r"\\end\{aligned\}", "", math)
    math = re.sub(r"\\begin\{align\*?\}", "", math)
    math = re.sub(r"\\end\{align\*?\}", "", math)
    math = re.sub(r"\\begin\{cases\}", r"\\cases{", math)
    math = re.sub(r"\\end\{cases\}", "}", math)
    return math.strip(), tag


class WordWriter:
    def __init__(self, word, out_path: Path):
        self.word = word
        word.Documents.Add()
        self.doc = word.ActiveDocument
        self.sel = word.Selection
        self.out_path = out_path
        self.math_inserted = 0
        self.math_buildup_failed = 0
        self.image_inserted = 0
        self.tables_inserted = 0
        self._setup_doc()

    def _setup_doc(self) -> None:
        self.word.Visible = False
        try:
            self.doc.PageSetup.TopMargin = 72
            self.doc.PageSetup.BottomMargin = 72
            self.doc.PageSetup.LeftMargin = 72
            self.doc.PageSetup.RightMargin = 72
        except Exception:
            pass
        try:
            normal = self.word.ActiveDocument.Styles(WD_STYLE_NORMAL)
            normal.Font.Name = "Times New Roman"
            normal.Font.Size = 11
            normal.ParagraphFormat.SpaceAfter = 6
            normal.ParagraphFormat.LineSpacing = 14
        except Exception:
            pass

    def close(self, save: bool = True) -> None:
        if save:
            self.out_path.parent.mkdir(parents=True, exist_ok=True)
            com_retry(lambda: self.word.ActiveDocument.SaveAs2(str(self.out_path), FileFormat=WD_FORMAT_DOCX))
        com_retry(lambda: self.word.ActiveDocument.Close(False))

    def goto_end(self) -> None:
        self.sel.EndKey(Unit=WD_STORY)

    def set_normal(self) -> None:
        self.sel.Style = WD_STYLE_NORMAL
        self.sel.Font.Name = "Times New Roman"
        self.sel.Font.Size = 11
        self.sel.Font.Bold = False
        self.sel.Font.Italic = False
        self.sel.ParagraphFormat.Alignment = WD_ALIGN_LEFT

    def add_heading(self, level: int, text: str) -> None:
        self.goto_end()
        level = min(max(level, 1), 3)
        self.sel.Style = WD_STYLE_HEADING[level]
        self.sel.Font.Name = "Times New Roman"
        self.sel.TypeText(clean_text(text))
        self.sel.TypeParagraph()
        self.set_normal()

    def add_text_paragraph(self, text: str, *, italic: bool = False, code: bool = False) -> None:
        self.goto_end()
        self.set_normal()
        if code:
            self.sel.Font.Name = "Consolas"
            self.sel.Font.Size = 9
        self.sel.Font.Italic = bool(italic)
        chunks = self._inline_chunks(text)
        for kind, value in chunks:
            if kind == "text":
                self.sel.TypeText(clean_text(value))
            else:
                self._insert_math(value, display=False)
        self.sel.TypeParagraph()
        self.set_normal()

    def add_display_math(self, math: str) -> None:
        self.goto_end()
        self.set_normal()
        self.sel.ParagraphFormat.Alignment = WD_ALIGN_CENTER
        math, tag = prepare_math(math)
        self._insert_math(math, display=True)
        if tag:
            self.sel.TypeText(f"    ({tag})")
        self.sel.TypeParagraph()
        self.set_normal()

    def add_image(self, md_path: Path, alt: str, raw_path: str) -> None:
        image_path = resolve_image(md_path, raw_path)
        self.goto_end()
        self.set_normal()
        self.sel.ParagraphFormat.Alignment = WD_ALIGN_CENTER
        if image_path.exists():
            shape = com_retry(lambda: self.sel.InlineShapes.AddPicture(
                FileName=str(image_path),
                LinkToFile=False,
                SaveWithDocument=True,
            ))
            try:
                shape.LockAspectRatio = True
                if shape.Width > 450:
                    shape.Width = 450
            except Exception:
                pass
            self.image_inserted += 1
        else:
            self.sel.TypeText(f"[Missing image: {raw_path}]")
        self.sel.TypeParagraph()
        self.set_normal()

    def add_table(self, rows: list[list[str]]) -> None:
        if not rows:
            return
        cols = max(len(row) for row in rows)
        rows = [row + [""] * (cols - len(row)) for row in rows]
        self.goto_end()
        self.set_normal()
        table = com_retry(lambda: self.doc.Tables.Add(self.sel.Range, len(rows), cols))
        table.Style = "Table Grid"
        table.AllowAutoFit = True
        table.AutoFitBehavior(WD_AUTOFIT_WINDOW)
        for r_idx, row in enumerate(rows, start=1):
            for c_idx, cell in enumerate(row, start=1):
                table.Cell(r_idx, c_idx).Range.Text = cell
                table.Cell(r_idx, c_idx).Range.Font.Name = "Times New Roman"
                table.Cell(r_idx, c_idx).Range.Font.Size = 9
                if r_idx == 1:
                    table.Cell(r_idx, c_idx).Range.Font.Bold = True
        self.tables_inserted += 1
        rng = table.Range
        rng.Collapse(WD_COLLAPSE_END)
        rng.Select()
        self.sel.TypeParagraph()
        self.set_normal()

    def _inline_chunks(self, text: str) -> list[tuple[str, str]]:
        chunks: list[tuple[str, str]] = []
        last = 0
        for match in INLINE_MATH_RE.finditer(text):
            if match.start() > last:
                chunks.append(("text", text[last : match.start()]))
            chunks.append(("math", match.group(1)))
            last = match.end()
        if last < len(text):
            chunks.append(("text", text[last:]))
        return chunks

    def _insert_math(self, math: str, *, display: bool) -> None:
        math, _ = prepare_math(math)
        if not math:
            return
        start = self.sel.Range.Start
        self.sel.TypeText(math)
        end = self.sel.Range.End
        time.sleep(0.03)
        rng = com_retry(lambda: self.doc.Range(start, end))
        try:
            com_retry(lambda: self.doc.OMaths.Add(rng))
            self.math_inserted += 1
            try:
                com_retry(lambda: self.doc.OMaths(self.doc.OMaths.Count).BuildUp())
            except Exception:
                self.math_buildup_failed += 1
        except Exception:
            self.math_buildup_failed += 1
        self.sel.SetRange(self.doc.Content.End - 1, self.doc.Content.End - 1)


def parse_markdown(md_path: Path, writer: WordWriter) -> None:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        if stripped.startswith("```"):
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            for code_line in code_lines:
                writer.add_text_paragraph(code_line, code=True)
            i += 1
            continue

        if stripped == "$$" or stripped.startswith("$$"):
            math_lines: list[str] = []
            if stripped != "$$":
                initial = stripped[2:]
                if initial.endswith("$$"):
                    writer.add_display_math(initial[:-2])
                    i += 1
                    continue
                math_lines.append(initial)
            i += 1
            while i < len(lines) and lines[i].strip() != "$$":
                math_lines.append(lines[i])
                i += 1
            writer.add_display_math("\n".join(math_lines))
            i += 1
            continue

        image_match = IMAGE_RE.match(stripped)
        if image_match:
            writer.add_image(md_path, image_match.group("alt"), image_match.group("path"))
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < len(lines) and TABLE_SEPARATOR_RE.match(lines[i + 1]):
            table_rows = [split_table_row(stripped)]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_rows.append(split_table_row(lines[i]))
                i += 1
            writer.add_table(table_rows)
            continue

        if stripped.startswith("#"):
            match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
            if match:
                writer.add_heading(len(match.group(1)), match.group(2))
                i += 1
                continue

        para_lines = [line.strip()]
        i += 1
        while i < len(lines):
            nxt = lines[i]
            nxt_stripped = nxt.strip()
            if not nxt_stripped:
                break
            if (
                nxt_stripped.startswith("#")
                or nxt_stripped.startswith("```")
                or nxt_stripped == "$$"
                or nxt_stripped.startswith("$$")
                or IMAGE_RE.match(nxt_stripped)
                or (nxt_stripped.startswith("|") and i + 1 < len(lines) and TABLE_SEPARATOR_RE.match(lines[i + 1]))
            ):
                break
            para_lines.append(nxt_stripped)
            i += 1
        paragraph = " ".join(para_lines)
        paragraph, italic = strip_caption_marks(paragraph)
        writer.add_text_paragraph(paragraph, italic=italic)


def inspect_docx(path: Path) -> dict[str, int | bool]:
    with ZipFile(path) as zf:
        names = zf.namelist()
        xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    return {
        "exists": path.exists(),
        "omath": xml.count("<m:oMath"),
        "paragraphs": xml.count("<w:p"),
        "tables": xml.count("<w:tbl"),
        "images": sum(1 for name in names if name.startswith("word/media/")),
    }


def convert_one(word, md_path: Path) -> tuple[Path, dict[str, int | bool], int]:
    out_path = md_path.with_name(md_path.stem + "_OMML.docx")
    writer = WordWriter(word, out_path)
    try:
        parse_markdown(md_path, writer)
        failed = writer.math_buildup_failed
        writer.close(save=True)
    except Exception:
        writer.close(save=False)
        raise
    return out_path, inspect_docx(out_path), failed


def main() -> int:
    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    results = []
    try:
        for md_path in TARGETS:
            out_path, stats, failed = convert_one(word, md_path)
            results.append((out_path, stats, failed))
    finally:
        word.Quit()

    for out_path, stats, failed in results:
        print(
            f"{out_path.name}: omath={stats['omath']}, images={stats['images']}, "
            f"tables={stats['tables']}, paragraphs={stats['paragraphs']}, buildup_failed={failed}"
        )
        print(f"  {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
