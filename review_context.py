"""Private, deterministic decision explanations and saved Surfline summaries."""
from datetime import datetime

from recommendations import (BALI, TIERS, LOW_RATINGS, daylight_intervals, number,
                             qualifies, rating_label, forecast_date_label, tier_windows)


def clock(timestamp):
    return datetime.fromtimestamp(timestamp, BALI).strftime('%H:%M')


def value(item, digits=1):
    return f'{item:.{digits}f}'.rstrip('0').rstrip('.') if number(item) else 'N/A'


def span(items, digits=1):
    items = [item for item in items if number(item)]
    if not items:
        return 'N/A'
    low, high = min(items), max(items)
    return value(low, digits) + ('–' + value(high, digits) if low != high else '')


def longest_period(row):
    periods = [s.get('period_s') for s in row.get('swells', []) if number(s.get('period_s'))]
    return max(periods) if periods else None


def current_sections(parts):
    sections, tier = {}, None
    for line in '\n'.join(parts).splitlines():
        heading = line.strip().strip('*').strip()
        found = next((t for t in TIERS if heading in
                      (t.upper(), {'beginner': '🟢 BEGINNER', 'intermediate': '🟡 INTERMEDIATE',
                                   'advanced': '🔵 ADVANCED'}[t])), None)
        if found:
            tier = found
            sections[tier] = []
        elif 'CAUTIONS' in heading:
            tier = None
        elif tier and heading:
            sections[tier].append(heading)
    return sections


def exclusion_reasons(interval, tier):
    advice, row = interval['tiers'][tier], interval['row']
    if advice['status'] == 'unknown':
        return ('missing ' + ', '.join(advice['missing']),)
    reasons = []
    rating = str(row['rating']['key']).upper()
    if rating in LOW_RATINGS:
        reasons.append('Surfline rates the conditions ' + rating_label(rating))
    if row['wind']['speed_kts'] * 1.852 > 20:
        reasons.append('wind exceeds 20 km/h')
    energy = row['energy']['nearshore']
    if energy < 100:
        reasons.append('energy is below the 100 flat-surf rule')
    if tier == 'beginner' and energy > 600:
        reasons.append('energy exceeds the 600 beginner/high-energy rule')
    if tier == 'intermediate':
        if row['surf_max_ft'] > 4:
            reasons.append('breaking surf exceeds 4 ft')
        if longest_period(row) > 14:
            reasons.append('the longest swell period exceeds 14 s')
        if energy > 1000:
            reasons.append('energy exceeds 1000')
        if interval['tide']['band'] != 'mid':
            reasons.append('the tide is ' + interval['tide']['band'] + ', rather than mid tide')
    if tier == 'beginner' and not reasons:
        reasons.append('low tide is conditional and this hour has no over-limit inside-break exception')
    return tuple(reasons) or ('the skill-level rules do not qualify this hour',)


def decision_runs(intervals, tier):
    runs = []
    for interval in intervals:
        included = qualifies(interval, tier)
        inside = included and tier == 'beginner' and interval['tiers'][tier].get('inside_limit_ft') == 2
        reason = ('coached inside-break exception',) if inside else (
            ('the skill-level rules pass',) if included else exclusion_reasons(interval, tier))
        key = (included, inside, reason)
        if runs and runs[-1]['end'] == interval['start'] and runs[-1]['key'] == key:
            runs[-1]['end'] = interval['end']
            runs[-1]['intervals'].append(interval)
        else:
            runs.append(dict(start=interval['start'], end=interval['end'], key=key, intervals=[interval]))
    return runs


def reasoning(report, intervals):
    sections = current_sections(report['parts'])
    lines = ['DETAILED SURF ANALYSIS — ' + forecast_date_label(report['date'])
             + f" v{report['revision']}", 'Private review only. This explains the saved source and current draft.']
    for tier in TIERS:
        lines.extend(['', tier.upper()])
        rules = {
            'beginner': 'Rules: 2 ft / 12 s beginner limits; the explicit coached inside exception can '
                        'qualify above those limits when energy is at most 600, wind at most 20 km/h '
                        'and the rating at least Fair.',
            'intermediate': 'Rules: outside surf at most 4 ft, longest period at most 14 s, energy at most '
                            '1000 and mid tide. The preferred 600–1000 energy band is guidance, not a lower cutoff.',
            'advanced': 'Rules: no fixed upper height/period ceiling; poor ratings, wind above 20 km/h, '
                        'flat surf and missing data are excluded. Low/high tide is a preference caution '
                        'rather than an exclusion for this level.',
        }
        lines.append(rules[tier])
        if sections.get(tier):
            lines.append('Current draft: ' + '; '.join(sections[tier]))
        windows = tier_windows(intervals, tier)
        lines.append('Source-rule windows: ' + '; '.join(windows))
        if sections.get(tier) and sections[tier] != windows:
            lines.append('The current draft differs from the source-rule windows; Leo must review the edits.')
        for run in decision_runs(intervals, tier):
            included, inside, reasons = run['key']
            text = f"{clock(run['start'])}–{clock(run['end'])}: "
            text += ('Included' if included else 'Excluded') + ' — ' + '; '.join(reasons) + '.'
            if included:
                rows = [i['row'] for i in run['intervals']]
                heights = [r.get(k) for r in rows for k in ('surf_min_ft', 'surf_max_ft')]
                winds = [r.get('wind', {}).get('speed_kts') for r in rows]
                text += (' Breaking surf ' + span(heights) + ' ft; longest swell period '
                         + span([longest_period(r) for r in rows]) + ' s; wind '
                         + span([w * 1.852 for w in winds if number(w)]) + ' km/h; energy '
                         + span([r.get('energy', {}).get('nearshore') for r in rows]) + ' (feed values).')
                if inside:
                    text += (' The outside forecast exceeds a beginner height/period limit. A coach must '
                             'check inside waves are at most 2 ft and assess currents, including at low tide.')
            lines.append(text)
    lines.extend(['', 'Energy units are unconfirmed. The 600 flag is an application rule; '
                  'these data do not measure or establish current strength.'])
    if report.get('feedback'):
        lines.extend(['Reviewer feedback for this draft (not original Surfline data):', report['feedback'],
                      'Compare reviewer edits in the current draft with the source-rule assessment above. '
                      'Original source values remain unchanged in the next message.'])
    return '\n'.join(lines)


