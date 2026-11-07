"""Describe absent inputs without treating them as favourable surf conditions."""
from datetime import datetime
from recommendations import BALI, number, positive, daylight_intervals, report_header
from phase2 import build_blocks, chunks

LABELS = {'wind': 'Wind and gusts', 'tides': 'Tide', 'energy': 'Wave energy',
          'rating': 'Surfline rating', 'swells': 'Swell', 'weather': 'Sunrise and sunset'}


def inspect(data, target):
    day = next((d for d in data.get('daily', []) if d.get('date') == target), None)
    if day is None:
        return {'surf', 'weather'}, None
    try:
        intervals = daylight_intervals(day)
    except ValueError:
        rows = day.get('hourly', [])
        valid_surf = any(positive(r.get('surf_min_ft')) and positive(r.get('surf_max_ft'))
                         and r['surf_min_ft'] <= r['surf_max_ft'] for r in rows)
        return ({'weather'} if valid_surf else {'weather', 'surf'}), None
    missing = set()
    for i in intervals:
        r = i['row']
        if not (positive(r.get('surf_min_ft')) and positive(r.get('surf_max_ft'))
                and r['surf_min_ft'] <= r['surf_max_ft']):
            missing.add('surf')
        if not all(positive((r.get('wind') or {}).get(k)) for k in ('speed_kts', 'gust_kts')):
            missing.add('wind')
        if i['tide'] is None or not number(i['tide'].get('height_m')):
            missing.add('tides')
        if not positive((r.get('energy') or {}).get('nearshore')):
            missing.add('energy')
        if not (r.get('rating') or {}).get('key'):
            missing.add('rating')
        if not any(positive(s.get('period_s')) for s in r.get('swells', [])):
            missing.add('swells')
    # The pre-sunrise gust rule also needs target-date early-hour observations.
    sunrise = (day.get('sunlight') or {}).get('sunrise_ts')
    early = [r for r in day.get('hourly', []) if number(r.get('timestamp')) and r['timestamp'] < sunrise]
    if not early or any(not positive((r.get('wind') or {}).get('gust_kts')) for r in early):
        missing.add('wind')
    return missing, intervals


def render(data, target, name, missing, intervals):
    if intervals is None:
        report = report_header(target, name) + '\n\n' + '\n\n'.join(
            title + '\nCould not assess surf times because sunrise/sunset data is unavailable.'
            for title in ('🟢 BEGINNER', '🟡 INTERMEDIATE', '🔵 ADVANCED'))
        parts = chunks([report], limit=3000)
    else:
        parts = chunks(build_blocks(data, target, name), limit=3000)
        if any(i['tiers'][tier]['status'] == 'unknown' for i in intervals
               for tier in ('beginner', 'intermediate', 'advanced')):
            parts = [p.replace('No qualifying window.', 'Could not confirm a suitable window from the available data.')
                     for p in parts]
    notes = []
    for endpoint in sorted(missing):
        if endpoint not in LABELS:
            continue
        detail = LABELS[endpoint] + ' data could not be retrieved completely from Surfline and was not fully included in the report'
        if endpoint == 'tides':
            detail += ', so I could not confirm if the inside break is suitable for beginners'
        elif endpoint == 'wind':
            detail += ', so I could not fully assess windy or choppy periods'
        elif endpoint in ('energy', 'rating'):
            detail += ', so recommendations could not be fully confirmed'
        elif endpoint == 'weather':
            detail += ', so I could not confirm the daylight surfing window'
        notes.append(detail + '.')
    return parts, ('Data notes: ' + ' '.join(notes) if notes else '')
