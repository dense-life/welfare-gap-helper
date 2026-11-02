
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

# 목록 API 페이지를 순회해 등록된 중앙부처 서비스를 수집한다.
MAX_PAGES = 100
ROWS_PER_PAGE = 100
MAX_DETAILS = 0


def log(message):
    print(message, flush=True)


def fail(message):
    log(f"COLLECTION FAILED: {message}")
    sys.exit(1)


def local_name(tag):
    return tag.split("}")[-1]


def find_text(element, names):
    if isinstance(names, str):
        names = [names]

    for child in element.iter():
        if local_name(child.tag) in names:
            value = "".join(child.itertext()).strip()
            if value:
                return value

    return ""


def child_text(element, names):
    if isinstance(names, str):
        names = [names]

    for child in list(element):
        if local_name(child.tag) in names:
            value = "".join(child.itertext()).strip()
            if value:
                return value

    return ""


def request_xml(url, params):
    """API를 호출하고 XML 응답을 반환한다."""
    request_params = dict(params)

    # 인증키는 환경 변수에서 가져온 값을 사용한다.
    # URL 인코딩 키와 디코딩 키의 차이를 확인하기 전까지
    # 인증키를 임의로 unquote() 하지 않는다.
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
        body = exc.read().decode(
            "utf-8", errors="replace"
        )[:1500]
        fail(f"API HTTP 오류 {exc.code}: {body}")

    except urllib.error.URLError as exc:
        fail(f"API 연결 오류: {exc.reason}")

    except TimeoutError:
        fail("API 요청 시간이 초과되었습니다.")

    try:
        root = ET.fromstring(raw)

    except ET.ParseError as exc:
        preview = raw[:1000].decode(
            "utf-8", errors="replace"
        )
        fail(
            f"XML 응답 해석 실패: {exc}; "
            f"응답 일부: {preview}"
        )

    result_code = find_text(root, "resultCode")
    result_message = find_text(root, "resultMessage")

    log(
        f"API 응답 코드: {result_code or '(없음)'} / "
        f"메시지: {result_message or '(없음)'}"
    )

    if result_code and result_code not in ("0", "00", "0000"):
        fail(
            f"API 오류 resultCode={result_code}, "
            f"resultMessage={result_message}"
        )

    return root


def get_items(root):
    """목록 응답에서 복지서비스 항목을 찾는다."""
    return [
        element
        for element in root.iter()
        if local_name(element.tag) in (
            "servList",
            "servDtl",
            "item",
        )
    ]


def normalize_program(item):
    """목록 응답을 프로젝트의 공통 데이터 구조로 변환한다."""
    service_id = (
        child_text(item, ["servId", "servID", "serviceId"])
        or find_text(item, ["servId", "servID", "serviceId"])
    )

    title = (
        child_text(
            item,
            ["servNm", "servName", "serviceName", "title"],
        )
        or find_text(
            item,
            ["servNm", "servName", "serviceName", "title"],
        )
    )

    if not service_id or not title:
        return None

    def value(*names):
        return (
            child_text(item, list(names))
            or find_text(item, list(names))
        )

    detail = {
        "summary": value("servDgst", "servSummary", "summary"),
        "support": value("sprtCtn", "servCont", "support"),
        "target": value("tgtrDtlCn", "trgterIndvdl", "target"),
        "criteria": value("slctCritCn", "slctCrit", "criteria"),
        "application": value("aplyMtdCn", "aplyMtd", "application"),
        "contact": value("rprsCtadr", "telNo", "contact"),
        "department": value("jurMnofNm", "orgName", "department"),
    }

    detail = {
        key: val
        for key, val in detail.items()
        if val
    }

    return {
        "id": f"central-{service_id}",
        "servId": service_id,
        "title": title,
        "source": "한국사회보장정보원 중앙부처복지서비스 API",
        "program_level": "central",
        "api_record": True,
        "region": "전국",
        "url": value("servDtlLink", "servUrl", "url"),
        "detail": detail,
    }


def main():
    api_key = os.environ.get(
        "CENTRAL_WELFARE_API_KEY", ""
    ).strip()

    if not api_key:
        log(
            "SKIP: CENTRAL_WELFARE_API_KEY가 없어 중앙부처 API 수집을 "
            "건너뜁니다. 기존 중앙부처 데이터는 유지합니다."
        )
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    programs_by_id = {}

    log("중앙부처 복지서비스 목록 API 수집을 시작합니다.")
    log(
        f"요청 조건: callTp=L, numOfRows={ROWS_PER_PAGE}, "
        f"최대 페이지={MAX_PAGES}, srchKeyCode=001"
    )

    total_count = None
    page_count = 1
    for page_number in range(1, MAX_PAGES + 1):
        root = request_xml(
            LIST_URL,
            {
                "serviceKey": api_key,
                "callTp": "L",
                "pageNo": page_number,
                "numOfRows": ROWS_PER_PAGE,
                "srchKeyCode": "001",
            },
        )
        items = get_items(root)
        if page_number == 1:
            try:
                total_count = int(find_text(root, "totalCount"))
            except (TypeError, ValueError):
                total_count = len(items)
            if total_count > 0:
                page_count = min(
                    MAX_PAGES,
                    (total_count + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE,
                )

        for item in items:
            program = normalize_program(item)
            if program:
                programs_by_id[program["servId"]] = program

        log(
            f"목록 진행: {page_number}/{page_count}페이지, "
            f"현재 {len(programs_by_id)}개"
        )
        if page_number >= page_count or not items:
            break

    programs = list(programs_by_id.values())
    if not programs:
        fail("목록 응답에서 유효한 중앙부처 복지서비스를 찾지 못했습니다.")
    if total_count is None:
        total_count = len(programs)

    output = {
        "schema_version": 1,
        "dataset_status": "official_central_api_sync",
        "source": "한국사회보장정보원 중앙부처복지서비스 API",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "api_count": len(programs),
        "detail_sample_count": MAX_DETAILS,
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

    log(f"목록 수집 성공: 유효 서비스 {len(programs)}개")
    log(f"API 응답의 전체 서비스 건수: {total_count}")
    log(f"파일 저장 완료: {DATA_FILE}")
    log("상세 API는 이번 시험에서 호출하지 않았습니다.")


if __name__ == "__main__":
    main()
