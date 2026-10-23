
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "central_policies.json"


def fail(message):
    print(f"VALIDATION FAILED: {message}")
    sys.exit(1)


def main():
    if not DATA_FILE.exists():
        fail("data/central_policies.json 파일이 없습니다.")

    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        fail(f"JSON 파일을 읽을 수 없습니다: {exc}")

    if not isinstance(data, dict):
        fail("최상위 데이터는 JSON 객체여야 합니다.")

    if data.get("schema_version") != 1:
        fail("schema_version이 1이 아닙니다.")

    if data.get("dataset_status") != "official_central_api_sync_sampled":
        fail("dataset_status가 예상한 값과 다릅니다.")

    programs = data.get("programs")
    if not isinstance(programs, list):
        fail("programs는 목록이어야 합니다.")

    if not programs:
        fail("중앙부처 복지서비스 데이터가 비어 있습니다.")

    seen_ids = set()
    seen_service_ids = set()

    required_fields = ["id", "servId", "title", "source"]

    for index, program in enumerate(programs, start=1):
        if not isinstance(program, dict):
            fail(f"{index}번째 서비스가 객체가 아닙니다.")

        for field in required_fields:
            value = program.get(field)
            if not isinstance(value, str) or not value.strip():
                fail(f"{index}번째 서비스의 {field} 값이 없습니다.")

        if program.get("api_record") is not True:
            fail(f"{index}번째 서비스의 api_record가 true가 아닙니다.")

        if program.get("program_level") != "central":
            fail(f"{index}번째 서비스의 program_level이 central이 아닙니다.")

        if program["id"] in seen_ids:
            fail(f"중복 id: {program['id']}")

        if program["servId"] in seen_service_ids:
            fail(f"중복 servId: {program['servId']}")

        seen_ids.add(program["id"])
        seen_service_ids.add(program["servId"])

    if data.get("api_count") != len(programs):
        fail("api_count와 programs 개수가 일치하지 않습니다.")

    print(f"VALIDATION OK: {len(programs)}개 중앙부처 복지서비스")


if __name__ == "__main__":
    main()
