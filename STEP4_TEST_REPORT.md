# STEP4 — 조회용 Tmax Pro*C 생성 구현·검증 보고

검증일: 2026-11-17 / Windows / Python 3.12 / Chrome.

**실제 Pro*C 컴파일 및 Oracle/Tmax 실행은 수행하지 않았습니다. 컴파일 성공으로 보고하지 않습니다. 생성물은 검증 전 운영 배포 불가입니다.**

## 1. 샘플을 실제로 읽고 확인한 구조

기준 파일: `samples/md_fdrpt_s5.pc`. CP949로 읽어 코드·주석을 분석했습니다. 원본 `E:\백업\proc\md_fdrpt_s5.pc`와 복사본의 SHA256이 동일합니다.

```text
0b20dbf0605bb3c0006f3db509a50b968a2de67e52b1d5b4d09e1797aa14617b
```

| 항목 | 샘플에서 확인 | 생성 결과 |
|---|---|---|
| include | `#include <global.h>`, `exec sql include oravar;` | 동일, 표준 memset 사용을 위해 string.h 추가 |
| 건수 정의 | `MAXROWCNT 1000` | 사용자가 설정한 MAXROWCNT, SQL에 ROWNUM을 추가하지 않음 |
| 함수 | `#if defined(__STDC__)` 및 구형 매개변수 선언 | 같은 조건부 함수 선언 형태 |
| 입력 | asciz10 / asciz20 스칼라, memset, `GET(field,0,variable)` | 저장한 변수명·전문 순서로 스칼라 선언/GET |
| 출력 | asciz10 / asciz20 `[MAXROWCNT]` | 검증된 asciz 계열의 같은 크기 배열 |
| SQL | 단일 SELECT, 여러 배열을 INTO 대상으로 사용 | 최종 SQL에 최상위 INTO 삽입 또는 기존 INTO 검증 |
| SQL 오류 | SQLCODE 0/NOTFOUND/TOOMANY 구분, DBSEL/SQLMSG | 같은 비교·MakeErrMsg·TPRETURN_ERROR 호출 |
| 초과 | TOOMANY → SF_B220 / MAXROWCNT / 오류 1 | 같은 처리에 SQLCNT 상한 방어 추가 |
| 건수 | `rowcnt = SQLCNT` | 동일 |
| 공통 로컬 | rowcnt/rowcnt1, iDaycnt/jj/ii/ix/iy, DataCnt | 매크로 의존 여부를 추측해 제거하지 않고 모두 보존 |
| 버퍼 | tprealloc → Finit, TUXALLOC/TUXINIT 오류 | 같은 순서·서명 |
| PUT | `for(iy=0; iy<rowcnt; iy++)`, `PUT(field,iy,array[iy])` | 같은 반복·인수 형식, 저장 전문 순서 유지 |
| 0건 | 반복 생략 후 SF_A220에 0을 전달하고 성공 종료 | 0건 전용 분기로 명시하되 같은 SF_A220 / 성공 0 사용 |
| 종료 | MakeMsg(SF_A220,rowcnt), TPRETURN(message,0) | 동일 |

샘플에 적힌 asciz 용량: 1, 10, 20, 30, 50, 100(asciz1h), 300(asciz3h), 500(asciz5h), 3000(asciz3k). 생성기는 요청 길이 이상인 가장 작은 확인된 선언을 선택합니다. 예: NUMBER(22)의 호스트 길이 64 → asciz1h. 접두어 i/d를 native int/double 선언으로 해석하지 않습니다.

`global.h`, `oravar`, FML 필드 사전은 제공되지 않았으므로 실제 typedef 크기, GET/PUT 내부 분기 및 반환 계약, SQLCNT/NOTFOUND/TOOMANY 값, SVCNAME과 메시지 코드 정의는 확인하지 못했습니다. 샘플의 묵시적 반환형을 포함한 구형 C 함수 선언 및 Declare Section 생략도 그대로 따르며 실제 컴파일 옵션 확인이 필요합니다. 입력 3~10개 및 출력 9~100개에 필요한 추가 필드 번호는 요구사항 규칙으로 생성하되 샘플에는 해당 번호 정의가 없음을 경고합니다.

## 2. 구현 동작

`Pro*C 생성` 탭에서 서비스 ID, MAXROWCNT, 파일명, UTF-8/CP949를 확인하고 미리보기를 생성합니다. 기본 파일명은 서비스 ID의 소문자 `.pc`입니다.

