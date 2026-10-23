
"""Collect central-government welfare services from the approved official API.

API key: CENTRAL_WELFARE_API_KEY
Output: data/central_policies.json

The script preserves the previous output if collection fails.
Coverage depends on the API's published records and quota.
"""
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "central_policies.json"

BASE = (
    "https://apis.data.go.kr/"
    "B554287/NationalWelfareInformationsV001"
)
LIST_URL = BASE + "/NationalWelfarelistV001"
DETAIL_URL = BASE + "/NationalWelfaredetailedV001"

KEY = os.environ.get("CENTRAL_WELFARE_API_KEY", "").strip()

if not KEY:
    raise SystemExit(
        "CENTRAL_WELFARE_API_KEY secret is missing."
    )


def text_of(node, names):
    wanted = set(names)
    for element in node.iter():
        tag = element.tag.split("}")[-1]
        value = (element.text or "").strip()
        if tag in wanted and value:
            return value
    return ""


def request_xml(url, params):
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url + "?" + query,
        headers={"User-Agent": "welfare-gap-helper/1.0"},
    )
    with urllib.request.urlopen(req, timeout=40) as response:
        raw = response.read()

    root = ET.fromstring(raw)
    code = text_of(root, ["resultCode"])
    message = text_of(root, ["resultMsg"])

    # Some API responses use 00 or 0000 for success.
    if code and code not in ("0", "00", "0000"):
        if "SUCCESS" not in message.upper():
            raise RuntimeError(
                f"API error {code}: {message}"
            )

    return root


def list_page(page_no):
    root = request_xml(
        LIST_URL,
        {
            "serviceKey": KEY,
            "callTp": "L",
            "pageNo": page_no,
            "numOfRows": 500,
            "srchKeyCode": "003",
            "searchWrd": "",
            "orderBy": "date",
        },
    )

    total_text = text_of(root, ["totalCount"])
    total = int(total_text) if total_text.isdigit() else 0
    records = []

    for node in root.iter():
        sid = text_of(node, ["servId"])
        name = text_of(node, ["servNm", "serviceName", "title"])

        if not sid or not name:
            continue

        # Ignore parent/container elements that happen to contain
        # a descendant's ID and title.
        if any(x.get("id") == sid for x in records):
            continue

        records.append({
            "servId": sid,
            "title": name,
            "summary": text_of(
                node,
                ["servDgst", "servCn", "servExpln", "servDtlCn"],
            ),
            "category": text_of(
                node,
                ["intrsThemaNmArray", "intrsThemaNm", "servType"],
            ) or "중앙부처 복지",
            "life_stage": text_of(
                node, ["lifeNmArray", "lifeNm"]
            ),
            "target_group": text_of(
                node,
                ["trgterIndvdlNmArray", "trgterIndvdlNm"],
            ),
            "updated": text_of(
                node, ["lastModYmd", "lastModDt", "updtDt"]
            ),
            "official_url": text_of(
                node,
                ["servDtlLink", "servUrl", "detailUrl", "url"],
            ),
        })

    return records, total


def get_detail(service_id):
    # Detail operation and parameters should follow the approved
    # API specification. If detail is unavailable, list data is kept.
    root = request_xml(
        DETAIL_URL,
        {
            "serviceKey": KEY,
            "callTp": "D",
            "servId": service_id,
        },
    )

    fields = {
        "description": [
            "servDgst", "servDtlCn", "servCn", "servExpln"
        ],
        "target": ["sprtTrgtCn", "trgtCn", "sprtTrgt"],
        "criteria": ["slctCritCn", "slctnCritCn", "slctCrit"],
        "support": ["alwServCn", "srvPvsnCn", "sprtCn"],
        "application": ["aplyMtdCn", "aplyMthdCn", "aplyMtd"],
        "contact": ["inqplCtadrList", "inqplCtadr", "telno"],
        "last_updated": ["lastModYmd", "lastModDt", "updtDt"],
    }

    detail = {
        key: text_of(root, names)
        for key, names in fields.items()
    }

    # Keep only URLs explicitly supplied by the API.
    urls = []
    for element in root.iter():
        tag = element.tag.split("}")[-1].lower()
        value = (element.text or "").strip()
        if value.startswith("https://") or value.startswith("http://"):
            if any(word in tag for word in ("url", "site", "link", "aply")):
                urls.append(value)

    detail["official_urls"] = list(dict.fromkeys(urls))
    return detail


