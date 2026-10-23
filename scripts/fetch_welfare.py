
"""Collect local-government welfare services using the official API.

The API key must be provided as WELFARE_API_KEY.
This is a bounded discovery sync, not a guarantee of every local program.
If all list requests fail, the existing output JSON is preserved.
"""

import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from datetime import datetime, timezone, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "policies.json"

BASE = (
    "https://apis.data.go.kr/"
    "B554287/LocalGovernmentWelfareInformations"
)
LIST = BASE + "/LcgvWelfarelist"
DETAIL = BASE + "/LcgvWelfaredetailed"

KEY = os.environ.get("WELFARE_API_KEY", "").strip()

# 연결 문제를 빠르게 진단할 수 있도록 제한한다.
REQUEST_TIMEOUT = 20
MAX_RETRIES = 1
RETRY_DELAY = 2
ROWS_PER_PAGE = 100
MAX_PAGES_PER_QUERY = 5
MAX_DETAIL_RECORDS = 150
DETAIL_DELAY = 0.1

QUERIES = [
    ("주거", "040"),
    ("생활지원", "030"),
    ("돌봄", "120"),
    ("건강", "010"),
    ("일자리", "050"),
    ("안전", "070"),
    ("교육", "100"),
    ("문화", "060"),
    ("법률", "140"),
    ("금융", "130"),
]


def log(message):
    print(message, flush=True)


def local_name(tag):
    return tag.split("}")[-1]


def txt(node, names):
    if isinstance(names, str):
        names = [names]

    for name in names:
        for element in node.iter():
            if (
                local_name(element.tag) == name
                and element.text
                and element.text.strip()
            ):
                return element.text.strip()

    return ""


def request(url, params, label):
    """Request XML with a bounded retry policy."""
    full_url = url + "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": "welfare-gap-helper/2.1",
            "Accept": "application/xml,text/xml,*/*",
        },
    )

    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            log(
                f"API 요청: {label} "
                f"(시도 {attempt + 1}/{MAX_RETRIES + 1})"
            )

            with urllib.request.urlopen(
                req,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                raw = response.read()

            root = ET.fromstring(raw)

            code = txt(root, ["resultCode"])
            message = txt(root, ["resultMsg", "resultMessage"])

            if code and code not in ("0", "00", "0000"):
                raise RuntimeError(
                    f"API 응답 오류 code={code}, message={message}"
                )

            return root

        except urllib.error.HTTPError as exc:
            # 인증 오류나 잘못된 파라미터는 무조건 재시도하지 않는다.
            body = exc.read(1000).decode(
                "utf-8",
                errors="replace",
            )
            last_error = RuntimeError(
                f"HTTP {exc.code}: {body}"
            )

            if exc.code not in (429, 500, 502, 503, 504):
                break

        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            ET.ParseError,
            RuntimeError,
        ) as exc:
            last_error = exc

        if attempt < MAX_RETRIES:
            log(
                f"WARN {label}: {last_error}; "
                f"{RETRY_DELAY}초 후 재시도"
            )
            time.sleep(RETRY_DELAY)

    raise RuntimeError(f"{label}: {last_error}")


def page(word, topic, page_number):
    root = request(
        LIST,
        {
            "serviceKey": KEY,
            "pageNo": page_number,
            "numOfRows": ROWS_PER_PAGE,
            "intrsThemaArray": topic,
            "srchKeyCode": "003",
            "searchWrd": word,
            "arrgOrd": "001",
        },
        f"목록/{word}/페이지 {page_number}",
    )

    total_text = txt(root, "totalCount")
    rows = []

    # 서비스 항목을 찾을 때 중첩 XML에서 같은 서비스가
    # 중복 수집되지 않도록 servId 기준으로 정리한다.
    page_rows = {}

    for node in root.iter():
        service_id = txt(node, "servId")
        name = txt(node, "servNm")

        if not service_id or not name:
            continue

        row = {
            "id": service_id,
            "name": name,
            "summary": txt(
                node,
                ["servDgst", "servDtlCn", "servCn", "servExpln"],
            ),
            "region": " ".join(
                value
                for value in [
                    txt(node, "ctpvNm"),
                    txt(node, "sggNm"),
                ]
                if value
            ),
            "category": (
                txt(
                    node,
                    [
                        "intrsThemaNmArray",
                        "intrsThemaNm",
                        "intrsThema",
                    ],
                )
                or word
            ),
            "life_stage": txt(node, ["lifeNmArray", "lifeNm"]),
            "updated": txt(node, "lastModYmd"),
        }

        page_rows[service_id] = row

    rows.extend(page_rows.values())

    try:
        total = int(total_text)
    except (TypeError, ValueError):
        total = len(rows)

    return rows, total


def detail(service_id):
    root = request(
        DETAIL,
        {
            "serviceKey": KEY,
            "servId": service_id,
        },
        f"상세/{service_id}",
    )

    fields = {
        "description": [
            "servDgst",
            "servDtlCn",
            "servCn",
            "servExpln",
        ],
        "target": [
            "sprtTrgtCn",
            "trgtCn",
            "sprtTrgt",
        ],
        "criteria": [
            "slctCritCn",
            "slctnCritCn",
            "slctCrit",
        ],
        "support": [
            "alwServCn",
            "srvPvsnCn",
            "sprtCn",
        ],
        "application": [
            "aplyMtdCn",
            "aplyMthdCn",
            "aplyMtd",
        ],
        "contact": [
            "inqplCtadrList",
            "inqplCtadr",
            "telno",
        ],
        "last_updated": ["lastModYmd"],
    }

    result = {
        key: txt(root, names)
        for key, names in fields.items()
    }

    result = {
        key: value
        for key, value in result.items()
        if value
    }

    urls = []

    for element in root.iter():
        tag = local_name(element.tag).lower()
        value = (element.text or "").strip()

        if value.startswith("http") and any(
            marker in tag
            for marker in (
                "url",
                "site",
                "link",
                "homepage",
                "aply",
            )
        ):
            urls.append(value)

    result["official_urls"] = list(dict.fromkeys(urls))

    return result


