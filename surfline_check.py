"""Inspect a saved forecast, or explicitly request a protected live diagnostic."""
from review_bot import Store, capture_label, saved_parts
from forecast_sources import Forecast
from run_log import write_summary
import argparse
from datetime import datetime, timedelta
from importlib.metadata import PackageNotFoundError, version

from forecast_sources import SourceUnavailable, fetch_surfline
from recommendations import BALI, daylight_intervals, number, positive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', default='', help='YYYY-MM-DD; empty means tomorrow in Bali')
    parser.add_argument('--live', action='store_true', help='Use the protected daily Surfline request budget')
    parser.add_argument('--state', default='review-state/state.json')
    args = parser.parse_args()
    target = args.date or (datetime.now(BALI) + timedelta(days=1)).date().isoformat()
    try:
        datetime.strptime(target, '%Y-%m-%d')
    except ValueError:
        parser.error('Use a forecast date in YYYY-MM-DD format.')
    if args.live:
        print('Live Surfline check only. No Telegram or LLM calls; request checkpoints only; no review-state changes.', flush=True)
        for name in ('requests', 'curl_cffi', 'surf-mcp'):
            try:
                installed = version(name)
            except PackageNotFoundError:
                print('Required dependency is missing: ' + name)
                return 1
            print(f'{name}: {installed}', flush=True)
        try:
            snapshot = fetch_surfline(target)
        except SourceUnavailable as error:
            print('Forecast check failed: ' + str(error))
            return 1
    else:
        record = Store(args.state).data['reports'].get(target, {})
        data = record.get('forecast') or {}
        if not data.get('daily'):
            print(f'No saved forecast for {target}.')
            return 1
        name = record.get('name') or data.get('spot_name') or 'Surf spot'
        snapshot = Forecast(target, name, data, saved_parts(data, target, name))
    print(capture_label(snapshot.data))
    day = next(day for day in snapshot.data['daily'] if day['date'] == target)
    try:
        intervals = daylight_intervals(day)
    except ValueError:
        print('Sunrise/sunset unavailable; no daylight windows assessed.')
        print(snapshot.data.get('data_notes', ''))
        return 0
    print(f'Forecast available: {snapshot.name} | {target} | Bali/WITA.')
    print(f'Daylight intervals with breaking-surf coverage: {len(intervals)}.')
    checks = {
        'Wind': lambda interval: positive((interval['row'].get('wind') or {}).get('speed_kts')),
        'Swell period': lambda interval: any(positive(s.get('period_s'))
                                             for s in interval['row'].get('swells', [])),
        'Energy': lambda interval: positive((interval['row'].get('energy') or {}).get('nearshore')),
        'Tide': lambda interval: interval['tide'] is not None and number(interval['tide']['height_m']),
        'Rating': lambda interval: bool((interval['row'].get('rating') or {}).get('key')),
    }
    for label, available in checks.items():
        print(f'{label} coverage: {sum(available(interval) for interval in intervals)}/{len(intervals)}.')
    print(f'Deterministic report prepared: {len(snapshot.parts)} parts. PREVIEW ONLY; nothing sent.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    finally:
        write_summary()
