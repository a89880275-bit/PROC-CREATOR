# Tmax 전문 매핑 데이터 계약

서비스 정의의 `variables` 목록과 SQLite `variables.mapping_meta_json`에 동일한 확장 메타데이터를 보관합니다. 기본 이름/타입/길이/역할은 기존 정규화 열에도 유지하고, 전문 순서는 field_mappings에 유지합니다.

| 필드 | 의미 |
|---|---|
| mapping_id | 저장/재조회에 안정적인 도메인 ID. SQLite variables.id는 저장 시 재생성될 수 있으므로 동기화는 mapping_id 사용 |
| role | IN=GET, OUT=PUT |
| field_name | 각 방향의 목록 순서에 따라 S_TYPE1~10 / S_STRING1~100으로 검증·배정 |
| variable_name | 실제 Pro*C 호스트 식별자. 이름 접두어와 호스트 선언 타입은 독립 |
| db_column | 메인 컬럼 또는 조인 별칭.컬럼. 여러 컬럼에 걸친 계산식은 빈 값일 수 있음 |
| column_comment | 원본 컬럼 설명 또는 확인된 계산식 설명 |
| db_type / db_length / precision / scale | DB 또는 계산 결과의 확인된 자료형/길이/정밀도/스케일 |
| nullable / date_format | NULL 가능 여부와 날짜 문자열 변환 포맷 |
| host_type / host_length | 실제 선언 타입 요청과 최소 문자 용량. 현재 조회 생성기는 확인된 asciz로 해석하며 실제 sizeof는 환경 검증 필요 |
| sql_bind_name | IN에 대응하는 최종 SQL 바인드 이름. 수동 이름 변경 뒤 확인 반영으로 정합화 |
| output_alias | SELECT 결과 별칭. 기존 INTO에 별칭 없는 식은 INTO 호스트를 논리 식별자로 사용 가능 |
| source_expression | SQL 결과 식(AS 별칭 제외) 또는 입력 바인드 식. Oracle 실행이나 재귀 템플릿 평가를 하지 않음 |
| source_position | SQL에서 발견된 방향별 위치. Tmax 전문 순서와 다를 수 있음 |
| array / null_indicator | OUT 배열 및 사용자 지정 NULL 지시 변수명 |
| is_manual / order_manual | 수동 필드 수정과 전문 순서 수정 여부 |
| mapping_status | auto=자동 발견, confirmed=사용자 확정, unmapped=추가 확인 필요 |
| is_active | 최종 SQL에서 사용 여부. 빠진 기존 매핑은 기본 false로 보관, 임의 삭제하지 않음 |

목록 내 상대 순서가 전문 순서입니다. SELECT/WHERE에 등장하는 순서로 기존 목록을 자동 재정렬하지 않습니다. 출력 재정렬을 명시적으로 선택한 경우에만 SELECT 순서로 배정하며, SQL INTO 연결은 source_expression/별칭을 기준으로 별도로 정렬합니다.

동일 SQL 바인드가 반복되어도 입력 한 개입니다. 같은 DB 컬럼이라도 SQL 바인드 이름이 서로 다르면 별도 입력일 수 있습니다. 입력·출력의 전체 호스트 식별자는 유일해야 합니다. 새 출력의 기본 이름에는 Out을 붙이고 수동 수정값은 보존합니다.

미리보기는 입력 정의의 SHA256 지문을 반환합니다. 반영 시 서버가 다시 분석해 지문, 삭제 선택, 타입/길이, 이름 충돌, 개수 제한을 검증합니다. 수동 변수명 유지 때문에 SQL 바인드를 바꾸는 경우도 사용자 확인 후 실제 바인드 토큰만 변경합니다. 리터럴/주석/NULL 지시 변수 이름은 치환하지 않습니다.

단일 SQL의 INTO/바인드 및 SELECT 결과 분석은 토큰 기반 정적 분석이며 Oracle 의미 분석·실행·컴파일이 아닙니다. 불명확한 계산식은 타입을 사용자가 확인해야 하고, 변환을 보장할 수 없는 SQL 구조는 차단합니다.

v3 마이그레이션은 mapping_meta_json 열을 추가하고 기존 서비스의 안정 ID·설명·타입 속성을 보강합니다. 기존 변수명·호스트 선언·SQL·전문 순서·서비스 버전 번호와 버전 이력 원문을 바꾸지 않습니다. v4 생성 이력은 사용한 서비스 스냅샷과 템플릿/소스를 별도로 기록합니다.
