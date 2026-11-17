"""Optional Windows browser integration check: python tests/browser_smoke.py.
Uses installed Chrome, temporary SQLite, and the supplied MDMEDORT.xlsx.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import os,sys,subprocess,time,urllib.request,re
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]

def run():
    with TemporaryDirectory(prefix='proc-browser-') as tmp:
        env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONPATH':os.pathsep.join([str(ROOT),*sys.path]),'PROC_MANAGER_DB':str(Path(tmp)/'browser.sqlite3')}
        with open(Path(tmp)/'server.log','w+',encoding='utf-8',errors='replace') as log:
            try:
                urllib.request.urlopen('http://127.0.0.1:8765/api/session',timeout=1)
            except OSError: pass
            else: raise RuntimeError('8765 포트를 사용하는 서버를 먼저 중지하세요. 테스트는 운영 DB를 사용하지 않습니다.')
            server=subprocess.Popen([sys._base_executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=log)
            try:
                for _ in range(60):
                    if server.poll() is not None: raise RuntimeError('테스트 서버 기동 실패')
                    try:
                        urllib.request.urlopen('http://127.0.0.1:8765/api/session',timeout=1);break
                    except OSError: time.sleep(.2)
                with sync_playwright() as p:
                    browser=p.chromium.launch(channel='chrome',headless=True)
                    page=browser.new_page(viewport={'width':1440,'height':1100})
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('dialog',lambda d:d.accept())
                    page.goto('http://127.0.0.1:8765')
                    expect(page.locator('#status')).to_contain_text('로컬 모드')
                    page.locator('[data-tab="dictionary"]').click()
                    manual_requests=[]
                    page.on('request',lambda r:manual_requests.append(r.url) if r.url.endswith('/api/dictionary/preview') else None)
                    page.get_by_text('수동 작성한 테이블 등록',exact=True).click()
                    page.locator('#dict-manual').click()
                    expect(page.locator('#status')).to_contain_text('수동 등록할 컬럼이 없습니다')
                    assert manual_requests==[]
                    page.locator('#dict-file').set_input_files(str(ROOT/'MDMEDORT.xlsx'))
                    page.locator('#dict-upload').click()
                    expect(page.locator('#dict-preview')).to_contain_text('MDMEDORT')
                    expect(page.locator('#dict-commit')).to_be_enabled()
                    # The old misleading manual registration action must keep the Excel preview.
                    page.locator('#dict-manual').click()
                    expect(page.locator('#status')).to_contain_text('선택 항목 사전에 등록')
                    expect(page.locator('#dict-preview')).to_contain_text('MDMEDORT')
                    assert manual_requests==[]
                    checked=page.locator('.dict-change:checked').count()
                    page.locator('.dictionary-change details summary').first.click()
                    assert page.locator('.dict-change:checked').count()==checked
                    page.locator('#dict-check-none').click()
                    expect(page.locator('#dict-commit')).to_be_disabled()
                    expect(page.locator('#dict-selection-status')).to_contain_text('선택 0건')
                    page.locator('#dict-check-all').click()
                    page.locator('#dict-commit').click()
                    expect(page.locator('#dict-results')).to_contain_text('188컬럼')
                    assert page.locator('[data-dict-detail="0"]').bounding_box()['height']<=34
                    expect(page.locator('[data-dict-detail="0"]')).to_contain_text(' / ')
                    # Uploading the registered workbook again is a no-op, not a missing-selection error.
                    page.locator('#dict-upload').click()
                    expect(page.locator('#dict-selection-status')).to_contain_text('이미 등록된 동일한 내용')
                    expect(page.locator('#dict-commit')).to_be_disabled()
                    expect(page.locator('#dict-commit')).to_have_text('변경 없음 · 이미 등록됨')
                    expect(page.locator('#status')).to_contain_text('이미 등록된 동일한 내용')
                    editor=page.locator('.dictionary-editor').bounding_box()
                    table_list=page.locator('.dictionary-list-panel').bounding_box()
                    info=page.locator('.dictionary-info-panel').bounding_box()
                    assert editor['x']+editor['width']<=table_list['x']
                    assert table_list['x']+table_list['width']<=info['x']
                    assert abs(table_list['y']-info['y'])<2
                    assert abs(editor['y']-table_list['y'])<2
                    assert page.locator('#dict-results').bounding_box()['height']>500
                    page.locator('.dictionary-editor').evaluate('(el)=>el.scrollTop=el.scrollHeight')
                    expect(page.locator('[data-dict-detail="0"]')).to_be_in_viewport()
                    assert page.locator('.dictionary-list-panel').bounding_box()['y']==table_list['y']
                    page.locator('.dictionary-editor').evaluate('(el)=>el.scrollTop=0')
                    out=ROOT/'test-results';out.mkdir(exist_ok=True)
                    page.screenshot(path=str(out/'dictionary-layout.png'),full_page=True)
                    page.locator('[data-dict-detail="0"]').click()
                    expect(page.locator('.dictionary-info-panel #dict-use')).to_be_in_viewport()
                    expect(page.locator('.dictionary-info-panel #dict-table-history')).to_be_in_viewport()
                    expect(page.locator('.dictionary-info-panel')).to_contain_text('PATNO')
                    page.locator('#dict-detail').evaluate('(el)=>el.scrollTop=el.scrollHeight')
                    expect(page.locator('[data-dict-detail="0"]')).to_be_in_viewport()
                    page.locator('#dict-detail').evaluate('(el)=>el.scrollTop=0')
                    page.locator('#dict-table-history').click()
                    expect(page.locator('#dict-history')).to_contain_text('v1')
                    page.screenshot(path=str(out/'dictionary-three-panels.png'),full_page=True)
                    page.locator('#dict-use').click()
                    expect(page.locator('#sql')).to_be_visible()
                    left=page.locator('.sql-column-panel').bounding_box()
                    right=page.locator('.sql-result-panel').bounding_box()
                    assert left['x']+left['width']<=right['x']
                    assert abs(left['y']-right['y'])<2
                    assert page.locator('#pick-pool').bounding_box()['height']>400
                    y=page.evaluate('window.scrollY')
                    page.locator('#pick-pool').evaluate('(el)=>el.scrollTop=el.scrollHeight')
                    expect(page.locator('#generate')).to_be_in_viewport()
                    expect(page.locator('#final_sql')).to_be_in_viewport()
                    assert page.evaluate('window.scrollY')==y
                    page.locator('#pick-pool').evaluate('(el)=>el.scrollTop=0')
                    page.locator('#generate').click()
                    expect(page.locator('#sql-status')).to_contain_text('조회 컬럼을 선택')
                    expect(page.locator('#sql-status')).to_have_class('error')
                    expect(page.locator('#generate')).to_be_enabled()
                    page.locator('[data-pick="selected"][data-column="PATNO"]').click()
                    page.locator('[data-pick="selected"][data-column="ORDDATE"]').click()
                    page.locator('[data-pick="where"][data-column="PATNO"]').click()
                    page.locator('[data-pick="order"][data-column="ORDDATE"]').click()
                    # Drag and drop is an alternative to the tested buttons.
                    page.locator('.pick-column[data-column="ORDSEQNO"]').drag_to(page.locator('[data-target="selected"]'))
                    expect(page.locator('#pick-selected')).to_contain_text('ORDSEQNO')
                    # Generate directly after dictionary import, without entering a service ID.
                    page.locator('#generate').click()
                    expect(page.locator('#final_sql')).to_have_value(re.compile('FROM MDMEDORT'))
                    expect(page.locator('#sql-status')).to_contain_text('SQL 생성 완료')
                    expect(page.locator('#generate')).to_be_enabled()
                    page.locator('[data-tab="basic"]').click()
                    page.locator('#service_id').fill('BROWSER_S1')
                    page.locator('#name').fill('브라우저 검증 서비스')
                    page.locator('#table_alias').fill('a')
                    page.locator('[data-tab="sql"]').click()
                    page.locator('#generate').click()
                    expect(page.locator('#final_sql')).to_have_value(re.compile('FROM MDMEDORT a'))
                    expect(page.locator('#final_sql')).to_have_value(re.compile(':sPatno'))
                    expect(page.locator('#final_sql')).to_have_value(re.compile('ORDER BY a.ORDDATE'))
                    page.locator('[data-tab="mapping"]').click()
                    first=page.locator('#mapping-rows .variable_name').first
                    first.fill('sManualPatno');first.press('Tab')
                    page.locator('[data-tab="sql"]').click()
                    custom=page.locator('#final_sql').input_value().replace(':sPatno',':sManualPatno')+'\n-- 수동 수정 보존'
                    page.locator('#final_sql').fill(custom)
                    page.locator('#save').click()
                    expect(page.locator('#status')).to_contain_text('저장 완료')
                    page.reload();expect(page.locator('#status')).to_contain_text('로컬 모드')
                    page.locator('[data-id="BROWSER_S1"]').click()
                    expect(page.locator('#status')).to_contain_text('불러왔습니다')
                    page.locator('[data-tab="sql"]').click()
                    expect(page.locator('#final_sql')).to_have_value(custom)
                    expect(page.locator('#pick-selected')).to_contain_text('ORDSEQNO')
                    expect(page.locator('#conditions')).to_contain_text('PATNO')
                    page.locator('[data-tab="mapping"]').click()
                    expect(page.locator('#mapping-rows .variable_name').first).to_have_value('sManualPatno')
                    # PK defaults are proposed only for an empty WHERE list.
                    page.locator('[data-tab="sql"]').click()
                    page.locator('[data-remove-condition]').click()
                    page.locator('#operation').select_option('UPDATE')
                    assert page.locator('#conditions .condition').count()==3
                    out=ROOT/'test-results';out.mkdir(exist_ok=True)
                    page.screenshot(path=str(out/'sql-builder.png'),full_page=True)
                    page.set_viewport_size({'width':1366,'height':768})
                    expect(page.locator('#generate')).to_be_in_viewport()
                    expect(page.locator('#final_sql')).to_be_in_viewport()
                    page.screenshot(path=str(out/'sql-builder-desktop.png'),full_page=True)
                    page.set_viewport_size({'width':800,'height':900})
                    expect(page.locator('#generate')).to_be_visible()
                    page.screenshot(path=str(out/'sql-builder-narrow.png'),full_page=True)
                    # Join UI integration uses a second table only in this temporary test DB.
                    page.set_viewport_size({'width':1440,'height':1100})
                    page.evaluate("""async()=>{
                      const columns=[{name:'PATNO',length:8,nullable:false,primary_key:true},{name:'PATNAME',length:40},{name:'BIRTHDATE',db_type:'DATE',length:19}];
                      const p=await api('/dictionary/preview','POST',{tables:[{table_name:'APPATBAT',comment:'테스트 환자마스터',columns}]});
                      await api('/dictionary/commit','POST',{import_id:p.import_id,selections:p.tables.map(e=>({owner:e.table.owner,table_name:e.table.table_name,keys:e.changes.map(c=>c.key)}))});
                    }""")
                    page.locator('#new').click()
                    page.locator('[data-tab="sql"]').click()
                    page.locator('#sql-main-table').select_option('|MDMEDORT')
                    page.locator('#sql-join-table').select_option('|APPATBAT')
                    expect(page.locator('#sql-join-settings')).to_be_visible()
                    expect(page.locator('#sql-join-conditions .left_column')).to_have_value('PATNO')
                    expect(page.locator('#sql-join-conditions .right_column')).to_have_value('PATNO')
                    page.locator('#sql-join-type').select_option('LEFT')
                    page.locator('[data-pick="selected"][data-column="PATNO"]').click()
                    page.locator('[data-pick="where"][data-column="PATNO"]').click()
                    page.locator('#sql-column-source').select_option('join')
                    assert page.locator('#pick-pool .pick-column').count()==3
                    for column in ['b.PATNO','b.PATNAME','b.BIRTHDATE']:
                        page.locator('[data-pick="selected"][data-column="'+column+'"]').click()
                    page.locator('[data-pick="where"][data-column="b.PATNAME"]').click()
                    page.locator('[data-pick="order"][data-column="b.PATNAME"]').click()
                    page.locator('#generate').click()
                    expect(page.locator('#final_sql')).to_have_value(re.compile('LEFT JOIN APPATBAT b ON a.PATNO = b.PATNO'))
                    expect(page.locator('#final_sql')).to_have_value(re.compile('b.PATNO AS b_PATNO'))
                    expect(page.locator('#final_sql')).to_have_value(re.compile('ORDER BY b.PATNAME'))
                    assert page.locator('#operation option').filter(has_text='UPDATE').is_disabled()
                    page.locator('[data-tab="basic"]').click()
                    page.locator('#service_id').fill('JOIN_BROWSER_S1')
                    page.locator('#save').click()
                    expect(page.locator('#status')).to_contain_text('저장 완료')
                    page.reload();expect(page.locator('#status')).to_contain_text('로컬 모드')
                    page.locator('[data-id="JOIN_BROWSER_S1"]').click()
                    expect(page.locator('#status')).to_contain_text('불러왔습니다')
                    page.locator('[data-tab="sql"]').click()
                    expect(page.locator('#sql-join-table')).to_have_value('|APPATBAT')
                    expect(page.locator('#sql-join-type')).to_have_value('LEFT')
                    expect(page.locator('#pick-selected')).to_contain_text('b.PATNAME')
                    page.locator('#sql-join-alias').fill('p')
                    page.locator('#sql-join-alias').press('Tab')
                    expect(page.locator('#pick-selected')).to_contain_text('p.PATNAME')
                    page.locator('#generate').click()
                    expect(page.locator('#final_sql')).to_have_value(re.compile('LEFT JOIN APPATBAT p ON a.PATNO = p.PATNO'))
                    expect(page.locator('#final_sql')).to_have_value(re.compile('ORDER BY p.PATNAME'))
                    expect(page.locator('#generate')).to_be_enabled()
                    page.screenshot(path=str(out/'sql-join-builder.png'),full_page=True)
                    page.locator('#sql-join-table').select_option('')
                    expect(page.locator('#sql-join-settings')).to_be_hidden()
                    expect(page.locator('#pick-selected')).not_to_contain_text('p.PATNAME')
                    page.locator('#generate').click()
                    expect(page.locator('#final_sql')).not_to_have_value(re.compile(' JOIN '))
                    # Stage 3: split grids, manual edits, SQL diff, expression type confirmation.
                    page.locator('#new').click()
                    page.locator('[data-tab="sql"]').click()
                    page.locator('#sql-main-table').select_option('|MDMEDORT')
                    for column in ['PATNO','ORDSEQNO']:
                        page.locator('[data-pick="selected"][data-column="'+column+'"]').click()
                        page.locator('[data-pick="where"][data-column="'+column+'"]').click()
                    page.locator('#generate').click()
                    expect(page.locator('#final_sql')).to_have_value(re.compile('FROM MDMEDORT'))
                    page.locator('#open-mapping').click()
                    expect(page.locator('#mapping-rows tr[data-i]')).to_have_count(2)
                    expect(page.locator('#output-mapping-rows tr[data-i]')).to_have_count(2)
                    expect(page.locator('#sync-preview-panel')).to_contain_text('SQL / 전문 차이')
                    page.locator('#mapping-rows .variable_name').first.fill('sPatientUser')
                    page.locator('#mapping-rows .variable_name').first.press('Tab')
                    page.locator('#mapping-rows [data-move="1"]').first.click()
                    expect(page.locator('#mapping-rows .variable_name').first).to_have_value('iOrdseqno')
                    page.locator('[data-tab="basic"]').click()
                    page.locator('#service_id').fill('MAPPING_BROWSER_S1')
                    page.locator('#save').click();expect(page.locator('#status')).to_contain_text('저장 완료')
                    page.locator('[data-tab="sql"]').click()
                    edited="SELECT PATNO AS PATIENT_NO, ORDSEQNO AS SEQUENCE_NO, ORDSEQNO + 1 AS NEXT_SEQ, NVL(PATNO, ':sPatno') AS DISPLAY_TEXT FROM MDMEDORT WHERE PATNO = :sPatno OR PATNO = :sPatno AND ORDSEQNO = TO_NUMBER(:iOrdseqno) AND PATNO <> :sExtra"
                    page.locator('#final_sql').fill(edited)
                    page.locator('#open-mapping').click()
                    expect(page.locator('#sync-preview-panel')).to_contain_text('DISPLAY_TEXT')
                    expression_row=page.locator('[data-plan-index]').filter(has_text='DISPLAY_TEXT').first
                    expression_row.locator('.sync-source').select_option('PATNO')
                    expression_row.locator('.sync-type').select_option('VARCHAR2')
                    expression_row.locator('.sync-length').fill('20')
                    expression_row.locator('.sync-length').press('Tab')
                    page.locator('#sync-output-order').check()
                    page.locator('#sync-apply').click()
                    expect(page.locator('#mapping-notice')).to_contain_text('동기화했습니다')
                    expect(page.locator('#mapping-rows tr[data-i]')).to_have_count(3)
                    expect(page.locator('#output-mapping-rows tr[data-i]')).to_have_count(4)
                    assert page.evaluate("s.variables.find(v=>v.output_alias==='DISPLAY_TEXT').db_length")==20
                    expect(page.locator('#mapping-rows .variable_name').first).to_have_value('iOrdseqno')
                    expect(page.locator('#mapping-rows .variable_name').nth(1)).to_have_value('sPatientUser')
                    value=page.locator('#final_sql').input_value()
                    assert 'PATNO = :sPatientUser' in value and "':sPatno'" in value
                    page.locator('#save').click();expect(page.locator('#status')).to_contain_text('저장 완료')
                    page.reload();expect(page.locator('#status')).to_contain_text('로컬 모드')
                    page.locator('[data-id="MAPPING_BROWSER_S1"]').click()
                    expect(page.locator('#status')).to_contain_text('불러왔습니다')
                    page.locator('[data-tab="mapping"]').click()
                    expect(page.locator('#output-mapping-rows tr[data-i]')).to_have_count(4)
                    expect(page.locator('#mapping-rows .variable_name').nth(1)).to_have_value('sPatientUser')
                    page.screenshot(path=str(out/'tmax-mapping.png'),full_page=True)
                    page.locator('[data-tab="sql"]').click()
                    page.locator('#final_sql').fill('SELECT PATNO AS PATIENT_NO FROM MDMEDORT WHERE PATNO = :sPatientUser')
                    page.locator('#open-mapping').click()
                    expect(page.locator('[data-remove-id]')).to_have_count(5)
                    page.locator('#sync-apply').click()
                    expect(page.locator('#mapping-notice')).to_contain_text('동기화했습니다')
                    expect(page.locator('#mapping-rows')).to_contain_text('SQL 미사용')
                    page.locator('#sync-preview').click()
                    expect(page.locator('[data-remove-id]')).to_have_count(5)
                    for checkbox in page.locator('[data-remove-id]').all():checkbox.check()
                    page.locator('#sync-apply').click()
                    expect(page.locator('#mapping-notice')).to_contain_text('동기화했습니다')
                    expect(page.locator('#mapping-rows tr[data-i]')).to_have_count(1)
                    expect(page.locator('#output-mapping-rows tr[data-i]')).to_have_count(1)
                    # Stage 4: validated SELECT preview, immutable save, overwrite confirmation and download.
                    page.locator('#save').click();expect(page.locator('#status')).to_contain_text('저장 완료')
                    page.locator('[data-tab="proc"]').click()
                    page.locator('#proc-max-rows').fill('50')
                    page.locator('#proc-max-rows').press('Tab')
                    page.evaluate("""()=>{window._saveFetch=window.fetch;window.fetch=(url,options)=>String(url).startsWith('/api/services/')&&options?.method==='PUT'?new Promise(resolve=>setTimeout(resolve,800)).then(()=>window._saveFetch(url,options)):window._saveFetch(url,options);}""")
                    page.locator('#save').click()
                    expect(page.locator('#save')).to_be_disabled()
                    expect(page.locator('#proc-preview')).to_be_disabled()
                    expect(page.locator('#status')).to_contain_text('저장 완료')
                    page.evaluate('()=>{window.fetch=window._saveFetch;delete window._saveFetch;}')
                    page.locator('#proc-preview').click()
                    expect(page.locator('#proc-status')).to_contain_text('컴파일 미검증')
                    expect(page.locator('#proc-source')).to_have_value(re.compile('#define MAXROWCNT 50'))
                    expect(page.locator('#proc-source')).to_have_value(re.compile(r'GET \(S_TYPE1, 0, sPatientUser\);'))
                    expect(page.locator('#proc-source')).to_have_value(re.compile(r'PUT \(S_STRING1, iy, sPatnoOut\[iy\]\);'))
                    source=page.locator('#proc-source').input_value()
                    page.evaluate("""()=>{window._previewFetch=window.fetch;window.fetch=(url,options)=>String(url)==='/api/generate/preview'?new Promise(resolve=>setTimeout(resolve,800)).then(()=>window._previewFetch(url,options)):window._previewFetch(url,options);}""")
                    page.locator('#proc-preview').click()
                    page.locator('#proc-filename').fill('changed_preview.pc')
                    expect(page.locator('#proc-preview')).to_be_enabled()
                    expect(page.locator('#proc-save')).to_be_disabled()
                    expect(page.locator('#proc-status')).to_contain_text('미리보기를 다시 생성')
                    page.evaluate('()=>{window.fetch=window._previewFetch;delete window._previewFetch;}')
                    page.locator('#proc-filename').fill('mapping_browser_s1.pc')
                    page.locator('#proc-preview').click()
                    expect(page.locator('#proc-status')).to_contain_text('컴파일 미검증')
                    assert page.locator('#proc-source').input_value()==source
                    assert 'ROWNUM' not in source and ':sPatnoOut:n_sPatnoOut' in source
                    page.locator('#proc-save').click()
                    expect(page.locator('#proc-status')).to_contain_text('SQLite에 저장')
                    with page.expect_download() as info:page.locator('#proc-download').click()
                    downloaded=info.value
                    assert downloaded.suggested_filename=='mapping_browser_s1.pc'
                    downloaded.save_as(str(out/'mapping_browser_s1.pc'))
                    assert (out/'mapping_browser_s1.pc').read_text(encoding='utf-8')==source
                    page.locator('#proc-preview').click();expect(page.locator('#proc-status')).to_contain_text('컴파일 미검증')
                    page.locator('#proc-save').click();expect(page.locator('#proc-status')).to_contain_text('SQLite에 저장')
                    page.locator('#proc-history').click()
                    expect(page.locator('[data-generation]')).to_have_count(2)
                    page.screenshot(path=str(out/'proc-preview.png'),full_page=True)
                    page.locator('#proc-filename').fill('../bad.pc')
                    page.locator('#proc-preview').click()
                    expect(page.locator('#proc-status')).to_contain_text('생성이 차단')
                    expect(page.locator('#proc-download')).to_be_disabled()
                    assert errors==[],errors
                    browser.close()
                    print('PASS: Excel preview/commit, 188 columns, dictionary import, SELECT/WHERE/ORDER, drag/drop, host mapping, manual edits, save/reopen, PK defaults; no JS errors')
            except Exception:
                log.flush();log.seek(0);print(log.read());raise
            finally:
                server.terminate()
                try:server.wait(timeout=10)
                except subprocess.TimeoutExpired:server.kill();server.wait()
if __name__=='__main__':run()
