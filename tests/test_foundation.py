from pathlib import Path
import sqlite3
from xml.sax.saxutils import escape
from zipfile import ZipFile

from fastapi.testclient import TestClient

from dashboard.api import create_app
from dashboard.foundation import import_workbook, prepare_records, read_workbook, records, summary
from test_dashboard import fixture


def workbook(path: Path, amount=12000000):
    """Small real OOXML fixture: examples, missing keys, date and formula cache."""
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    sheets = {
        '03_거래처': {4: {'A': '★ 거래처 코드', 'B': '★ 거래처명', 'C': '★ 구분'},
                    6: {'A': 'C-001', 'B': '예시', 'C': '고객사'},
                    7: {'A': 'C-001', 'B': '실제 고객', 'C': '고객사'},
                    8: {'B': '코드 누락 고객', 'C': '공급사'}},
        '21_견적이력': {4: {'A': '★ 견적번호', 'B': '★ 견적일', 'K': '★ 견적 금액(원)'},
                      5: {'B': 'YYYY-MM-DD'}, 6: {'A': 'EXAMPLE', 'K': 999},
                      7: {'A': 'Q1', 'B': 46023, 'K': amount},
                      8: {'M': '=IF(A8="","",1)'}},
        '22_RAG문서': {4: {'A': '★ 문서번호', 'B': '★ 문서명'},
                     7: {'A': 'RAG-01', 'B': '작업표준서'}},
        '17_견적단가기준': {4: {'A': '★ 단가 유형', 'B': '★ 대상 코드', 'D': '★ 단가', 'E': '단위', 'F': '시작일'},
                        7: {'A': '자재', 'B': 'SUS304', 'D': 0, 'E': '원/kg', 'F': '2026-01-01'},
                        8: {'A': '자재', 'B': 'SUS316', 'D': 4000, 'E': '원/kg', 'F': '2026-01-01'}},
    }
    with ZipFile(path, 'w') as z:
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+''.join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i,name in enumerate(sheets,1))+'</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships>'+''.join(f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1))+'</Relationships>')
        z.writestr('xl/styles.xml', f'<styleSheet xmlns="{ns}"><numFmts><numFmt numFmtId="176" formatCode="yyyy-mm-dd"/></numFmts><fills><fill><patternFill/></fill><fill><patternFill><fgColor rgb="FFDDEBF7"/></patternFill></fill></fills><cellXfs><xf fillId="0" numFmtId="0"/><xf fillId="1" numFmtId="0"/><xf fillId="0" numFmtId="176"/></cellXfs></styleSheet>')
        for i,(name,rows) in enumerate(sheets.items(),1):
            xml = ''
            for row,values in rows.items():
                cells = ''
                for col,value in values.items():
                    style = 2 if name=='21_견적이력' and col=='B' and row==7 else 1 if name=='22_RAG문서' and row==7 else 0
                    attrs = f'r="{col}{row}" s="{style}"'
                    if isinstance(value, str) and value.startswith('='):
                        cells += f'<c {attrs}><f>{escape(value[1:])}</f><v/></c>'
                    elif isinstance(value, str):
                        cells += f'<c {attrs} t="inlineStr"><is><t>{escape(value)}</t></is></c>'
                    else:
                        cells += f'<c {attrs}><v>{value}</v></c>'
                xml += f'<row r="{row}">{cells}</row>'
            z.writestr(f'xl/worksheets/sheet{i}.xml',f'<worksheet xmlns="{ns}"><sheetData>{xml}</sheetData></worksheet>')


def test_examples_formula_tails_missing_keys_dates_and_composite_keys(tmp_path):
    path=tmp_path/'input.xlsx'
    workbook(path)
    rows,_=prepare_records(read_workbook(path))
    assert len(rows)==6
    assert all(r['source_row']!=6 for r in rows)
    quote=next(r for r in rows if r['sheet']=='21_견적이력')
    assert quote['values']['B']=='2026-01-01'
    customer=next(r for r in rows if r['sheet']=='03_거래처' and r['source_row']==8)
    assert any('거래처 코드' in i for i in customer['issues'])
    assert next(r for r in rows if r['sheet']=='22_RAG문서')['design']
    prices=[r for r in rows if r['sheet']=='17_견적단가기준']
    assert not any(r['issues'] for r in prices)
    assert prices[0]['values']['D']==0


def test_idempotent_import_version_history_and_source_snapshot(tmp_path):
    db=tmp_path/'db.sqlite3'; path=tmp_path/'input.xlsx'
    workbook(path)
    first=import_workbook(path,db)
    assert first['records']==6 and first['reused'] is False
    assert import_workbook(path,db)['reused'] is True
    assert summary(db)['records']==6
    workbook(path,amount=15000000)
    updated=import_workbook(path,db)
    assert updated['records']==6 and updated['analytics']['quote_source_total']==15000000
    with sqlite3.connect(db) as con:
        assert con.execute('SELECT count(*) FROM foundation_imports').fetchone()[0]==2
        assert con.execute('SELECT sum(active) FROM foundation_imports').fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM foundation_records').fetchone()[0]==12
    assert len(list((tmp_path/'foundation-sources').glob('*.xlsx')))==2


def test_restart_keeps_import_and_preserves_kpis(tmp_path):
    root=fixture(tmp_path); db=tmp_path/'db.sqlite3'; path=tmp_path/'input.xlsx'
    workbook(path)
    with TestClient(create_app(root,db)) as client:
        before=client.get('/api/dashboard/summary').json()['kpis']
        import_workbook(path,db)
        info=client.get('/api/foundation/summary').json()
        assert info['quote_overlap_rows']==1
        assert client.get('/api/foundation/records?sheet=03_거래처&issues_only=true').json()['total']==2
        assert client.get('/api/foundation/records?q=실제%20고객').json()['total']==1
        assert client.get('/api/foundation/records?limit=0').status_code==422
        assert client.get('/api/foundation/source').content==path.read_bytes()
        assert client.get('/api/dashboard/summary').json()['kpis']==before
    with TestClient(create_app(root,db)) as client:
        assert client.get('/api/foundation/summary').json()['records']==6
        assert client.get('/api/dashboard/summary').json()['kpis']==before
        assert records(db,offset=5,limit=1)['total']==6
