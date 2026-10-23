
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_FILE = DATA_DIR / "central_policies.json"

BASE_URL = (
    "https://apis.data.go.kr/"
    "B554287/NationalWelfareInformationsV001"
)
LIST_URL = BASE_URL + "/NationalWelfarelistV001"
DETAIL_URL = BASE_URL + "/NationalWelfaredetailedV001"

MAX_PAGES = 20
ROWS_PER_PAGE = 100
MAX_DETAILS = 40


def log(message):
    print(message, flush=True)


def fail(message):
    log(f"COLLECTION FAILED: {message}")
    sys.exit(1)


def local_name(tag):
    return tag.split("}")[-1]


def child_text(element, names):
    """요소의 직계 자식 중 이름이 일치하는 첫 번째 값을 반환한다."""
    if isinstance(names, str):
        names = [names]

    for child in list(element):
        if local_name(child.tag) in names:
            value = "".join(child.itertext()).strip()
            if value:
                return value

    return ""


def find_text(element, names):
    """하위 요소까지 검색하되, 이름이 일치하는 첫 번째 값을 반환한다."""
    if isinstance(names, str):
        names = [names]

    for child in element.iter():
        if local_name(child.tag) in names:
            value = "".join(child.itertext()).strip()
            if value:
                return value

    return ""


def request_xml(url, params):
   request_params = dict(params)

if "serviceKey" in request_params:
    request_params["serviceKey"] = urllib.parse.unquote(
        request_params["serviceKey"]
    )

query = urllib.parse.urlencode(request_params)
request_url = f"{url}?{query}"

    request = urllib.request.Request(
        request_url,
        headers={"User-Agent": "welfare-gap-helper/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        fail(f"API HTTP 오류 {exc.code}: {body}")
    except urllib.error.URLError as exc:
        fail(f"API 연결 오류: {exc.reason}")
    except TimeoutError:
        fail("API 요청 시간이 초과되었습니다.")

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        preview = raw[:500].decode("utf-8", errors="replace")
        fail(f"XML 응답을 해석할 수 없습니다: {exc}; 응답 일부: {preview}")

    result_code = find_text(root, "resultCode")
    result_message = find_text(root, "resultMessage")

    if result_code and result_code not in ("00", "0000", "0"):
        fail(
            f"API가 오류를 반환했습니다. "
            f"resultCode={result_code}, "
            f"resultMessage={result_message}"
        )

    return root


def get_items(root):
    """응답의 item 요소를 찾는다."""
    return [
        element
        for element in root.iter()
        if local_name(element.tag) == "servList"
        or local_name(element.tag) == "servDtl"
        or local_name(element.tag) == "item"
    ]


def normalize_program(item):
    service_id = (
        child_text(item, ["servId", "servID", "serviceId"])
        or find_text(item, ["servId", "servID", "serviceId"])
    )

    title = (
        child_text(item, ["servNm", "servName", "serviceName", "title"])
        or find_text(item, ["servNm", "servName", "serviceName", "title"])
    )

    if not service_id or not title:
        return None

    def value(*names):
        return child_text(item, list(names)) or find_text(item, list(names))

    detail = {
        "summary": value("servDgst", "servSummary", "summary"),
        "support": value("sprtCtn", "servCont", "support"),
        "target": value("tgtrDtlCn", "trgterIndvdl", "target"),
        "criteria": value("slctCritCn", "slctCrit", "criteria"),
        "application": value("aplyMtdCn", "aplyMtd", "application"),
        "contact": value("rprsCtadr", "telNo", "contact"),
        "department": value("jurMnofNm", "orgName", "department"),
    }

    detail = {key: val for key, val in detail.items() if val}

    url = value("servDtlLink", "servUrl", "url")

    return {
        "id": f"central-{service_id}",
        "servId": service_id,
        "title": title,
        "source": "한국사회보장정보원 중앙부처복지서비스 API",
        "program_level": "central",
        "api_record": True,
        "region": "전국",
        "url": url,
        "detail": detail,
    }


def main():
    api_key = os.environ.get("CENTRAL_WELFARE_API_KEY", "").strip()

    if not api_key:
        fail("CENTRAL_WELFARE_API_KEY 환경 변수가 설정되지 않았습니다.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    programs_by_id = {}

    log("중앙부처 복지서비스 목록 API 호출을 시작합니다.")

    for page in range(1, MAX_PAGES + 1):
        root = request_xml(
            LIST_URL,
            {
    "serviceKey": api_key,
    "callTp": "L",
    "pageNo": page,
    "numOfRows": ROWS_PER_PAGE,
},
        )

        items = get_items(root)

        if not items:
            if page == 1:
                fail(
                    "목록 응답에서 서비스 항목을 찾지 못했습니다. "
                    "API 응답 필드와 요청 매개변수를 확인해야 합니다."
                )
            break

        added = 0

        for item in items:
            program = normalize_program(item)
            if program:
                programs_by_id[program["servId"]] = program
                added += 1

        log(
            f"목록 {page}페이지: "
            f"응답 항목 {len(items)}개, 유효 항목 {added}개"
        )

        total_count_text = find_text(root, "totalCount")
        try:
            total_count = int(total_count_text)
        except (TypeError, ValueError):
            total_count = 0

        if total_count and page * ROWS_PER_PAGE >= total_count:
            break

        if len(items) < ROWS_PER_PAGE:
            break

        time.sleep(0.2)

    programs = list(programs_by_id.values())

    if not programs:
        fail("목록 API에서 유효한 복지서비스를 수집하지 못했습니다.")

    log(f"목록 수집 완료: {len(programs)}개 서비스")

    # 상세 API 호출 한도를 고려하여 일부 서비스만 조회한다.
    detail_count = min(MAX_DETAILS, len(programs))

    for index in range(detail_count):
        program = programs[index]

        try:
            root = request_xml(
                DETAIL_URL,
               {
    "serviceKey": api_key,
    "callTp": "D",
    "servId": program["servId"],
},
            )
        except SystemExit:
            raise

        items = get_items(root)

        if items:
            detail_program = normalize_program(items[0])
            if detail_program:
                program["detail"].update(
                    detail_program.get("detail", {})
                )
                if detail_program.get("url"):
                    program["url"] = detail_program["url"]

        if (index + 1) % 10 == 0 or index + 1 == detail_count:
            log(f"상세 정보 조회: {index + 1}/{detail_count}")

        time.sleep(0.2)

    output = {
        "schema_version": 1,
        "dataset_status": "official_central_api_sync_sampled",
        "source": "한국사회보장정보원 중앙부처복지서비스 API",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "api_count": len(programs),
        "detail_sample_count": detail_count,
        "programs": programs,
    }

    temp_file = DATA_FILE.with_suffix(".json.tmp")

    try:
        temp_file.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_file.replace(DATA_FILE)
    except OSError as exc:
        fail(f"JSON 파일 저장 실패: {exc}")

    log(f"수집 완료: {DATA_FILE}")
    log(f"중앙부처 복지서비스 {len(programs)}개 저장 완료")


if __name__ == "__main__":
    main()
