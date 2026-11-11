import {useEffect,useState} from 'react'
import {api} from './api'

type Sheet={name:string;kind:string;headers:Record<string,string>;row_count:number;issue_rows:number;design_rows:number}
export type FoundationSummary={source:{filename:string;imported_at:string;sha256:string}|null;sheets:Sheet[];records:number;reference_records:number;issue_rows:number;design_rows:number;quote_overlap_rows:number;rules:string[];analytics:{quote_rows:number;quote_amount_rows:number;quote_source_total:number;quote_date_from:string|null;quote_date_to:string|null;actual_cost_rows:number;customer_types:Record<string,number>;model_families:Record<string,number>;missing_fields:Record<string,number>;empty_sheets:string[]}}
type Cell={cell:string;value:unknown;raw:string|null;type:string;formula:string|null;design:boolean}
type Row={id:number;sheet:string;source_row:number;record_key:string;values:Record<string,unknown>;cells:Record<string,Cell>;design:number;issues:string[];status:string;overlap:{id:number;project_id:string}[]}
type Result={total:number;items:Row[]}
const display=(v:unknown)=>v===null||v===undefined||v===''?'—':typeof v==='boolean'?(v?'Y':'N'):String(v)

export function Foundation({summary,query,mode='browse',allowedSheets,revision=0}:{summary:FoundationSummary|null;query:string;mode?:'browse'|'database'|'issues'|'audit'|'rag';allowedSheets?:string[];revision?:number}){
 const options=summary?.sheets.filter(s=>mode==='rag'?s.name==='22_RAG문서':allowedSheets?allowedSheets.includes(s.name):true)||[]
 const [chosen,setChosen]=useState('')
 const sheet=options.some(s=>s.name===chosen)?chosen:options.find(s=>s.name==='03_거래처')?.name||options[0]?.name||''
 const [offset,setOffset]=useState(0),[result,setResult]=useState<Result|null>(null),[error,setError]=useState(''),[detail,setDetail]=useState<Row|null>(null)
 const [pending,setPending]=useState(false)
 useEffect(()=>{setOffset(0);setDetail(null)},[sheet,query,mode])
 useEffect(()=>{
  if(!summary?.source||!sheet)return
  let cancelled=false
  setPending(true);setError('')
  const timer=window.setTimeout(()=>{
   api<Result>(`/api/foundation/records?sheet=${encodeURIComponent(sheet)}&q=${encodeURIComponent(query)}&issues_only=${mode==='issues'}&offset=${offset}&limit=50`)
    .then(r=>{if(!cancelled)setResult(r)}).catch(e=>{if(!cancelled)setError(e.message)}).finally(()=>{if(!cancelled)setPending(false)})
  },150)
  return()=>{cancelled=true;window.clearTimeout(timer)}
 },[sheet,query,offset,mode,summary,revision])
 if(!summary)return <p role="status">기초데이터 적재현황을 불러오는 중입니다.</p>
 if(!summary.source)return <div className="empty">아직 적재한 기초데이터가 없습니다.</div>
 const current=options.find(s=>s.name===sheet)
 const columns=Object.entries(current?.headers||{})
 return <section className="foundation">
  <div className="foundation-heading"><div><h2>{mode==='database'?'기초데이터 DB 적재현황':mode==='issues'?'기초데이터 누락·중복 검사':mode==='audit'?'기초데이터 원본 대조':mode==='rag'?'RAG 문서 목록·공개 범위':'기초데이터 탐색'}</h2><p>{summary.source.filename}</p></div><a href="/api/foundation/source">적재 원본 다운로드</a></div>
  {mode==='database'?<><div className="foundation-stats">{[['입력 데이터',summary.records],['확인 필요 행',summary.issue_rows],['설계안 포함 행',summary.design_rows],['기존 견적번호 중복 후보',summary.quote_overlap_rows]].map(([label,value])=><div key={label}><span>{label}</span><strong>{Number(value).toLocaleString()}<small>건</small></strong></div>)}</div><p>적재 시각: {new Date(summary.source.imported_at).toLocaleString('ko-KR')} · 안내·진행현황·코드 목록 {summary.reference_records}행 별도 보존</p><div className="table-wrap sheet-summary"><table><thead><tr><th>시트</th><th>적재 행</th><th>확인 필요</th><th>설계안 포함</th></tr></thead><tbody>{summary.sheets.map(s=><tr key={s.name}><td><button className="text-button" onClick={()=>{setChosen(s.name);setOffset(0)}}>{s.name}</button></td><td>{s.row_count}</td><td>{s.issue_rows}</td><td>{s.design_rows}</td></tr>)}</tbody></table></div><ul className="import-rules">{summary.rules.map(rule=><li key={rule}>{rule}</li>)}</ul></>:null}
  {mode==='rag'?<p className="data-note">문서 등록정보와 공개 범위를 검색합니다. 문서 본문 추출·임베딩·AI 답변은 아직 연결하지 않았습니다.</p>:null}
  {allowedSheets?.includes('21_견적이력')?<p className="data-note">아래는 새 입력양식의 견적이력입니다. 기존 반응기 견적·수주 합계에 합산하지 않습니다. 번호가 같은 기존 견적은 상세에서 중복 후보로 표시합니다.</p>:null}
  <div className="foundation-controls"><label>시트 <select aria-label="기초데이터 시트" value={sheet} onChange={e=>{setChosen(e.target.value);setOffset(0);setDetail(null)}}>{options.map(s=><option key={s.name} value={s.name}>{s.name} ({mode==='issues'?s.issue_rows:s.row_count})</option>)}</select></label><span>{pending?'조회 중…':`${result?.total||0}건`}</span><div className="pagination"><button disabled={!offset||pending} onClick={()=>setOffset(Math.max(0,offset-50))}>이전</button><span>{Math.floor(offset/50)+1} / {Math.max(1,Math.ceil((result?.total||0)/50))}</span><button disabled={pending||offset+50>=(result?.total||0)} onClick={()=>setOffset(offset+50)}>다음</button></div></div>
  {error?<p role="alert" className="notice">{error}</p>:null}
  <p className="data-note">하늘색 설계안은 회사 확인 전 자료입니다. ‘입력값 적재’는 승인 완료를 뜻하지 않습니다. 행 번호를 누르면 원본 셀과 검수 항목을 확인할 수 있습니다.</p>
  {!pending&&!error?<div className="table-wrap foundation-table"><table><thead><tr><th>원본 행</th><th>상태</th>{columns.map(([col,label])=><th key={col}>{label}</th>)}</tr></thead><tbody>{result?.items.map(row=><tr key={row.id}><td><button className="text-button" onClick={()=>setDetail(row)}>{row.source_row}행 보기</button></td><td><span className={row.issues.length?'record-state needs-review':'record-state'}>{row.status}</span>{row.design?<small className="design-label">설계안 포함</small>:null}{row.overlap.length?<small className="design-label">기존 견적 중복 후보</small>:null}</td>{columns.map(([col])=><td key={col}><div className="cell-preview" title={display(row.values[col])}>{display(row.values[col])}</div></td>)}</tr>)}</tbody></table>{!result?.items.length?<div className="empty">조건에 맞는 데이터가 없습니다.</div>:null}</div>:null}
  {detail?<div className="overlay" onMouseDown={e=>e.target===e.currentTarget&&setDetail(null)}><aside className="drawer" role="dialog" aria-modal="true" aria-label="원본 셀 대조"><header><div><span>{detail.sheet} · {detail.source_row}행</span><h2>{detail.record_key}</h2><p>{detail.status}</p></div><button aria-label="대조 닫기" onClick={()=>setDetail(null)}>×</button></header><section><h3>검수 항목</h3>{detail.issues.length?<ul>{detail.issues.map((issue,i)=><li key={i}>{issue}</li>)}</ul>:<p>등록된 검증 규칙에서 오류가 발견되지 않았습니다.</p>}{detail.design?<p className="notice">원본에 하늘색 설계안 셀이 포함되어 있습니다. 회사 확인이 필요합니다.</p>:null}{detail.overlap.length?<p className="notice">기존 견적번호와 일치: {[...new Set(detail.overlap.map(q=>q.project_id))].join(', ')}. 동일 거래 여부를 검수하기 전 합산하지 않습니다.</p>:null}<h3>원본 셀과 적재값</h3><p>수식 결과는 엑셀에 저장된 계산값이며 재계산하지 않았습니다.</p><div className="table-wrap"><table><thead><tr><th>셀</th><th>항목</th><th>적재값</th><th>원본 값 / 수식</th></tr></thead><tbody>{Object.entries(detail.cells).map(([col,c])=><tr key={col}><td>{c.cell}</td><td>{current?.headers[col]||col}</td><td>{display(c.value)}</td><td>{c.formula!==null?<code>={c.formula}</code>:display(c.type==='s'||c.type==='inlineStr'?c.value:c.raw)}</td></tr>)}</tbody></table></div></section></aside></div>:null}
 </section>
}