def source_summary(report, day, intervals):
    lines = ['SURFLINE DATA SUMMARY — ' + forecast_date_label(report['date'])
             + f" v{report['revision']}",
             'Private review only. Saved Surfline snapshot; revisions do not refresh or overwrite it.',
             'Sunrise ' + clock(day['sunlight']['sunrise_ts']) + '; sunset '
             + clock(day['sunlight']['sunset_ts']) + '. Analyzed '
             + clock(intervals[0]['start']) + '–' + clock(intervals[-1]['end']) + ' (Bali time).',
             'Surf is breaking-wave height; inside waves are not separately forecast.',
             'E = nearshore energy (feed units unconfirmed); P = longest swell-partition period.',
             'Each row describes the following hour. Tide height is interpolated; bands/trend are application calculations.',
             'Displayed values are rounded; the original snapshot stays saved.',
             '', 'Time | Surf ft | E | P s | Wind km/h | Tide m (band/trend) | Rating']
    for interval in intervals:
        row, tide = interval['row'], interval['tide']
        wind = row.get('wind') or {}
        speed = wind.get('speed_kts')
        direction = str(wind.get('cardinal') or '')[:4]
        tide_text = (value(tide['height_m'], 2) + ' ' + tide['band'] + '/' + tide['trend']
                     if tide else 'N/A')
        lines.append(' | '.join([clock(interval['start']),
                                value(row.get('surf_min_ft')) + '–' + value(row.get('surf_max_ft')),
                                value((row.get('energy') or {}).get('nearshore')),
                                value(longest_period(row)),
                                value(speed * 1.852 if number(speed) else None) + ' ' + direction,
                                tide_text, rating_label((row.get('rating') or {}).get('key'))]))
    extrema = [t for t in day.get('tide_extrema', []) if number(t.get('timestamp'))
               and intervals[0]['start'] <= t['timestamp'] <= intervals[-1]['end']]
    if extrema:
        lines.extend(['', 'Daylight tide events: ' + '; '.join(
            str(t.get('type', 'Tide')).capitalize() + ' ' + clock(t['timestamp']) + ' ('
            + value(t.get('height_ft') * .3048 if number(t.get('height_ft')) else None, 2) + ' m)'
            for t in sorted(extrema, key=lambda t: t['timestamp'])) + '.'])
    rows = [i['row'] for i in intervals]
    gusts = [(r.get('wind') or {}).get('gust_kts') for r in rows]
    if any(number(gust) for gust in gusts):
        lines.append('Daylight gust range: ' + span([g * 1.852 for g in gusts if number(g)]) + ' km/h.')
    count = max((len(r.get('swells', [])) for r in rows), default=0)
    if count:
        lines.append('Swell ranges by feed position (positions do not identify a tracked swell system):')
        for index in range(count):
            swells = [r['swells'][index] for r in rows if len(r.get('swells', [])) > index]
            directions = sorted({str(s['cardinal']) for s in swells if s.get('cardinal')})
            lines.append(str(index + 1) + ': ' + span([s.get('height_ft') for s in swells], 2)
                         + ' ft / ' + span([s.get('period_s') for s in swells]) + ' s / '
                         + (', '.join(directions) or 'direction unavailable') + '.')
    lines.append('Tide bands use the bracketing tidal cycle when available; otherwise the daily height range.')
    return '\n'.join(lines)


def build_review_context(report):
    """Return two logical documents; no network, LLM, feedback parsing or state writes."""
    source = report.get('forecast') or {}
    if not isinstance(source, dict) or 'daily' not in source:
        return ('DETAILED SURF ANALYSIS\nSaved forecast data is unavailable for this older draft. '
                'Its recommendations cannot be independently checked from the saved source. '
                'Review the report and any reviewer corrections before approval.',
                'SURFLINE DATA SUMMARY\nNo saved daily Surfline snapshot is available for this older draft. '
                'No measurements have been invented. Use a fresh manual test draft to fetch current data.')
    day = next(d for d in source['daily'] if d['date'] == report['date'])
    intervals = daylight_intervals(day)
    return reasoning(report, intervals), source_summary(report, day, intervals)
