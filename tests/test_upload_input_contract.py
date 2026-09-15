"""Input-picker contracts for CT / mask uploads.

Chromium matches only the final extension of a file against ``accept``
tokens, so ``.nii.gz`` never matches and the entry silently hides the very
files this product stores. Extensionless DICOM files are hidden the same
way. The CT picker therefore must not filter by extension, must offer a
real folder picker, and the server must honor an explicit DICOM-series
folder upload even when it contains a single file.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _tag(html: str, element_id: str) -> str:
    match = re.search(
        rf"<input\b[^>]*id=\"{re.escape(element_id)}\"[^>]*>", html
    )
    assert match, f"input#{element_id} not found"
    return match.group(0)


def test_ct_picker_accepts_nii_gz_and_extensionless_dicom():
    index = read("web/app/index.html")

    ct = _tag(index, "fileCT")
    assert "accept=" not in ct, (
        "the CT picker must not filter by extension: Chromium cannot match "
        ".nii.gz and hides extensionless DICOM"
    )
    assert "multiple" in ct

    folder = _tag(index, "fileCTFolder")
    assert "webkitdirectory" in folder
    assert "multiple" in folder

    # Mask pickers keep a filter but must not use the multi-dot token that
    # Chromium silently drops.
    for element_id in ("fileCTV", "fileOAR"):
        tag = _tag(index, element_id)
        assert ".nii.gz" not in tag
        assert ".gz" in tag


def test_folder_uploads_declare_a_dicom_series_and_the_server_honors_it():
    ui_api = read("web/app/static/js/brachybot-ui-api.js")
    server = read("web/server.py")

    assert "input.hasAttribute('webkitdirectory')" in ui_api
    assert "formData.append('dicom_series', '1')" in ui_api
    assert "f.webkitRelativePath || f.name" in ui_api
    assert 'request.form.get("dicom_series")' in server
    assert "len(files) == 1 and not force_series" in server
