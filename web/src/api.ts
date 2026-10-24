export async function api<T>(path:string):Promise<T>{
  const response=await fetch(path)
  if(!response.ok) throw new Error((await response.json().catch(()=>null))?.detail||'데이터를 불러오지 못했습니다.')
  return response.json()
}
export const won=(value:number|null|undefined)=>value==null?'미확인':value>=100000000?`${(value/100000000).toFixed(1)}억원`:value>=10000?`${Math.round(value/10000).toLocaleString()}만원`:`${value.toLocaleString()}원`
