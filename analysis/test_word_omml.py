from pathlib import Path
from zipfile import ZipFile

import win32com.client as win32


out = Path(r"F:\tmp\omml_test.docx")
word = win32.Dispatch("Word.Application")
word.Visible = False
doc = word.Documents.Add()
try:
    rng = doc.Range(0, 0)
    rng.Text = r"\sigma_i(t)\in[0,1]"
    doc.OMaths.Add(rng)
    doc.OMaths(1).BuildUp()
    doc.SaveAs2(str(out), FileFormat=16)
finally:
    doc.Close(False)
    word.Quit()

with ZipFile(out) as zf:
    xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
print("has_oMath=", "<m:oMath" in xml)
print("path=", out)
