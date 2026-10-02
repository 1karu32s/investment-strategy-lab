"""Synthetic accounting tests: no market data or credentials required."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

_OUTPUT = tempfile.TemporaryDirectory()
os.environ['FROZEN_SUMMARY_DIR'] = _OUTPUT.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'momentum_tool'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pandas as pd
import frozen_run as fr
from validate_tiingo import normalize

class AccountingSmoke(unittest.TestCase):
    def test_contribution_on_halving_day(self):
        dates = pd.to_datetime(['2020-01-02', '2020-01-03', '2020-01-06'])
        panel = pd.DataFrame({'QQQ': [1., 1., .5]}, index=dates)
        signals = {d: {'trend': False, 'dd': 0., 'picked': []} for d in [dates[0], dates[2]]}
        daily, _, _ = fr.simulate(panel, list(signals), signals, 'B0', dates[0], dates[-1], 0., 0., initial=100, monthly=10)
        self.assertAlmostEqual(daily.nav.iloc[-1], .5)
        self.assertAlmostEqual(daily.value.iloc[-1], (100. + 10.) * .5 + 10.)

    def test_missing_cash_gate_blocks(self):
        gates = {k: True for k in fr.REQUIRED_GATES + fr.CASH_GATES}
        gates.pop('cash_gap_blocks')
        with self.assertRaises(RuntimeError):
            fr.validate_gates(gates, cash_required=True)

    def test_split_day_not_double_adjusted(self):
        rows = [dict(date='2020-01-02', close=100., adjClose=50., divCash=0., splitFactor=1.),
                dict(date='2020-01-03', close=50., adjClose=50., divCash=0., splitFactor=2.),
                dict(date='2020-01-06', close=51., adjClose=51., divCash=0., splitFactor=1.)]
        result = normalize(rows)
        self.assertEqual(result[1]['future_split_factor'], 1.)
        self.assertAlmostEqual(result[1]['gross_exdate_total_return_index'], 1.)
        self.assertAlmostEqual(result[2]['gross_exdate_total_return_index'], 1.02)

if __name__ == '__main__':
    unittest.main()