def main():
    if not KEY:
        raise SystemExit(
            "WELFARE_API_KEY secret is missing. "
            "Check GitHub Settings > Secrets and variables > Actions."
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)

    all_rows = {}
    errors = []
    consecutive_list_failures = 0

    log("지자체 복지서비스 목록 수집을 시작합니다.")
    log(f"요청 제한: timeout={REQUEST_TIMEOUT}s, retry={MAX_RETRIES}")
    log(f"검색 분야: {len(QUERIES)}개")

    for word, topic in QUERIES:
        try:
            first_rows, total = page(word, topic, 1)

            consecutive_list_failures = 0

            for row in first_rows:
                all_rows[row["id"]] = row

            page_count = min(
                (total + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE,
                MAX_PAGES_PER_QUERY,
            )

            for page_number in range(2, page_count + 1):
                page_rows, _ = page(word, topic, page_number)

                for row in page_rows:
                    all_rows[row["id"]] = row

            log(
                f"성공 {word}: API 전체 건수={total}, "
                f"누적 고유 서비스={len(all_rows)}"
            )

        except Exception as exc:
            message = f"{word}: {exc}"
            errors.append(message)
            consecutive_list_failures += 1
            log(f"WARN {message}")

            # 첫 분야부터 두 차례 연속으로 실패하면
            # 모든 검색어를 계속 호출하지 않고 연결 문제를 알린다.
            if consecutive_list_failures >= 2 and not all_rows:
                raise SystemExit(
                    "목록 API 요청이 연속으로 실패했습니다. "
                    "API 서버 상태, 요청 URL, API 키 및 "
                    "GitHub Actions 네트워크를 확인하세요. "
                    "기존 JSON은 변경하지 않았습니다. "
                    + "; ".join(errors)
                )

    if not all_rows:
        raise SystemExit(
            "No records collected; existing JSON preserved. "
            + "; ".join(errors)
        )

    rows = sorted(
        all_rows.values(),
        key=lambda item: (item["region"], item["name"]),
    )[:MAX_DETAIL_RECORDS]

    log(f"목록 수집 완료: {len(all_rows)}개 고유 서비스")
    log(f"상세정보 수집 대상: {len(rows)}개")

    for index, item in enumerate(rows, start=1):
        try:
            item["detail"] = detail(item["id"])

        except Exception as exc:
            item["detail"] = {}
            item["detail_error"] = str(exc)
            log(f"WARN 상세정보 {item['id']}: {exc}")

        if index % 25 == 0:
            log(f"상세정보 진행: {index}/{len(rows)}")

        time.sleep(DETAIL_DELAY)

    programs = []

    for item in rows:
        detail_data = item.get("detail", {})
        urls = detail_data.get("official_urls", [])

        programs.append(
            {
                "id": "api-" + item["id"],
                "servId": item["id"],
                "title": item["name"],
                "category": item["category"] or "지자체 복지",
                "region": item["region"],
                "life_stage": item["life_stage"],
                "summary": (
                    item["summary"]
                    or detail_data.get("description", "")
                ),
                "description": detail_data.get("description", ""),
                "target": detail_data.get("target", ""),
                "criteria": detail_data.get("criteria", ""),
                "support": detail_data.get("support", ""),
                "application": detail_data.get("application", ""),
                "contact": detail_data.get("contact", ""),
                "official_urls": urls,
                "url": urls[0] if urls else "",
                "source": (
                    "한국사회보장정보원 지자체복지서비스 API"
                ),
                "updated": (
                    detail_data.get("last_updated")
                    or item.get("updated")
                    or "API 갱신일 미제공"
                ),
                "api_record": True,
            }
        )

    now = datetime.now(
        timezone(timedelta(hours=9))
    ).isoformat(timespec="seconds")

    data = {
        "schema_version": 4,
        "dataset_status": "official_api_sync_sampled",
        "generated_at": now,
        "api_count": len(programs),
        "coverage_note": (
            "검색어·관심주제별로 수집한 API 결과입니다. "
            "API에 등록된 전국 모든 사업을 보장하지 않으며, "
            "상세정보나 신청 URL이 없는 경우 빈 값으로 표시합니다."
        ),
        "sync_errors": errors,
        "programs": programs,
        "refresh_plan": {
            "frequency": "weekly via GitHub Actions",
            "provider": "한국사회보장정보원 지자체복지서비스 API",
            "paid_services": False,
            "status": "scheduled_sync_configured; coverage is bounded "
            "by query strategy and API limits",
        },
    }

    # 임시 파일에 먼저 기록한 후 교체해 저장 중 손상을 방지한다.
    temp_file = OUT.with_suffix(".json.tmp")

    try:
        temp_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_file.replace(OUT)

    except OSError as exc:
        if temp_file.exists():
            temp_file.unlink()
        raise SystemExit(f"JSON 저장 실패: {exc}")

    log(f"저장 완료: {OUT}")
    log(f"저장된 서비스: {len(programs)}개")
    log(f"목록 수집 오류: {len(errors)}개")


if __name__ == "__main__":
    main()
