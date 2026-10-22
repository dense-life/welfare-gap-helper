# 복지틈새찾기 (지자체 API 기반 MVP)

## 이 버전의 결과
1. 입력한 조건과 지역을 바탕으로 지자체 복지서비스 후보 검색
2. API가 제공한 상세 설명·지원 대상·선정 기준·지원 내용·신청 방법·문의처 표시
3. API가 명시적으로 제공한 공식 URL만 신청/안내 링크로 표시. URL이 없으면 임의로 복지로 메인 페이지를 신청 링크처럼 표시하지 않음.

## 중요 제한
- 이 프로그램은 한국사회보장정보원 지자체복지서비스 API만 사용합니다. 중앙정부·모든 공공기관 사업을 포함하지 않습니다.
- 수집 스크립트는 여러 관심 주제와 검색어로 조회하고 페이지 수 및 상세조회 수를 제한합니다. 따라서 전국의 모든 지자체 사업이 빠짐없이 수집된다고 보장하지 않습니다.
- API에 상세 기준이나 신청 URL이 없으면 화면에도 없는 것으로 표시합니다. 사용자의 자격을 확정하지 않습니다.
- 현재 무료 API 일일 호출량에 맞춰 실행당 상세조회는 최대 150건으로 제한했습니다. 필요하면 나중에 갱신 전략을 개선할 수 있습니다.

## 설치
1. GitHub에서 공개 저장소를 만들고 이 폴더 안의 파일을 저장소 최상위에 올립니다.
2. Settings → Secrets and variables → Actions → New repository secret 에 `WELFARE_API_KEY` 를 만들고 공공데이터포털 일반인증키를 입력합니다. 키를 HTML이나 JSON에 넣지 마세요.
3. Actions 탭에서 `Weekly welfare API sync`를 선택하고 `Run workflow`로 최초 실행합니다.
4. 실행 로그에서 수집 건수와 오류를 확인합니다. `data/policies.json`이 갱신되면 Pages를 배포합니다.
5. Settings → Pages → Deploy from a branch → `main` / `/(root)` 설정합니다.

## 데이터 출처
한국사회보장정보원 지자체복지서비스 API: https://www.data.go.kr/data/15108347/openapi.do
목록 endpoint: `https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations/LcgvWelfarelist`
상세 endpoint: `https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations/LcgvWelfaredetailed`

## 업데이트
GitHub Actions는 매주 자동 실행되며 수동 실행도 가능합니다. 자동 실행이 성공했는지는 Actions 실행 결과에서 확인해야 합니다. 자동 업데이트는 API가 제공하는 데이터 범위 내에서만 동작합니다.
