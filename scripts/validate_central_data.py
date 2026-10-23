```python
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "central_policies.json"


def fail(message):
    print(f"VALIDATION FAILED: {message}", flush=True)
    sys.exit(1)


def main():
    if not DATA_FILE.exists():
        fail(f"데이터 파일이 없습니다: {DATA_FILE}")

    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"JSON 파일을 읽을 수 없습니다: {exc}")

    if not isinstance(data, dict):
        fail("최상위 데이터는 JSON 객체여야 합니다.")

    if data.get("schema_version") != 1:
        fail("schema_version 값이 1이 아닙니다.")

    if data.get("dataset_status") != "official_central_api_sync_sampled":
        fail("dataset_status 값이 예상과 다릅니다.")

    programs = data.get("programs")

    if not isinstance(programs, list) or not programs:
        fail("programs가 비어 있거나 배열 형식이 아닙니다.")

    required_fields = [
        "id",
        "servId",
        "title",
        "source",
        "api_record",
        "program_level",
    ]

    seen_ids = set()
    seen_serv_ids = set()

    for index, program in enumerate(programs, start=1):
        if not isinstance(program, dict):
            fail(f"{index}번째 프로그램이 객체 형식이 아닙니다.")

        for field in required_fields:
            value = program.get(field)
            if value is None or value == "":
                fail(f"{index}번째 프로그램의 {field} 값이 없습니다.")

        if program.get("api_record") is not True:
            fail(f"{index}번째 프로그램의 api_record가 true가 아닙니다.")

        if program.get("program_level") != "central":
            fail(f"{index}번째 프로그램의 program_level이 central이 아닙니다.")

        program_id = program["id"]
        serv_id = program["servId"]

        if program_id in seen_ids:
            fail(f"중복 id가 있습니다: {program_id}")

        if serv_id in seen_serv_ids:
            fail(f"중복 servId가 있습니다: {serv_id}")

        seen_ids.add(program_id)
        seen_serv_ids.add(serv_id)

    api_count = data.get("api_count")

    if api_count != len(programs):
        fail(
            f"api_count({api_count})와 "
            f"programs 개수({len(programs)})가 다릅니다."
        )

    print(
        f"중앙부처 복지 데이터 검증 성공: "
        f"{len(programs)}개 프로그램",
        flush=True,
    )


if __name__ == "__main__":
    main()
```