- 최종 SQL을 사용합니다. 문자열·주석·호스트 변수·괄호 깊이를 구분하고 최상위 SELECT/FROM/INTO를 찾습니다. 식, JOIN, WHERE, 서브쿼리, CASE, NVL, TO_CHAR의 본문을 임의로 재작성하지 않습니다.
- INTO가 없으면 SELECT 결과 순서에 대응하는 출력 호스트를 삽입합니다. 기존 INTO가 있으면 개수·이름·순서를 검증하고 중복 INTO를 만들지 않습니다. NULL 지시 변수만 빠졌다면 해당 호스트 토큰 뒤에 보강합니다.
- INTO를 포함한 SQL을 처음 붙여 넣은 경우에도 3단계 매핑 분석·확인 후 생성할 수 있습니다. 입력/출력에 동일한 호스트명을 공유하면 배열/스칼라 충돌이므로 차단합니다.
- INTO 대상은 SQL 결과 순서로 연결합니다. PUT 전문은 저장된 전문 순서로 연결합니다. 사용자가 PUT 순서를 바꾸어도 SQL 결과가 잘못된 변수로 들어가지 않게 두 순서를 분리합니다.
- 반복 입력 바인드는 GET 한 번만 생성합니다. 문자열·주석 속 `:name`은 선언 검사에 포함하지 않습니다. SQL NULL 지시 변수는 GET 입력으로 중복 계산하지 않습니다.
- WHERE/SELECT와 매핑의 개수·이름·식, 미선언 호스트, 미사용 보관 매핑, 미확정 자료형, 중복/고정 변수명, 배열 옵션, 전문 번호와 길이를 검사합니다.
- 조회 건수는 MAXROWCNT 배열과 SQLCNT로 처리합니다. 쿼리용 ROWNUM 래퍼는 만들지 않습니다.

### 샘플 외에 명시적으로 추가한 NULL/길이 처리

Oracle 공식 문서에서 확인한 지시 배열을 사용합니다. 모든 출력에 short 배열을 연결하며, -1은 NULL로 취급해 해당 문자열 요소를 0으로 채웁니다. 0보다 큰 값 또는 -2는 문자열 잘림으로 오류 반환합니다. 이 부분은 원본 샘플에 없는 표준 Pro*C 기반 확장이며 실제 헤더/컴파일러로 검증하지 않았습니다.

- NULL 출력 정책은 **빈 문자열**입니다. NULL과 빈 문자열의 업무적 구분은 보존하지 않습니다.
- 사용자 지정 NULL 지시 변수명은 보존하고 충돌을 검사합니다. 자동 이름은 `n_변수명`이며 필요하면 충돌 방지 접미어를 사용합니다.
- 입력 지시 변수는 명시적으로 설정한 경우에만 스칼라 short로 선언하고 0으로 초기화합니다. GET 필드 누락/NULL 전달 규칙은 헤더 확인이 필요합니다.
- DB/결과 문자열 길이보다 호스트가 짧거나 NUMBER 정밀도를 수용하지 못하면 차단합니다. 숫자 이름 접두어와 선언 타입은 독립적입니다.
- 확인된 asciz 최대 용량 3000 초과, 지원되지 않는 native 호스트 타입, 예상 배열 메모리 16MiB 초과는 차단합니다. 16MiB는 생성기의 자체 보수적 상한이며 실제 sizeof/스택 허용량은 아닙니다.

