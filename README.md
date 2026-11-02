# 복지틈새찾기 (지자체 API 기반 MVP)

## 데이터 갱신 방식과 한계

- 웹페이지는 검색할 때마다 정부 API를 직접 호출하지 않습니다. 브라우저에 API 인증키를 공개하지 않도록 GitHub Actions가 API를 주기적으로 호출해 `data/policies.json`, `data/central_policies.json`을 갱신하고, 페이지는 이 JSON 수집본을 불러옵니다.
- 기본 자동 실행은 매주 1회입니다. 지자체 수집은 전체 목록을 먼저 페이지 단위로 요청하고, API가 전체 목록 조회를 허용하지 않을 때 여러 주제별 검색으로 전환합니다. 중앙부처도 전체 페이지를 순회합니다. 가장 최근 수집 시각은 화면에 표시됩니다. 검색 요청마다 최신 API 응답을 받아야 한다면 GitHub Pages만으로는 구현할 수 없으며, 인증키를 보관하는 서버리스 API나 백엔드 배포가 추가로 필요합니다.
- JSON 파일을 직접 열지 말고 GitHub Pages 주소 또는 로컬 웹서버에서 페이지를 여세요. `file://` 실행은 상대 경로 JSON 요청이 차단될 수 있습니다.

### 로컬에서 실행

저장소 폴더에서 Node.js가 설치된 환경이라면 `node serve-local.mjs`를 실행한 뒤 `http://127.0.0.1:8000/`을 여세요. 종료할 때는 서버가 실행 중인 터미널에서 `Ctrl+C`를 누릅니다.

## 이 버전의 결과
1. 입력한 조건과 지역을 바탕으로 지자체 복지서비스 후보 검색
2. API가 제공한 상세 설명·지원 대상·선정 기준·지원 내용·신청 방법·문의처 표시
3. API가 명시적으로 제공한 공식 URL만 신청/안내 링크로 표시. URL이 없으면 임의로 복지로 메인 페이지를 신청 링크처럼 표시하지 않음.

## 중요 제한
- 이 프로그램은 한국사회보장정보원 지자체·중앙부처 복지서비스 API를 사용합니다. 모든 공공기관 사업을 포함하지는 않습니다.
- 수집 스크립트는 여러 관심 주제와 검색어로 조회하고 페이지 수 및 상세조회 수를 제한합니다. 따라서 전국의 모든 지자체 사업이 빠짐없이 수집된다고 보장하지 않습니다.
- API에 상세 기준이나 신청 URL이 없으면 화면에도 없는 것으로 표시합니다. 사용자의 자격을 확정하지 않습니다.
- 지자체 상세 API 요청은 실행당 최대 20건입니다. 중앙부처 목록은 페이지 단위로 수집하며 상세 API는 현재 호출하지 않습니다.

## 설치
1. GitHub에서 공개 저장소를 만들고 이 폴더 안의 파일을 저장소 최상위에 올립니다.
2. Settings → Secrets and variables → Actions 에 `WELFARE_API_KEY`를 만들고 지자체 API 인증키를 입력합니다. 이 키가 중앙부처 API 사용 신청에도 승인된 키라면 중앙부처 수집에 재사용합니다. 별도 키를 발급받았다면 `CENTRAL_WELFARE_API_KEY`를 추가하세요. 키를 HTML이나 JSON에 넣지 마세요.
3. Actions 탭에서 `Weekly welfare API sync`를 선택하고 `Run workflow`로 최초 실행합니다. 지자체/중앙부처 수집과 검증 단계가 모두 성공했는지 확인하세요.
4. 실행 로그에서 수집 건수와 오류를 확인합니다. `data/policies.json`이 갱신되면 Pages를 배포합니다.
5. Settings → Pages → Deploy from a branch → `main` / `/(root)` 설정합니다.

## 데이터 출처
한국사회보장정보원 지자체복지서비스 API: https://www.data.go.kr/data/15108347/openapi.do
목록 endpoint: `https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations/LcgvWelfarelist`
상세 endpoint: `https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations/LcgvWelfaredetailed`

## 업데이트
GitHub Actions는 매주 자동 실행되며 수동 실행도 가능합니다. 자동 실행이 성공했는지는 Actions 실행 결과에서 확인해야 합니다. 자동 업데이트는 API가 제공하는 데이터 범위 내에서만 동작합니다.
