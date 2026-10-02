"""Offline Tiingo EOD reconciliation. Standard library only; no external approval implied."""
import argparse
import csv
import hashlib
import json
import math
from datetime import date
from pathlib import Path


def normalize(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError('Empty or invalid prices')
    ordered = sorted(rows, key=lambda r: r['date'])
    seen = set()
    for r in ordered:
        day = r['date'][:10]
        date.fromisoformat(day)
        if day in seen:
            raise ValueError('Duplicate date')
        seen.add(day)
        for key in ('close', 'adjClose', 'divCash', 'splitFactor'):
            if not math.isfinite(float(r[key])):
                raise ValueError('Non-finite field')
        if any(float(r[k]) <= 0 for k in ('close', 'adjClose', 'splitFactor')):
            raise ValueError('Non-positive price or split')
        if float(r['splitFactor']) != 1 and float(r['divCash']) != 0:
            raise ValueError('Same-day split and dividend: establish dividend share basis first')
    factors = [1.] * len(ordered)
    future = 1.
    for i in range(len(ordered) - 1, -1, -1):
        factors[i] = future
        future *= float(ordered[i]['splitFactor'])
    result = []
    tri = 1.
    previous = None
    previous_adj = None
    base_adj = float(ordered[0]['adjClose'])
    for row, factor in zip(ordered, factors):
        price = float(row['close']) / factor
        dividend = float(row['divCash']) / factor
        gross = (price + dividend) / previous if previous is not None else 1.
        if gross <= 0 or not math.isfinite(gross):
            raise ValueError('Invalid total-return factor')
        tri *= gross
        adjusted = float(row['adjClose'])
        residual = (adjusted / previous_adj - gross) * 10000 if previous_adj is not None else None
        result.append({'date': row['date'][:10], 'raw_close': row['close'],
                       'raw_divCash': row['divCash'], 'splitFactor': row['splitFactor'],
                       'future_split_factor': factor, 'split_adjusted_close': price,
                       'split_adjusted_distribution': dividend,
                       'gross_exdate_total_return_index': tri,
                       'provider_adjusted_index': adjusted / base_adj,
                       'provider_vs_exdate_daily_bps': residual})
        previous, previous_adj = price, adjusted
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    manifest = json.loads((root / 'manifest.json').read_text())
    files = manifest['files']
    for record in files:
        path = (root / record['file']).resolve()
        if path.parent != root:
            raise ValueError('Manifest path must reference a file inside the download directory')
        if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Source SHA256 mismatch')
    out = root / 'validation'
    out.mkdir(exist_ok=True)
    report = {'status': 'internal_reconciliation_only', 'primary_gate_passed': False,
              'source_manifest_sha256': hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest(),
              'validator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'download_errors': manifest.get('errors', []), 'assets': {}, 'errors': [],
              'limitations': ['Exchange-calendar completeness not checked',
                             'Independent prices and issuer corporate actions not verified',
                             'First observation starts at its close; first-row dividend not earned',
                             'No backtest inputs changed']}
    prices = [r for r in files if r['kind'] == 'prices']
    for record in prices:
        ticker = record['ticker']
        # Output filename derives from verified source filename, not arbitrary ticker text.
        target = out / (Path(record['file']).stem + '_normalized.csv')
        try:
            rows = json.loads((root / record['file']).read_text())
            frame = normalize(rows)
            with target.open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(frame[0]))
                writer.writeheader()
                writer.writerows(frame)
            report['assets'][ticker] = {
                'rows': len(frame), 'start': frame[0]['date'], 'end': frame[-1]['date'],
                'dividend_events': sum(float(r['divCash']) != 0 for r in rows),
                'splits': {r['date'][:10]: r['splitFactor'] for r in rows if float(r['splitFactor']) != 1},
                'max_abs_daily_residual_bps': max((abs(r['provider_vs_exdate_daily_bps']) for r in frame[1:]), default=0.),
                'terminal_provider_to_reconstructed_ratio': frame[-1]['provider_adjusted_index'] / frame[-1]['gross_exdate_total_return_index'],
                'file': target.name, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
        except (ValueError, KeyError, TypeError, ZeroDivisionError, OverflowError) as exc:
            report['errors'].append({'ticker': ticker, 'error': str(exc)})
    if not prices:
        report['errors'].append({'error': 'No price files in manifest'})
    (out / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report['errors'] or report['download_errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