공식 근거: [Oracle Pro*C Host Arrays](https://docs.oracle.com/en/database/oracle/oracle-database/21/lnpcc/host-arrays.html)는 배열 SELECT INTO, 지시 배열, sqlca.sqlerrd[2]의 행 수 및 SELECT_ERROR 옵션에 따른 초과 처리를 설명합니다. [Oracle Pro*C Datatypes and Host Variables](https://docs.oracle.com/en/database/oracle/oracle-database/19/lnpcc/datatypes-and-host-variables.html)는 지시 변수 문법과 NULL/잘림 값을 설명합니다. 프로젝트 SQLCNT 매크로가 그 표준 카운터에 어떻게 대응하는지는 헤더 확인 사항입니다.

## 3. 저장·다운로드 및 마이그레이션

- 생성 전 오류/경고, 전체 소스 미리보기, 복사, 생성 결과 저장, `.pc` 다운로드 및 읽기 전용 생성 이력 조회를 구현했습니다.
- 같은 서비스·파일명의 이력이 있으면 확인을 요구하고 새 이력으로 보관합니다. 과거 소스를 덮어 지우지 않습니다. 실제 로컬 파일 덮어쓰기/저장 위치는 브라우저 설정·저장 창이 처리합니다.
- 서버는 사용자가 입력한 경로로 파일을 쓰지 않습니다. 파일명에서 경로 구분자, 경로 순회 및 Windows 예약 이름을 차단합니다.
- SQLite v3는 매핑 메타데이터를 추가하며 기존 변수명/SQL/순서 및 버전 이력을 보존합니다. v4는 proc_generations 및 인덱스를 추가합니다. 기존 테이블/열을 삭제하지 않습니다.
- 생성 소스, 정확한 사용 서비스 스냅샷, 기준 서비스 버전, 파일명/인코딩, SHA256, 템플릿 ID·버전(1.0.0)·해시, 설정·경고를 저장합니다. 템플릿 원문도 templates에 보관하고 generated_files/audit_log와 연계합니다.
- 편집 중인 정의도 생성 이력에는 실제 사용한 스냅샷으로 기록합니다. 서비스 정의 자체의 저장은 상단 ‘저장’ 버튼을 사용합니다.
- 미리보기 이후 소스에 영향을 주는 정의가 바뀌면 재생성을 요구합니다. 운영 Tmax 등록/배포나 Oracle 데이터 변경은 수행하지 않습니다.

## 4. 테스트 결과

실행 명령:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
node --check app/static/app.js
node --check app/static/mapping_ui.js
node --check app/static/proc_ui.js
# 8765 서버를 중지한 상태에서, 실제 관리 DB와 분리된 임시 DB로 수행
.\.venv\Scripts\python.exe tests/browser_smoke.py
```

**자동화 239개 통과**, 의존성 TestClient/httpx 폐기 예정 경고 1개. 기존 테이블 사전·Excel·CRUD·JOIN·저장 회귀를 포함합니다. 4단계 전용 검사는 `tests/test_proc_generator.py`의 28개 케이스입니다.

| 요청 테스트 | 확인 내용 | 검증 수준 |
|---|---|---|
| 1. GET 1개 | 실제 생성 GET 1회, 저장 이름 사용 | 코드 생성 검사 |
| 2. GET 10개 | S_TYPE1~10 및 반복 바인드 중복 배제 | 코드 생성 검사 |
| 3. GET 11개 | 요청 검증에서 차단, 파일 이력 미생성 | API 검사 |
| 4. PUT 1개 | 배열 선언·INTO·PUT | 코드 생성 검사 |
| 5. PUT 100개 | S_STRING1~100, 동일 MAXROWCNT 배열 | 코드 생성 검사 |
| 6. PUT 101개 | 요청 검증에서 차단 | API 검사 |
| 7. 결과 0건 | rowcnt==0, SF_A220/0 및 성공 반환 분기 | 구조 검사, 실제 DB 0건 실행 미검증 |
| 8. 다중 행 | SQLCNT, rowcnt 경계, iy 반복·배열 인덱스·초과 처리 | 구조 검사, 실제 다중 행 실행 미검증 |
| 9. DATE/NUMBER | TO_CHAR/TO_DATE, NUMBER(22) asciz1h, int 과대 범위 차단 | 코드·검증 검사 |
| 10. JOIN/서브쿼리 | LEFT JOIN, EXISTS, CASE/NVL 식 보존, 최상위 INTO만 삽입 | 토큰·코드 검사 |
| 11. 수동 SQL | 조건/리터럴/주석 보존, 변경 후 재동기화 요구 | 코드·API 검사 |
| 12. 수동 변수명 | GET 이름 유지, PUT 수동 순서와 INTO 순서 분리 | 코드 검사 |
| 13. 미선언 호스트 | SQL/GET 이름 차이 검출 | 생성 차단 검사 |
| 14. 샘플 비교 | include/define/선언 분기/GET/PUT/오류/종료 정규화 비교 | 원본 파일 직접 비교 |

추가 검사: NULL/잘림 분기, 기존 INTO 보강, INTO SQL 처음부터 동기화, COUNT INTO 별칭 없는 경우, 입력/출력 동일 호스트 거부, 잘못된 파일명·길이·미사용 매핑, 스냅샷/템플릿 저장, 중복 파일명 확인, 과거 이력 불변, 저장 전·미리보기 변경 차단, CP949 및 SHA256 일치.

Chrome에서 다음 전체 흐름을 확인했습니다.

테이블 선택 → SQL 생성 → GET/PUT 분리 화면 → 수동 이름/순서 수정 → SQL 계산식 타입 확인 → 매핑 동기화 → 저장/재조회 → 미사용 보관/선택 삭제 → Pro*C 검사·미리보기 → 생성 결과 저장 → 같은 파일명 확인 → 실제 `.pc` 다운로드. 다운로드 파일과 미리보기 내용 일치를 확인했고 JavaScript 오류가 없었습니다. 브라우저 테스트 데이터는 임시 DB에만 생성했습니다.

## 5. 구현 파일

| 영역 | 파일 |
|---|---|
| 매핑 계약/기존 데이터 확장 | app/models.py, app/db.py, app/services/mapping_migration.py |
| SQL 토큰 분석/동기화 | app/services/sql_analyzer.py, mapping_sync.py, mapping_service.py, app/mapping_api.py |
| 3단계 화면 | app/static/mapping_ui.js, index.html, app.js, style.css |
| 조회 생성/안전 검사 | app/services/proc_generator.py |
| 템플릿/환경 의존성 | app/templates/select.pc.j2, environment.json |
| 생성 이력/파일 API | app/services/proc_storage.py, app/proc_api.py, app/main.py |
| 4단계 화면 | app/static/proc_ui.js |
| 자동화 | tests/test_mapping_sync.py, test_proc_generator.py, 기존 회귀 테스트, browser_smoke.py |

## 6. 미구현·미검증 사항

- **실제 Pro*C 전처리·C 컴파일·링크·Tmax 실행·Oracle 실행 미검증.** 운영 환경의 헤더/라이브러리/필드 사전·옵션이 필요합니다.
- GET/PUT 매크로 내부의 입력 누락·형식 오류·출력 오류를 독립적으로 분류하는 코드는 구현하지 않았습니다. 샘플의 직접 호출을 유지하고 내부 처리를 확인 필요로 표시합니다. 헤더 없이 임의 반환값 검사를 만들지 않았습니다.
- 확인된 asciz 계열만 선언합니다. native int/double/사용자 타입·LOB 로케이터 등은 지원하지 않습니다. BYTE/CHAR 및 다중 바이트 길이·NLS·실제 asciz typedef/스택 한도는 운영 검증 대상입니다.
- WITH, 집합 연산, 확장 SELECT 구문, FOR UPDATE, 다중 SQL/PLSQL 등 안전한 INTO 변환을 보장하지 못하는 구조는 차단합니다. 복잡한 함수 결과의 타입은 사용자 확정값을 사용하며 Oracle 의미 검증을 대신하지 않습니다.
- DATE 출력은 TO_CHAR, DATE 입력은 TO_DATE/TO_TIMESTAMP를 요구합니다. 사용자 SQL의 변환을 임의로 삽입하지 않습니다.
- 샘플 기반의 단일 배열 SELECT 방식이며, 초과분을 여러 배치로 가져오는 cursor FETCH 기능은 없습니다. 초과 오류는 SELECT_ERROR=YES 및 프로젝트 TOOMANY 정의 확인이 필요합니다.
- 트랜잭션용 Pro*C, Delphi 호출 코드, 운영 배포 기능은 이번 4단계 범위에 포함하지 않습니다.

실제 로컬 서버 확인: start.bat 기동 후 HTTP 200 및 새 매핑/생성 UI 모듈, 조회 미리보기 API 응답을 확인했습니다. 기존 업무 테이블/사전 변경 이력/Excel 업로드 데이터와 버전 이력은 적용 전 백업과 비교해 변경이 없었습니다. 실제 DB의 스키마는 1~4이며 외래키 오류가 없었습니다. 기존 서비스가 있는 경우의 이름·SQL·순서 보존은 별도 시드 데이터 마이그레이션 테스트로 검증했습니다.

화면 경합 회귀 검사: 저장 요청과 미리보기 요청을 각각 지연시킨 Chrome 검사에서 저장 중 생성 버튼 비활성화, 설정 변경 후 오래된 미리보기 응답 폐기, 재생성·저장·다운로드 정상 흐름을 확인했습니다.
