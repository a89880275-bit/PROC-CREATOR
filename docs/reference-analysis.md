# 참고 Pro*C 분석 및 후속 구현 경계

원본은 수정하지 않았으며 samples/에는 바이트 그대로 복사했다. 원본 주석은 CP949 계열이다.

- md_fdrpt_s5.pc: global.h, `exec sql include oravar;`, MAXROWCNT 1000. 입력 `GET(field, 0, variable)`에 S_TYPE1/2 사용. 출력 asciz 배열을 SELECT INTO로 채운 뒤 SQLCNT를 rowcnt로 보존. SQLCODE는 0/NOTFOUND/TOOMANY를 구분하며 초과 조회는 오류. `PUT(field, iy, variable[iy])`로 S_STRING1~8 반복 출력.
- md_opdls_u19.pc: MAXROWCNT 50. `tpgetlev()==0`이면 `TPRETURN_ERROR(BADXA,-1)`. S_PATNO/S_STRING1~3 입력은 레거시 규칙. SELECT INTO 뒤 EXEC SQL EXECUTE BEGIN, pc_kakao_send 호출, :IsErr := 할당, 예외 블록과 명시적 commit work가 있다. 이 COMMIT을 신규 XA 서비스에 그대로 적용하면 안 된다. 프로시저 예외 이후 성공 반환되는 부분도 그대로 복제하지 않는다.
- md_sanmo_u1.pc: MAXROWCNT 50, XA 확인, S_STRING1~5 레거시 입력. UPDATE의 날짜 입력은 TO_DATE 바인드 변환. SQLCODE 오류에 DBUP 사용. 명시적 COMMIT은 없다.
- 공통: applog(msg), memset, `(FBFR *)msg->data`, tprealloc(MAXBUFSIZE), Finit/Fsizeof, `MakeErrMsg(message,SVCNAME,errorKind,errorText)`, `TPRETURN_ERROR(message,code)`, `MakeMsg(message,messageCode,rowcnt)`, `TPRETURN(message,0)`.
- 이름 접두어 i/s와 실제 asciz 선언은 독립적이다. 숫자 및 NULL 처리에 대한 운영 헤더 정의 확인이 필요하다.

조회용 `app/templates/select.pc.j2`는 4단계에서 구현했습니다. 샘플의 정확한 서명을 유지하고 공식 Oracle 규칙의 NULL 지시 배열을 확장합니다. 상세 비교와 검증 한계는 `STEP4_TEST_REPORT.md`에 기록했습니다. 트랜잭션 템플릿 및 Delphi 생성은 후속 범위입니다. global.h/oravar·FML·SQLCODE/NOTFOUND/TOOMANY/SQLCNT·메시지 코드·asciz typedef·컴파일 옵션과 GET/PUT 내부 오류 반환은 TODO: 환경 확인 필요이며 실제 컴파일 성공을 주장하지 않습니다.
