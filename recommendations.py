"""Pure rules for normalized surf-mcp forecasts; no network or posting."""
import math
from datetime import datetime
from zoneinfo import ZoneInfo

BALI = ZoneInfo('Asia/Makassar')
TIERS = ('beginner', 'intermediate', 'advanced')


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
                'notes': ['Missing/invalid ' + ', '.join(missing) + '; check locally.']}
    notes, coach, area, status = [], False, 'inside/outside', 'suitable to consider'
    if tier == 'beginner':
        area = 'inside whitewater'
        if hi > 2 or energy > 600 or period > 12:
            status, coach = 'conditional', True
            notes.append('Inside exception only; coach must assess actual inside waves (max 2 ft), currents and access.')
        if tide['band'] == 'low':
            status, coach = 'conditional', True
            notes.append('Low tide: shallower, faster/dumpier; prefer rising mid to high.')
        if 400 <= energy <= 600:
            notes.append('Upper beginner range; foamie and inside section preferred.')
    elif tier == 'intermediate':
        if hi > 4 or energy > 1000 or period > 14:
            area, status = 'inside only', 'conditional'
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
    return {'status': status, 'break': area, 'coach': coach, 'notes': notes}


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


def render_day(day, name):
    blocks = [f'{name} | {day["date"]} | WITA\nSource: Surfline via surf-mcp. Check conditions locally; recommendations are not safety guarantees.']
    for interval in daylight_intervals(day):
        a, b = (datetime.fromtimestamp(interval[k], BALI) for k in ('start', 'end'))
        row, tide = interval['row'], interval['tide']
        wind = row.get('wind') or {}
        energy = (row.get('energy') or {}).get('nearshore')
        periods = [s.get('period_s') for s in row.get('swells', []) if positive(s.get('period_s'))]
        speed = wind.get('speed_kts')
        lo, hi = row.get('surf_min_ft'), row.get('surf_max_ft')
        height = f'{lo:g}–{hi:g} ft' if positive(lo) and positive(hi) and lo <= hi else 'N/A'
        text = [f'{a:%H:%M}–{b:%H:%M}', f'Breaking surf: {height}',
                f'Energy: {energy if positive(energy) else "N/A"} kJ | Period: {max(periods) if periods else "N/A"} s',
                f'Wind: {round(speed * 1.852, 1) if positive(speed) else "N/A"} km/h {wind.get("cardinal") or "?"} | Rating: {(row.get("rating") or {}).get("key") or "N/A"}',
                (f'Tide: {tide["height_m"]:.2f} m, {tide["band"]} {tide["trend"]}; mid {tide["mid_m"]:.2f} m' if tide else 'Tide: N/A')]
        for tier, advice in interval['tiers'].items():
            text.append(f'{tier.title()}: {advice["status"]}; {advice["break"]}' + ('; COACH' if advice['coach'] else '') + '. ' + ' '.join(advice['notes']))
        blocks.append('\n'.join(text))
    return blocks
