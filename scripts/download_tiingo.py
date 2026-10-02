"""Download Tiingo ETF evidence with explicit dates; preserve raw files and never log tokens."""
import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import math
import os
import re
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, 'Redirect refused', headers, fp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tickers', nargs='+', required=True)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    for value in (args.start, args.end):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            parser.error('日期必须使用 YYYY-MM-DD')
        try:
            datetime.strptime(value, '%Y-%m-%d')
        except ValueError:
            parser.error('日期无效')
    if args.start > args.end:
        parser.error('起始日期不能晚于结束日期')
    tickers = list(dict.fromkeys(t.upper() for t in args.tickers))
    if any(not re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,19}', t) for t in tickers):
        parser.error('无效 ticker')
    token = os.environ.get('TIINGO_API_TOKEN', '').strip()
    if not token:
        if not sys.stdin.isatty():
            raise SystemExit('请在交互式终端隐藏输入 token，或预先配置 TIINGO_API_TOKEN。')
        token = getpass.getpass('Tiingo API token（输入不显示）: ').strip()
    if not token:
        raise SystemExit("未输入 token；未发送请求。")
    root = args.out.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    out = root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out.mkdir()
    report = {"provider": "Tiingo", "status": "download_only_unverified",
              "requested_start": args.start, "requested_end": args.end,
              "primary_gate_passed": False, "files": [], "errors": []}
    for ticker in tickers:
        base = f"https://api.tiingo.com/tiingo/daily/{ticker}"
        requests = [("metadata", base),
                    ("prices", base + f"/prices?startDate={args.start}&endDate={args.end}&format=json")]
        for kind, url in requests:
            record = {"ticker": ticker, "kind": kind, "url": url,
                      "fetched_at_utc": datetime.now(timezone.utc).isoformat()}
            try:
                req = Request(url, headers={"Authorization": "Token " + token,
                                            "Accept": "application/json"})
                with build_opener(NoRedirect).open(req, timeout=45) as response:
                    raw = response.read()
                data = json.loads(raw)
                if kind == "metadata":
                    if not isinstance(data, dict) or data.get("ticker", "").upper() != ticker:
                        raise ValueError("元数据标的不匹配")
                else:
                    if not isinstance(data, list) or not data:
                        raise ValueError("行情为空或不是记录列表")
                    dates = []
                    for row in data:
                        dates.append(row["date"][:10])
                        for field in ("close", "adjClose", "splitFactor"):
                            value = float(row[field])
                            if not math.isfinite(value) or value <= 0:
                                raise ValueError("无效价格或拆股因子")
                        if not math.isfinite(float(row["divCash"])):
                            raise ValueError("无效分红字段")
                    if len(set(dates)) != len(dates):
                        raise ValueError("重复行情日期")
                    record.update(rows=len(data), first_date=min(dates), last_date=max(dates))
                    if min(dates) < args.start or max(dates) > args.end:
                        raise ValueError('行情日期超出请求范围')
                    record['calendar_completeness'] = 'not_checked'
                    record['boundary_note'] = 'Actual dates recorded; holidays and truncation require calendar checks'
                name = f"{ticker}_{kind}.json"
                (out / name).write_bytes(raw)
                record.update(file=name, sha256=hashlib.sha256(raw).hexdigest())
                report["files"].append(record)
                print(f"{ticker} {kind}: 已保存", end="")
                if kind == "prices":
                    print(f"，{len(data)} 行，{min(dates)} 至 {max(dates)}")
                else:
                    print()
            except HTTPError as exc:
                # Do not print response bodies or headers that might echo credentials.
                report["errors"].append({**record, "error": f"HTTP {exc.code}"})
                print(f"{ticker} {kind}: HTTP {exc.code}；需核实账户权限或访问限制。")
            except (URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
                report["errors"].append({**record, "error": type(exc).__name__})
                print(f"{ticker} {kind}: {type(exc).__name__}；未通过下载检查。")
            finally:
                (out / "manifest.json").write_text(json.dumps(report, indent=2))
    print(f"证据目录：{out}")
    print("下载结果尚待分红、拆股及价格交叉核验；未替换回测数据。")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
