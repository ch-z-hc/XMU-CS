"""Rebuild the public demo from synthetic data without contacting the university."""
from pathlib import Path
import json

root = Path(__file__).resolve().parents[1]
data = json.loads((root / "docs" / "schedule-demo.json").read_text(encoding="utf-8"))
html = (root / "templates" / "schedule.html").read_text(encoding="utf-8")
html = html.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c"))
html = html.replace('href="./assets/', 'href="../assets/').replace('href="./manifest.json', 'href="../manifest.json')
(root / "docs" / "schedule-demo.html").write_text(html, encoding="utf-8")
