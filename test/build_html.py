"""Verify template loading and embedded synthetic data without login dependencies."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fetch_schedule", root / "fetch_schedule.py")
app = importlib.util.module_from_spec(spec)
with patch.dict("sys.modules", {
    "requests": SimpleNamespace(),
    "Crypto": SimpleNamespace(),
    "Crypto.Cipher": SimpleNamespace(AES=None),
    "Crypto.Util": SimpleNamespace(),
    "Crypto.Util.Padding": SimpleNamespace(pad=None),
}):
    spec.loader.exec_module(app)

sample = json.loads((root / "docs/schedule-demo.json").read_text(encoding="utf-8"))
raw = {
    "username": "PRIVATE_ID_SENTINEL", "student": {"XM": sample["student"]["name"], "private": "PRIVATE_FIELD_SENTINEL"},
    "term": sample["term"],
    "week_info": {"current": sample["defaultWeek"], "auto": sample["autoWeek"], "weeks": sample["weeks"]},
    "periods": sample["periods"], "weekday_order": sample["weekdayOrder"], "schedule": sample["schedule"],
}
html = app.build_html(raw)
assert "__DATA__" not in html
assert "PRIVATE_" not in html
embedded = json.loads(html.split("const DATA = ", 1)[1].split(";\n", 1)[0])
assert embedded["student"] == sample["student"]
assert embedded["periods"] == sample["periods"]
assert embedded["weeks"] == sample["weeks"]
assert embedded["term"] == sample["term"]
for expected, actual in zip(sample["schedule"], embedded["schedule"]):
    assert all(actual[key] == value for key, value in expected.items())
assert "<style>" in html and "function render()" in html
print("PASS template loading, self-contained HTML and synthetic data preservation")
