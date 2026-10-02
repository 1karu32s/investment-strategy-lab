"""Public source acquisition only; no credentials and no backtest-input replacement."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent
OUT = ROOT/'downloads'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
URLS = {
 'usd_cny_fed.html':'https://www.federalreserve.gov/releases/h10/hist/dat00_ch.htm',
 'spmo_nasdaq_prices.json':'https://api.nasdaq.com/api/quote/SPMO/historical?assetclass=etf&fromdate=2015-10-09&todate=2026-09-30&limit=9999',
 'spmo_nasdaq_dividends.json':'https://api.nasdaq.com/api/quote/SPMO/dividends?assetclass=etf',
 'spmo_invesco_distributions.json':'https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46138E339/distribution?idType=cusip&productType=ETF',
 'spmo_invesco_nav.json':'https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46138E339/navs?idType=cusip&productType=ETF',
 'spmo_invesco_performance.json':'https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46138E339/performance/standard?idType=cusip&performanceSubType=cumulative&productType=ETF&performancePeriod=monthly',
 'usd_cny_fred.csv':'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXCHUS&cosd=2015-10-01&coed=2026-09-30',
}
def fetch(item):
 name,url=item
 rec={'url':url,'retrieved_utc':datetime.now(timezone.utc).isoformat(),'validation':'download_only'}
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json, text/plain, */*'})
  with urllib.request.urlopen(req,timeout=25) as r:
   b=r.read();(OUT/name).write_bytes(b)
   rec.update(http_status=r.status,bytes=len(b),sha256=hashlib.sha256(b).hexdigest(),file=str(OUT/name))
 except Exception as e:
  rec['error']=str(e)
 return name,rec
if __name__=='__main__':
 OUT.mkdir(parents=True)
 with ThreadPoolExecutor(max_workers=4) as pool:
  results=dict(pool.map(fetch,URLS.items()))
 (OUT/'manifest.json').write_text(json.dumps(results,indent=2)+'\n')
 print(json.dumps({'directory':str(OUT),'sources':results},indent=2))
