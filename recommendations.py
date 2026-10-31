"""Pure rules for normalized surf-mcp forecasts; no network or posting."""
import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

BALI = ZoneInfo('Asia/Makassar')
TIERS = ('beginner', 'intermediate', 'advanced')
REPORT_CAUTIONS = (
    'High energy: strong currents possible.',
    'Wind above 20 km/h: surf only if comfortable; beginners should go with a coach.',
    'Below 100 kJ: generally too flat for worthwhile surfing.',
)
INSIDE_CAUTION = 'Check actual inside waves: beginners at most 2 ft; intermediate inside-only at most 4 ft.'


def forecast_date_label(target):
    return datetime.strptime(target, '%Y-%m-%d').strftime('%d %B %Y').lstrip('0')


def report_header(target, name):
    return f'Forecast date: {forecast_date_label(target)}\n\n📍{name.upper()}'


def report_bold_entities(text):
    """Telegram entity offsets count UTF-16 units, including preceding emoji."""
    headings = {'🟢 BEGINNER', '🟡 INTERMEDIATE', '🔵 ADVANCED', '⚠️ CAUTIONS'}
    entities, offset = [], 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip('\r\n')
        if content.startswith(('Forecast date:', '📍')) or content in headings:
            entities.append({'type': 'bold', 'offset': offset,
                             'length': len(content.encode('utf-16-le')) // 2})
        offset += len(line.encode('utf-16-le')) // 2
    return entities


def clean_report_text(text):
    """Remove the retired report banner without changing surf/coach advice."""
    for pattern in (r'\bWITA\b',
                    r'\bSource:\s*Surfline(?:\s+via\s+surf-mcp)?\.?',
                    r'\bCheck\s+conditions\s+locally[;,.]?\s+recommendations\s+are\s+not\s+safety\s+guarantees\.?'):
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    text = re.sub(r'[ \t]*\|[ \t]*(?=\r?$)', '', text, flags=re.MULTILINE)
    text = re.sub(r'[ \t]+\n', '\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def positive(value):
    return number(value) and value >= 0


def tide_at(day, timestamp):
    """Interpolate only bracketed samples no more than 2 hours apart."""
    samples = sorted((t['timestamp'], t['height_ft'] * .3048)
                     for t in day.get('tide_hourly', [])
                     if number(t.get('timestamp')) and number(t.get('height_ft')))
    if not samples:
        return None
    extrema = [t['height_ft'] * .3048 for t in day.get('tide_extrema', [])
               if number(t.get('height_ft'))]
    heights = [h for _, h in samples] + extrema
    low, high = min(heights), max(heights)
    for (a, x), (b, y) in zip(samples, samples[1:]):
        if a <= timestamp <= b and 0 < b - a <= 7200:
            height = x + (y - x) * (timestamp - a) / (b - a)
            fraction = (height - low) / (high - low) if high > low else None
            band = 'unknown' if fraction is None else ('low' if fraction < .33 else 'high' if fraction > .67 else 'mid')
            return {'height_m': height, 'mid_m': (low + high) / 2,
                    'band': band, 'trend': 'rising' if y > x else 'falling' if y < x else 'slack'}
    return None


def recommend(row, tide, tier):
    if tier not in TIERS:
        raise ValueError('Unknown skill tier')
    lo, hi = row.get('surf_min_ft'), row.get('surf_max_ft')
    energy = (row.get('energy') or {}).get('nearshore')
    periods = [s['period_s'] for s in row.get('swells', []) if positive(s.get('period_s'))]
    period = max(periods) if periods else None
    wind = (row.get('wind') or {}).get('speed_kts')
    rating = (row.get('rating') or {}).get('key')
    missing = [name for name, ok in [('breaking height', positive(lo) and positive(hi) and lo <= hi),
               ('energy', positive(energy)), ('period', positive(period)), ('wind', positive(wind)),
               ('tide', tide is not None and tide['band'] != 'unknown'), ('rating', bool(rating))] if not ok]
    if missing:
        return {'status': 'unknown', 'break': 'unassessed', 'coach': tier == 'beginner',
                'missing': missing,
                'notes': ['Missing/invalid ' + ', '.join(missing) + '; check locally.']}
    notes, coach, area, status = [], False, 'inside/outside', 'suitable to consider'
    inside_limit = None
    if tier == 'beginner':
        area = 'inside whitewater'
        if hi > 2 or energy > 600 or period > 12:
            status, coach = 'conditional', True
            inside_limit = 2
            notes.append('Inside exception only; coach must assess actual inside waves (max 2 ft), currents and access.')
        if tide['band'] == 'low':
            status, coach = 'conditional', True
            notes.append('Low tide: shallower, faster/dumpier; prefer rising mid to high.')
        if 400 <= energy <= 600:
            notes.append('Upper beginner range; foamie and inside section preferred.')
    elif tier == 'intermediate':
        if hi > 4 or energy > 1000 or period > 14:
            area, status = 'inside only', 'conditional'
            inside_limit = 4
            notes.append('Outside exceeds intermediate limits; check inside waves are at most 4 ft.')
        if tide['band'] != 'mid':
            status = 'conditional'
            notes.append('Prefer mid tide, rising or falling.')
    else:
        if hi > 4 or energy > 1000:
            notes.append('Powerful sets, currents, long paddle out and closeouts possible.')
        if tide['band'] != 'mid':
            notes.append('Prefer mid tide; assess reef depth and access.')
    if energy < 100:
        status = 'not recommended'
        notes.append('Nearly flat; beginners may try inside but not recommended. Longboard/foamie may help.')
    elif energy < 200:
        notes.append('Weak/small surf; longboard or 8 ft+ foamie preferred.')
    if tier == 'intermediate' and 600 <= energy <= 1000 and 10 <= period <= 14 and hi <= 4 and tide['band'] == 'mid':
        notes.append('Within preferred intermediate energy, period and tide range.')
    if wind * 1.852 > 20:
        if status != 'not recommended':
            status = 'conditional'
        coach = coach or tier == 'beginner'
        notes.append('Wind above 20 km/h: try only if comfortable; beginners should use a coach.')
    if str(rating).upper() in ('VERY_POOR', 'POOR', 'POOR_TO_FAIR'):
        if status == 'suitable to consider':
            status = 'conditional'
        notes.append('Low Surfline quality rating; manage expectations.')
    notes.append(f'Breaking surf forecast {lo:g}–{hi:g} ft; inside height is not separately forecast.')
    return {'status': status, 'break': area, 'coach': coach,
            'inside_limit_ft': inside_limit, 'notes': notes}


def daylight_intervals(day):
    """Cover sunrise to sunset, including gaps and partial boundary hours."""
    sunlight = day.get('sunlight') or {}
    start, end = sunlight.get('sunrise_ts'), sunlight.get('sunset_ts')
    if not number(start) or not number(end) or not start < end:
        raise ValueError('Sunrise/sunset unavailable; daylight recommendations withheld')
    date = day['date']
    if any(datetime.fromtimestamp(t, BALI).date().isoformat() != date for t in (start, end)):
        raise ValueError('Sunlight date mismatch')
    rows = {r['timestamp']: r for r in day.get('hourly', []) if number(r.get('timestamp'))}
    cursor, result = start, []
    while cursor < end:
        hour = math.floor(cursor / 3600) * 3600
        stop = min(hour + 3600, end)
        row = rows.get(hour, {})
        tide = tide_at(day, cursor)
        result.append({'start': cursor, 'end': stop, 'row': row, 'tide': tide,
                       'tiers': {tier: recommend(row, tide, tier) for tier in TIERS}})
        cursor = stop
    return result


def brief_advice(interval, tier):
    advice, row = interval['tiers'][tier], interval['row']
    if advice['status'] == 'unknown':
        return 'Not assessed (missing ' + ', '.join(advice['missing']) + ')'
    if advice['status'] == 'not recommended':
        return 'Not recommended (too flat)'
    energy = row['energy']['nearshore']
    period = max(s['period_s'] for s in row['swells'] if positive(s.get('period_s')))
    reasons = []
    if tier == 'beginner':
        label = 'Inside break'
        if row['surf_max_ft'] > 2:
            reasons.append('larger sets')
        if energy > 600:
            reasons.append('high energy')
        if period > 12:
            reasons.append('long period')
        if interval['tide']['band'] == 'low':
            reasons.append('low tide')
        if advice['coach']:
            label += ', coach recommended'
    elif tier == 'intermediate':
        label = 'Inside break only' if advice['break'] == 'inside only' else ''
        if row['surf_max_ft'] > 4:
            reasons.append('larger sets')
        if energy > 1000:
            reasons.append('high energy')
        if period > 14:
            reasons.append('long period')
        if interval['tide']['band'] != 'mid':
            reasons.append('mid tide preferred')
    else:
        lo, hi = row['surf_min_ft'], row['surf_max_ft']
        height = f'{hi:g}' if lo == hi else f'{lo:g}–{hi:g}'
        label = f'Breaking waves {height} ft'
    if row['wind']['speed_kts'] * 1.852 > 20:
        reasons.append('strong wind')
    if str(row['rating']['key']).upper() in ('VERY_POOR', 'POOR', 'POOR_TO_FAIR'):
        reasons.append('low quality rating')
    if 100 <= energy < 200:
        reasons.append('weak surf')
    if reasons:
        label = (label or 'Conditional') + ' (' + ', '.join(reasons) + ')'
    return label


def tier_windows(intervals, tier):
    # Merge adjacent intervals with identical displayed advice. Disjoint windows
    # retain their endpoints and are joined with "and", never bridged over gaps.
    runs = []
    for interval in intervals:
        label = brief_advice(interval, tier)
        if runs and runs[-1]['end'] == interval['start'] and runs[-1]['label'] == label:
            runs[-1]['end'] = interval['end']
        else:
            runs.append({'start': interval['start'], 'end': interval['end'], 'label': label})
    grouped = {}
    for run in runs:
        start, end = (datetime.fromtimestamp(run[key], BALI) for key in ('start', 'end'))
        grouped.setdefault(run['label'], []).append(f'{start:%H:%M}–{end:%H:%M}')
    return [' and '.join(times) + (' — ' + label if label else '') for label, times in grouped.items()]


def render_day(day, name):
    intervals = daylight_intervals(day)
    blocks = [report_header(day['date'], name)]
    for tier, heading in zip(TIERS, ('🟢 BEGINNER', '🟡 INTERMEDIATE', '🔵 ADVANCED')):
        blocks.append(heading + '\n' + '\n'.join(tier_windows(intervals, tier)))
    cautions = list(REPORT_CAUTIONS)
    if any(advice.get('inside_limit_ft') and advice['status'] == 'conditional'
           for interval in intervals for advice in interval['tiers'].values()):
        cautions.append(INSIDE_CAUTION)
    if any(positive((i['row'].get('energy') or {}).get('nearshore'))
           and 100 <= i['row']['energy']['nearshore'] < 200 for i in intervals):
        cautions.append('Weak surf: a longboard or foamie is preferred.')
    blocks.append('⚠️ CAUTIONS\n' + '\n'.join('- ' + text for text in cautions))
    return blocks
