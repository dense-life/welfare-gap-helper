
"""Collect local-government welfare services using the official API.

The API key must be provided as WELFARE_API_KEY.
This is a bounded discovery sync, not a guarantee of every local program.

Safety features:
- Preserve existing records that are missing from the latest list results.
- Preserve existing details when a detail request fails or returns empty data.
- Stop detail requests immediately when a request quota error is detected.
- Preserve the existing JSON if every list request fails.
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

REQUEST_TIMEOUT = 20
MAX_RETRIES = 1
RETRY_DELAY = 2
ROWS_PER_PAGE = 100
MAX_PAGES_PER_QUERY = 5

# Maximum number of new detail requests per run.
MAX_DETAIL_RECORDS = 20
DETAIL_DELAY = 0.2

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

DETAIL_FIELDS = (
    "description",
    "target",
    "criteria",
    "support",
    "application",
    "contact",
    "official_urls",
)


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
    """Request XML with bounded retries and quota-error detection."""
    request_params = dict(params)
    full_url = url + "?" + urllib.parse.urlencode(request_params)

    req = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": "welfare-gap-helper/2.3",
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

            # Some APIs return quota errors inside XML with HTTP 200.
            error_text = f"{code} {message}".lower()

            if is_quota_error_text(error_text):
                raise RuntimeError(
                    f"API_LIMIT_EXCEEDED: code={code}, message={message}"
                )

            if code and code not in ("0", "00", "0000"):
                raise RuntimeError(
                    f"API 응답 오류 code={code}, message={message}"
                )

            return root

        except urllib.error.HTTPError as exc:
            body = exc.read(1500).decode(
                "utf-8",
                errors="replace",
            )
            last_error = RuntimeError(
                f"HTTP {exc.code}: {body}"
            )

            if exc.code == 429:
                raise RuntimeError(
                    f"API_LIMIT_EXCEEDED: {last_error}"
                ) from exc

            # Retry only temporary server-side errors.
            if exc.code not in (500, 502, 503, 504):
                break

        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            ET.ParseError,
            RuntimeError,
        ) as exc:
            last_error = exc

            if is_quota_error_text(str(exc).lower()):
                raise RuntimeError(
                    f"API_LIMIT_EXCEEDED: {exc}"
                ) from exc

        if attempt < MAX_RETRIES:
            log(
                f"WARN {label}: {last_error}; "
                f"{RETRY_DELAY}초 후 재시도"
            )
            time.sleep(RETRY_DELAY)

    raise RuntimeError(f"{label}: {last_error}")


def is_quota_error_text(message):
    message = str(message).lower()

    return any(
        marker in message
        for marker in (
            "api_limit_exceeded",
            "http 429",
            "returnreasoncode 22",
            "returnreasoncode=22",
            "limited_number_of_service_requests",
            "일일 서비스 요청제한",
            "서비스 요청제한 횟수 초과",
            "요청 한도 초과",
        )
    )


def page(word, topic, page_number):
    root = request(
        LIST,
        {
            "serviceKey": KEY,
            "callTp": "L",
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
    page_rows = {}

    for node in root.iter():
        service_id = txt(node, "servId")
        name = txt(node, "servNm")

        if not service_id or not name:
            continue

        page_rows[service_id] = {
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

    rows = list(page_rows.values())

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
            "callTp": "D",
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


def get_service_id(program):
    """Get the API service ID from either supported ID field."""
    service_id = str(program.get("servId", "")).strip()

    if service_id:
        return service_id

    program_id = str(program.get("id", "")).strip()

    if program_id.startswith("api-"):
        return program_id[4:]

    return program_id


def load_existing():
    """Load previous data so existing records and details can be reused."""
    if not OUT.exists():
        return {}

    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
        programs = data.get("programs", [])
        result = {}

        for program in programs:
            if not isinstance(program, dict):
                continue

            service_id = get_service_id(program)

            if service_id:
                result[service_id] = program

        log(f"기존 데이터 확인: {len(result)}개 서비스")
        return result

    except (OSError, json.JSONDecodeError) as exc:
        log(f"WARN 기존 JSON을 읽지 못했습니다: {exc}")
        return {}


def has_detail(program):
    """Return True if the existing record contains usable detail fields."""
    return any(program.get(field) for field in DETAIL_FIELDS)


def main():
    if not KEY:
        raise SystemExit(
            "WELFARE_API_KEY secret is missing. "
            "Check GitHub Settings > Secrets and variables > Actions."
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    existing = load_existing()

    all_rows = {}
    errors = []
    successful_list_requests = 0

    log("지자체 복지서비스 목록 수집을 시작합니다.")
    log(
        f"요청 제한: timeout={REQUEST_TIMEOUT}s, "
        f"retry={MAX_RETRIES}, "
        f"상세정보 최대={MAX_DETAIL_RECORDS}개"
    )

    # Collect list results. Individual query failures do not erase old data.
    for word, topic in QUERIES:
        try:
            first_rows, total = page(word, topic, 1)
            successful_list_requests += 1

            for row in first_rows:
                all_rows[row["id"]] = row

            page_count = min(
                max(
                    1,
                    (total + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE,
                ),
                MAX_PAGES_PER_QUERY,
            )

            for page_number in range(2, page_count + 1):
                try:
                    page_rows, _ = page(word, topic, page_number)
                    successful_list_requests += 1

                    for row in page_rows:
                        all_rows[row["id"]] = row

                except Exception as exc:
                    message = (
                        f"{word} 페이지 {page_number}: {exc}"
                    )
                    errors.append(message)
                    log(f"WARN {message}")

                    if is_quota_error_text(str(exc)):
                        log(
                            "목록 API 호출 한도 초과가 감지되었습니다. "
                            "추가 목록 요청을 중단합니다."
                        )
                        break

        except Exception as exc:
            message = f"{word}: {exc}"
            errors.append(message)
            log(f"WARN {message}")

            if is_quota_error_text(str(exc)):
                log(
                    "목록 API 호출 한도 초과가 감지되었습니다. "
                    "추가 목록 요청을 중단합니다."
                )
                break

    # If no list request succeeded, do not rewrite the existing dataset.
    if successful_list_requests == 0 or not all_rows:
        raise SystemExit(
            "목록 수집에 성공하지 못했거나 결과가 없습니다. "
            "기존 JSON은 변경하지 않았습니다. "
            + "; ".join(errors)
        )

    log(f"이번 목록 수집: {len(all_rows)}개 고유 서비스")

    # Merge newly discovered services with existing records.
    # New list metadata takes precedence only when it is non-empty.
    merged = {}

    for service_id, old in existing.items():
        merged[service_id] = {
            "id": service_id,
            "name": old.get("title") or old.get("name") or "",
            "summary": old.get("summary", ""),
            "region": old.get("region", ""),
            "category": old.get("category", "지자체 복지"),
            "life_stage": old.get("life_stage", ""),
            "updated": old.get("updated", ""),
        }

    for service_id, row in all_rows.items():
        old_row = merged.get(service_id, {})

        merged[service_id] = {
            "id": service_id,
            "name": row.get("name") or old_row.get("name", ""),
            "summary": row.get("summary") or old_row.get("summary", ""),
            "region": row.get("region") or old_row.get("region", ""),
            "category": row.get("category") or old_row.get("category", "지자체 복지"),
            "life_stage": row.get("life_stage") or old_row.get("life_stage", ""),
            "updated": row.get("updated") or old_row.get("updated", ""),
        }

    new_count = sum(
        1 for service_id in all_rows if service_id not in existing
    )
    preserved_missing_count = sum(
        1 for service_id in existing if service_id not in all_rows
    )

    rows = sorted(
        merged.values(),
        key=lambda item: (item.get("region", ""), item.get("name", "")),
    )

    log(f"신규 서비스: {new_count}개")
    log(
        "이번 목록에서 누락되었지만 기존 데이터에서 보존한 서비스: "
        f"{preserved_missing_count}개"
    )
    log(f"병합 후 전체 서비스: {len(rows)}개")

    # Try records with no existing details first.
    rows.sort(
        key=lambda item: (
            has_detail(existing.get(item["id"], {})),
            item.get("region", ""),
            item.get("name", ""),
        )
    )

    detail_attempts = 0
    quota_exceeded = False
    detail_results = {}

    for item in rows:
        service_id = item["id"]
        old = existing.get(service_id, {})

        if has_detail(old):
            continue

        if detail_attempts >= MAX_DETAIL_RECORDS:
            break

        detail_attempts += 1

        try:
            fresh = detail(service_id)
            detail_results[service_id] = fresh

        except Exception as exc:
            detail_results[service_id] = {}
            log(f"WARN 상세정보 {service_id}: {exc}")

            if is_quota_error_text(str(exc)):
                quota_exceeded = True
                log(
                    "상세정보 API 호출 한도 초과가 감지되어 "
                    "추가 상세정보 요청을 중단합니다."
                )
                break

        if detail_attempts % 10 == 0:
            log(
                f"상세정보 진행: "
                f"{detail_attempts}/{MAX_DETAIL_RECORDS}"
            )

        time.sleep(DETAIL_DELAY)

    if quota_exceeded:
        errors.append(
            "상세정보 API 호출 한도 초과로 상세정보 갱신을 "
            "중단했습니다. 기존 상세정보는 재사용합니다."
        )

    programs = []

    for item in rows:
        service_id = item["id"]
        old = existing.get(service_id, {})
        fresh = detail_results.get(service_id, {})

        def choose(field, old_field=None):
            old_key = old_field or field
            return fresh.get(field) or old.get(old_key, "")

        urls = (
            fresh.get("official_urls")
            or old.get("official_urls")
            or []
        )

        if not isinstance(urls, list):
            urls = [urls] if urls else []

        title = item.get("name") or old.get("title") or old.get("name", "")

        program = {
            "id": old.get("id") or ("api-" + service_id),
            "servId": service_id,
            "title": title,
            "category": (
                item.get("category")
                or old.get("category")
                or "지자체 복지"
            ),
            "region": item.get("region") or old.get("region", ""),
            "life_stage": (
                item.get("life_stage")
                or old.get("life_stage", "")
            ),
            "summary": (
                item.get("summary")
                or fresh.get("description")
                or old.get("summary", "")
            ),
            "description": choose("description"),
            "target": choose("target"),
            "criteria": choose("criteria"),
            "support": choose("support"),
            "application": choose("application"),
            "contact": choose("contact"),
            "official_urls": urls,
            "url": (
                urls[0]
                if urls
                else old.get("url", "")
            ),
            "source": (
                old.get("source")
                or "한국사회보장정보원 지자체복지서비스 API"
            ),
            "updated": (
                fresh.get("last_updated")
                or item.get("updated")
                or old.get("updated")
                or "API 갱신일 미제공"
            ),
            "api_record": True,
        }

        # Retain other pre-existing fields that this script does not manage.
        managed_fields = set(program.keys())

        for key, value in old.items():
            if key not in managed_fields:
                program[key] = value

        programs.append(program)

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
            "상세정보나 신청 URL이 없는 경우 빈 값으로 표시합니다. "
            "이번 목록에서 누락된 기존 서비스는 보존하며, "
            "상세 API 호출 제한으로 일부 항목은 기존 상세정보를 "
            "유지할 수 있습니다."
        ),
        "sync_errors": errors,
        "programs": programs,
        "refresh_plan": {
            "frequency": "weekly via GitHub Actions",
            "provider": "한국사회보장정보원 지자체복지서비스 API",
            "paid_services": False,
            "status": (
                "scheduled_sync_configured; coverage is bounded "
                "by query strategy and API limits"
            ),
        },
    }

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
    log(f"상세정보 요청 시도: {detail_attempts}개")
    log(f"호출 한도 초과 감지: {'예' if quota_exceeded else '아니오'}")


if __name__ == "__main__":
    main()
