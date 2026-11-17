# 3단계 Tmax 전문/Pro*C 변수 매핑 검증 보고

- GET/PUT 분리 화면, 순서·설명·DB/결과 자료형·호스트 타입/길이·수동 여부·상태 표시 구현.
- VARCHAR2/CHAR/DATE=s, NUMBER 정수=i, 소수=d. 신규 출력은 Out 접미어. 접두어는 실제 선언과 독립적이며 NUMBER(22)는 기본 asciz 문자열 길이 64를 사용.
- 최종 SQL 토큰 분석: 문자열/주석/Oracle q 문자열/PLSQL := 구분. 동일 바인드는 한 GET만 생성. SELECT 별칭·집계·기본 숫자 계산식 분석. 확정 불가능한 식은 타입/정밀도/길이를 사용자 확인 후 반영.
- 신규/변경/삭제 후보 미리보기, 지문 비교 후 확인 반영. 수동 이름·호스트 선언·전문 순서 유지. SQL에서 빠진 매핑은 기본 보관·미사용 상태로 표시하고 명시적 체크만 삭제. 출력 순서 재배정도 별도 선택.
- 수동 변수명과 SQL 바인드가 다르면 확인 반영 시 바인드 토큰만 정합화하며 리터럴·주석은 변경하지 않음.
- SQLite v3: variables.mapping_meta_json 추가, 서비스 스냅샷 확장, 기존 이름/SQL/순서·버전 이력 보존. 이전 버전 스냅샷은 원본 유지.
- 자동화 210개 통과(기존 75개 포함). GET 1~10 및 PUT 1~100 각 경계, 11/101 차단, 중복/충돌, 편집 SQL 동기화, 수동 이름·순서, 계산식 확인, 저장/재열기, v2→v3 마이그레이션 검증.
- Chrome 임시 DB에서 테이블 선택→SQL 생성→GET/PUT→수동 이름/순서 변경→SQL 편집/계산식 확인→반영→저장/재조회→미사용 보관/선택 삭제 전체 확인. JS 오류 없음.
- 불완전 SQL, 다중 SQL, PL/SQL 실행문, 집합 연산의 자동 동기화는 차단. CTE/출처 불명·일부 함수는 자동 의미 분석을 주장하지 않고 사용자 타입 확인을 요구. Oracle 실행/Pro*C 컴파일 미검증.

주요 파일: app/services/sql_analyzer.py, mapping_sync.py, mapping_migration.py, app/mapping_api.py, app/static/mapping_ui.js, app/models.py, app/db.py, tests/test_mapping_sync.py, tests/browser_smoke.py.

4단계 연계 과정에서 기존 INTO 및 NULL 지시 변수 분석을 확장했습니다. 최신 전체 검증 결과는 STEP4_TEST_REPORT.md의 239개 통과 결과를 참고하세요. 210개는 3단계 완료 시점의 검증 수입니다.
