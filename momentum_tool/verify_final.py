from data_layer import load_prices
from engine import Strategy, run_backtest
from metrics import perf_stats, stress_report
import config

prices = load_prices(config.ALL_TICKERS)
s = Strategy(**config.RECOMMENDED)
r = run_backtest(prices, s, start="2017-01-01")
q = prices["QQQ"].loc["2017-01-01":]
qn = q / q.iloc[0]
st, qst = perf_stats(r["nav"]), perf_stats(qn)
print("推荐配置最终验证:", s.label())
print(f"策略: CAGR {st['CAGR']:.1%} | MaxDD {st['MaxDD']:.1%} | "
      f"Calmar {st['Calmar']:.2f} | 年换手 {r['annual_turnover']:.1f}")
print(f"QQQ : CAGR {qst['CAGR']:.1%} | MaxDD {qst['MaxDD']:.1%} | Calmar {qst['Calmar']:.2f}")
print("压力场景:", {k: f"{v:+.1%}" for k, v in stress_report(r["nav"]).items()})
print("最近 3 次调仓:")
print(r["trades"].tail(3).to_string(index=False))
