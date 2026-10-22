"""Collect local-government welfare services using the approved official API.
The API key must be provided as WELFARE_API_KEY (GitHub Actions secret).
This is a bounded discovery sync, not a guarantee of every local program.
"""
import json, os, urllib.parse, urllib.request, xml.etree.ElementTree as ET, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'data'/'policies.json'
BASE='https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations'
LIST=BASE+'/LcgvWelfarelist'; DETAIL=BASE+'/LcgvWelfaredetailed'
KEY=os.environ.get('WELFARE_API_KEY','').strip()
if not KEY: raise SystemExit('WELFARE_API_KEY secret is missing. Add it in GitHub Settings > Secrets and variables > Actions.')
# The API requires search terms in practical use. Multiple topic/search combinations broaden coverage.
QUERIES=[('주거','040'),('생활지원','030'),('돌봄','120'),('건강','010'),('일자리','050'),('안전','070'),('교육','100'),('문화','060'),('법률','140'),('금융','130')]
def txt(node,names):
    for name in names:
        for el in node.iter():
            if el.tag.split('}')[-1]==name and el.text and el.text.strip(): return el.text.strip()
    return ''
def request(url, params):
    full=url+'?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(full,headers={'User-Agent':'welfare-gap-helper/2.0'})
    with urllib.request.urlopen(req,timeout=35) as r: raw=r.read()
    root=ET.fromstring(raw)
    code=txt(root,['resultCode']); msg=txt(root,['resultMsg'])
    if code not in ('0','00','0000') and 'SUCCESS' not in msg.upper(): raise RuntimeError(f'API error {code}: {msg}')
    return root

def page(word,topic,n):
    root=request(LIST,{'serviceKey':KEY,'pageNo':n,'numOfRows':100,'intrsThemaArray':topic,'srchKeyCode':'003','searchWrd':word,'arrgOrd':'001'})
    total=txt(root,['totalCount']); rows=[]
    for node in root.iter():
        sid=txt(node,['servId']); name=txt(node,['servNm'])
        if sid and name:
            rows.append({'id':sid,'name':name,'summary':txt(node,['servDgst','servDtlCn','servCn','servExpln']),
             'region':' '.join(x for x in [txt(node,['ctpvNm']),txt(node,['sggNm'])] if x),
             'category':txt(node,['intrsThemaNmArray','intrsThemaNm','intrsThema']) or word,
             'life_stage':txt(node,['lifeNmArray','lifeNm']),'updated':txt(node,['lastModYmd'])})
    return rows,int(total) if total.isdigit() else len(rows)

def detail(sid):
    root=request(DETAIL,{'serviceKey':KEY,'servId':sid})
    # Keep useful named fields from detail response; never fabricate application links.
    fields={
      'description':['servDgst','servDtlCn','servCn','servExpln'],
      'target':['sprtTrgtCn','trgtCn','sprtTrgt'],
      'criteria':['slctCritCn','slctnCritCn','slctCrit'],
      'support':['alwServCn','srvPvsnCn','sprtCn'],
      'application':['aplyMtdCn','aplyMthdCn','aplyMtd'],
      'contact':['inqplCtadrList','inqplCtadr','telno'],
      'last_updated':['lastModYmd']}
    out={k:txt(root,v) for k,v in fields.items()}
    # Official web/application URL is used only if API explicitly supplies it.
    urls=[]
    for el in root.iter():
        tag=el.tag.split('}')[-1].lower(); value=(el.text or '').strip()
        if value.startswith('http') and any(x in tag for x in ('url','site','link','homepage','aply')): urls.append(value)
    out['official_urls']=list(dict.fromkeys(urls))
    return out

allrows={}; errors=[]
for word,topic in QUERIES:
  try:
    first,total=page(word,topic,1)
    for x in first: allrows[x['id']]=x
    # cap at 5 pages per query to respect free API quota; this is broad sampling, not exhaustive coverage.
    for n in range(2,min((total+99)//100,5)+1):
      for x in page(word,topic,n)[0]: allrows[x['id']]=x
    print(f'{word}: total reported={total}; unique collected={len(allrows)}')
  except Exception as e: errors.append(f'{word}: {e}'); print('WARN',errors[-1])
if not allrows: raise SystemExit('No records collected; existing JSON preserved. '+ '; '.join(errors))
# Detail requests use the API's separate 1,000/day quota. Limit each run to 150 services.
rows=sorted(allrows.values(),key=lambda x:(x['region'],x['name']))[:150]
for i,item in enumerate(rows):
  try: item['detail']=detail(item['id'])
  except Exception as e: item['detail']={}; item['detail_error']=str(e)
  if i and i%25==0: print(f'detail records {i}/{len(rows)}')
  time.sleep(.08)
programs=[]
for x in rows:
  d=x.get('detail',{}); urls=d.get('official_urls',[])
  programs.append({'id':'api-'+x['id'],'servId':x['id'],'title':x['name'],'category':x['category'] or '지자체 복지',
   'region':x['region'],'life_stage':x['life_stage'],'summary':x['summary'] or d.get('description',''),
   'description':d.get('description',''),'target':d.get('target',''),'criteria':d.get('criteria',''),
   'support':d.get('support',''),'application':d.get('application',''),'contact':d.get('contact',''),
   'official_urls':urls,'url':urls[0] if urls else '', 'source':'한국사회보장정보원 지자체복지서비스 API',
   'updated':d.get('last_updated') or x.get('updated') or 'API 갱신일 미제공','api_record':True})
now=datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')
data={'schema_version':4,'dataset_status':'official_api_sync_sampled','generated_at':now,'api_count':len(programs),
 'coverage_note':'검색어·관심주제별로 수집한 API 결과입니다. API에 등록된 전국 모든 사업을 보장하지 않으며, 상세정보나 신청 URL이 없는 경우 빈 값으로 표시합니다.',
 'sync_errors':errors,'programs':programs,
 'refresh_plan':{'frequency':'weekly via GitHub Actions','provider':'한국사회보장정보원 지자체복지서비스 API','paid_services':False,'status':'scheduled_sync_configured; coverage is bounded by query strategy and API limits'}}
OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'Wrote {len(programs)} service records to {OUT}; errors={len(errors)}')
