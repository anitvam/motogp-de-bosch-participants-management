"""PDF version of the grids, produced by LibreOffice from the generated .xlsx."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

WINDOWS_PATHS = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]
MAC_PATH = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


def find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        if found := shutil.which(name):
            return found
    for path in [*WINDOWS_PATHS, MAC_PATH]:
        if Path(path).exists():
            return path
    return None


def xlsx_to_pdf(xlsx: bytes, timeout: int = 120) -> bytes:
    soffice = find_soffice()
    if soffice is None:
        raise RuntimeError("LibreOffice non trovato: installalo per generare il PDF")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "batterie.xlsx"
        src.write_bytes(xlsx)
        # A private profile lets the conversion run even when LibreOffice is already open.
        profile = (tmp_path / "profile").as_uri()
        subprocess.run(
            [soffice, f"-env:UserInstallation={profile}", "--headless",
             "--convert-to", "pdf", "--outdir", str(tmp_path), str(src)],
            check=True, capture_output=True, timeout=timeout,
        )
        return (tmp_path / "batterie.pdf").read_bytes()
