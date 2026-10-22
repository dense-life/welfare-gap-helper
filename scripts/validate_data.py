"""Validate the local-government welfare API catalog produced by fetch_welfare.py."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "data" / "policies.json"
data = json.loads(path.read_text(encoding="utf-8"))
assert data.get("schema_version") == 4, f"Unexpected schema_version: {data.get('schema_version')}"
assert data.get("dataset_status") in ("official_api_sync_sampled", "official_api_sync_empty"), f"Unexpected dataset_status: {data.get('dataset_status')}"
programs = data.get("programs")
assert isinstance(programs, list), "programs must be a list"
if data.get("dataset_status") == "official_api_sync_sampled":
    assert len(programs) > 0, "API sync status says sampled but programs is empty"
seen = set()
for program in programs:
    for key in ("id", "title", "source", "servId"):
        assert program.get(key), f"API program missing {key}: {program.get('id', '(no id)')}"
    assert program["id"] not in seen, f"Duplicate id: {program['id']}"
    seen.add(program["id"])
    assert program.get("api_record") is True, f"Non-API record in API catalog: {program['id']}"
print(f"API catalog OK: {len(programs)} records; status={data.get('dataset_status')}; generated_at={data.get('generated_at')}")
for err in data.get("sync_errors", []):
    print(f"WARN: {err}")