export function FoundationAnalysis({summary}:{summary:FoundationSummary|null}){
 if(!summary?.source)return null
 const a=summary.analytics
 return <section className="foundation"><div className="foundation-heading"><div><h2>신규 기초데이터 분석</h2><p>{summary.source.filename} · 기존 반응기 분석과 별도 집계</p></div></div><div className="foundation-stats"><div><span>견적이력</span><strong>{a.quote_rows}<small>건</small></strong></div><div><span>실제 원가 입력</span><strong>{a.actual_cost_rows}<small>건</small></strong></div><div><span>미입력 업무 시트</span><strong>{a.empty_sheets.length}<small>개</small></strong></div><div><span>검수 필요</span><strong>{summary.issue_rows}<small>행</small></strong></div></div><p>견적일 범위: {a.quote_date_from||'미입력'} ~ {a.quote_date_to||'미입력'}. 금액 입력 {a.quote_amount_rows}건의 원본 합계 {a.quote_source_total.toLocaleString('ko-KR')}원. 중복 거래·수정 견적 검수 전 합계이며 매출·확정 견적 KPI로 사용하지 않습니다.</p><div className="grid2">{[['고객·공급사 구성',a.customer_types],['제품군 구성',a.model_families],['필수값 누락 항목',a.missing_fields]].map(([title,values])=><article className="panel" key={String(title)}><h3>{String(title)}</h3><div className="metric-list">{Object.entries(values as Record<string,number>).map(([label,value])=><div key={label}><span>{label}</span><b>{value}건</b></div>)}</div></article>)}<article className="panel"><h3>추가 확보가 필요한 데이터</h3><ul className="recommendations">{a.empty_sheets.map(name=><li key={name}>{name.replace(/^[^_]+_/, '')}: 입력 없음</li>)}</ul><p className="data-note">견적 원가 예측에는 실제 원가와 수주 결과가 연결된 표본을 더 확보해야 합니다. 입력 건수만으로 모델 준비도를 판단하지 않습니다.</p></article></div></section>
}