# The API has a daily request quota. Keep each run bounded.
# At most 20 list requests and 40 detail requests per run.
all_records = {}
errors = []

try:
    first, total = list_page(1)
    for item in first:
        all_records[item["servId"]] = item

    page_size = 500
    pages_needed = (total + page_size - 1) // page_size
    pages_to_fetch = min(max(pages_needed, 1), 20)

    for page_no in range(2, pages_to_fetch + 1):
        try:
            records, _ = list_page(page_no)
            for item in records:
                all_records[item["servId"]] = item
            time.sleep(0.15)
        except Exception as exc:
            errors.append(f"list page {page_no}: {exc}")
            print(errors[-1])
            break

except Exception as exc:
    raise SystemExit(
        "Central welfare list request failed; previous output preserved. "
        + str(exc)
    )

if not all_records:
    raise SystemExit(
        "No central welfare records collected; previous output preserved. "
        + "; ".join(errors)
    )

# Stable ordering makes the generated file easier to review.
records = sorted(
    all_records.values(),
    key=lambda item: (item["title"], item["servId"]),
)

# Detail calls are limited to reduce daily quota consumption.
for index, item in enumerate(records[:40]):
    try:
        item["detail"] = get_detail(item["servId"])
    except Exception as exc:
        item["detail"] = {}
        item["detail_error"] = str(exc)

    if index and index % 10 == 0:
        print(f"Detail requests attempted: {index}/{min(len(records), 40)}")
    time.sleep(0.15)

programs = []
for item in records:
    detail = item.get("detail", {})
    urls = detail.get("official_urls", [])

    # A URL from the list response is retained only if the API supplied it.
    list_url = item.get("official_url", "").strip()
    if list_url.startswith(("https://", "http://")):
        urls = list(dict.fromkeys([list_url] + urls))

    programs.append({
        "id": "central-api-" + item["servId"],
        "servId": item["servId"],
        "title": item["title"],
        "category": item["category"],
        "region": "전국",
        "life_stage": item["life_stage"],
        "summary": item["summary"] or detail.get("description", ""),
        "description": detail.get("description", ""),
        "target": detail.get("target", "") or item["target_group"],
        "criteria": detail.get("criteria", ""),
        "support": detail.get("support", ""),
        "application": detail.get("application", ""),
        "contact": detail.get("contact", ""),
        "official_urls": urls,
        "url": urls[0] if urls else list_url,
        "source": "한국사회보장정보원 중앙부처복지서비스 API",
        "updated": (
            detail.get("last_updated")
            or item["updated"]
            or "API 갱신일 미제공"
        ),
        "api_record": True,
        "program_level": "central",
    })

now = datetime.now(
    timezone(timedelta(hours=9))
).isoformat(timespec="seconds")

data = {
    "schema_version": 1,
    "dataset_status": "official_central_api_sync_sampled",
    "generated_at": now,
    "api_count": len(programs),
    "coverage_note": (
        "중앙부처 복지서비스 공식 API에서 수집한 자료입니다. "
        "API 응답 및 호출 한도에 따라 누락될 수 있으며, "
        "개별 자격과 신청 가능 여부는 담당 기관에서 확인해야 합니다."
    ),
    "sync_errors": errors,
    "programs": programs,
    "refresh_plan": {
        "frequency": "weekly via GitHub Actions",
        "provider": "한국사회보장정보원 중앙부처복지서비스 API",
        "paid_services": False,
    },
}

OUT.parent.mkdir(parents=True, exist_ok=True)
temp_path = OUT.with_suffix(".json.tmp")
temp_path.write_text(
    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
temp_path.replace(OUT)

print(f"Wrote {len(programs)} central services to {OUT}")
print(f"List total reported by API: {total}")
print(f"Warnings: {len(errors)}")
