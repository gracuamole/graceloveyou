"""Capture the rule engine's evidence at generation; Telegram reads saved text only."""
import json
from datetime import datetime
from difflib import unified_diff
from recommendations import (BALI, TIERS, LOW_RATINGS, daylight_intervals, is_batu_bolong,
                             number, qualifies, report_cautions, rounded_tide, tier_windows,
                             wave_line, wind_kmh)


def clock(timestamp):
    return datetime.fromtimestamp(timestamp, BALI).strftime('%H:%M')


def shown(value):
    return 'unavailable' if value is None else str(value)


def capture(report):
    day = next((d for d in report['forecast'].get('daily', []) if d['date'] == report['date']), None)
    if not day:
        return 'Generation inputs unavailable.'
    try:
        hours = daylight_intervals(day, report['name'])
    except ValueError:
        return 'Daylight inputs unavailable. No complete daylight window could be assessed.\n' + '\n'.join(report['parts'])
    batu = is_batu_bolong(report['name'])
    sun = day['sunlight']
    lines = [f"Spot: {report['name']}. Sunrise {clock(sun['sunrise_ts'])}, sunset {clock(sun['sunset_ts'])}. "
             f"Round sunrise up and sunset down: {clock(hours[0]['start'])}–{clock(hours[-1]['end'])}.",
             'Wave height uses the hourly Surfline surf_human descriptions within daylight.',
             wave_line(hours), '', 'Surfline inputs shared by all levels, by hour',
             'Tide: interpolated metres → nearest 0.1 m (half up). Wind/gust: knots × 1.852 → km/h rounded up.']
    borderline = []
    for hour in hours:
        row = hour['row']
        tide = (hour['tide'] or {}).get('height_m')
        height = rounded_tide(tide) if number(tide) else None
        wind = row.get('wind') or {}
        speed = wind_kmh(wind.get('speed_kts'))
        energy = (row.get('energy') or {}).get('nearshore')
        rating = (row.get('rating') or {}).get('key')
        maximum = row.get('surf_max_ft')
        surf = f"{shown(row.get('surf_min_ft'))}–{shown(maximum)} ft"
        if number(maximum):
            surf += f" (max {maximum * .3048:.3f} m)"
        conversions = [f"{shown(wind.get(k))}→{shown(wind_kmh(wind.get(k)))}" for k in ('speed_kts','gust_kts')]
        time = clock(hour['start'])
        lines.append(f"{time} {shown(row.get('surf_human'))}; {surf}; {shown(rating)}; "
                     f"{shown(energy)} kJ; tide {shown(round(tide, 5) if number(tide) else None)}→{shown(height)} m; "
                     f"wind/gust {' / '.join(conversions)}.")
        if not batu:
            lines.append(f"Tide band: {(hour['tide'] or {}).get('band', 'unavailable')}; "
                         f"swell periods (s): {[s.get('period_s') for s in row.get('swells', [])]}.")
        if batu:
            boundary = []
            if height in (.2,.8):
                boundary.append(f'rounded tide {height} m')
            if number(energy) and any(abs(energy - limit) <= 1 for limit in (60, 80, 400, 1000)):
                boundary.append(f'{energy} kJ')
            if number(maximum) and abs(maximum * .3048 - 2.5) <= .05:
                boundary.append('within 0.05 m of beginner height limit')
            cutoff = 16 if rating in LOW_RATINGS else 20
            if speed in (cutoff-1, cutoff):
                boundary.append(f'rounded wind {speed} km/h at the warning boundary')
            if boundary:
                borderline.append(time + ' ' + ', '.join(boundary))
    if batu and day.get('reviewer_rules'):
        from rule_questions import condition
        for hour in hours:
            case = condition(hour['row'], hour['tide'])
            rule = day['reviewer_rules'].get(json.dumps(case, sort_keys=True)) if case else None
            if rule:
                lines.append(f"{clock(hour['start'])}: matching reviewer rule permits "
                             + (', '.join(rule['tiers']) or 'no tiers') + ', subject to the physical limits.')
    if batu:
        lines.extend(['', 'Rules for all levels: minimum 80 kJ. At rounded tide above 0.2 and below 0.8 m, '
                      '60–400 kJ inclusive qualifies under the low-tide exception. At 0.8 m or higher, minimum 400 kJ. '
                      'At 1000 kJ or higher only advanced qualifies. Very poor excludes all; Poor permits beginner only; '
                      'Poor to fair and better permit all subject to other limits. Wind adds a warning above 15 km/h '
                      'on the three low ratings and at 20 km/h or higher on better ratings.'])
    for tier in TIERS:
        lines.extend(['', tier.upper()])
        if batu:
            lines.append('Inside: breaking surf below 2.5 m and tide at least 0.8 m unless the low-tide exception applies.'
                         if tier == 'beginner' else 'Outside: apply the shared rules; no mid-tide restriction.')
        else:
            lines.append({'beginner':'Inside exception above 2 ft, 600 energy or 12 s; coach checks inside waves.',
                          'intermediate':'Outside limits: 4 ft, 1000 energy and 14 s; mid tide preferred.',
                          'advanced':'Above 4 ft or 1000 energy can mean powerful sets.'}[tier])
        # Use the text actually generated, including incomplete-forecast wording.
        heading = {'beginner': '1️⃣ BEGINNER', 'intermediate': '2️⃣ INTERMEDIATE',
                   'advanced': '3️⃣ ADVANCED'}[tier]
        sections = '\n\n'.join(report['parts']).split('\n\n')
        conclusion = next((section[len(heading) + 1:] for section in sections
                           if section.startswith(heading + '\n')), None)
        lines.extend([conclusion] if conclusion else tier_windows(hours, tier))
        for h in hours:
            advice = h['tiers'][tier]
            notes = advice.get('notes', [])
            if notes or not qualifies(h, tier):
                lines.append(f"{clock(h['start'])}: {advice['status']}. " + ' '.join(notes))
    lines.extend(['', 'Cautions'])
    if batu:
        early = [f"{clock(r['timestamp'])} {shown(wind_kmh((r.get('wind') or {}).get('gust_kts')))}"
                 for r in day.get('hourly', []) if number(r.get('timestamp')) and r['timestamp'] < sun['sunrise_ts']
                 and datetime.fromtimestamp(r['timestamp'], BALI).date().isoformat() == day['date']]
        lines.append('Before sunrise, rounded gust ≥17 km/h triggers choppiness. Gusts (km/h): ' + (', '.join(early) or 'unavailable') + '.')
        lines.append('Windy later: rising wind or gusts with daylight wind ≥17 km/h, or any windy hour. '
                     'Strong currents: qualifying advanced hour with energy ≥1000 kJ.')
        borderline.extend('pre-sunrise gust ' + obs + ' km/h' for obs in early if obs.split()[-1] in ('16','17'))
    else:
        lines.append('For qualifying hours: energy above 600 triggers a current warning; wind above 20 km/h '
                     'triggers a wind warning. Energy below 100 is very low; 100 to below 200 is weak. '
                     'A qualifying beginner inside exception adds a coach caution.')
    lines.extend(report_cautions(hours) or ['No caution triggered.'])
    lines.append('Borderline calls: ' + ('; '.join(borderline) if borderline else 'none flagged') + '.')
    return '\n'.join(lines)


def record_edit(report, old, new, feedback):
    if 'generation_reasoning' not in report or old == new:
        return
    changes = unified_diff('\n\n'.join(old).splitlines(), '\n\n'.join(new).splitlines(), n=0, lineterm='')
    changed = [s for s in list(changes)[2:] if s.startswith(('+','-'))]
    report.setdefault('reasoning_edits', []).append(feedback + '\n' + '\n'.join(changed))


def explanation(reports, date=None):
    if date is None and reports:
        date = max(reports)
    if date not in reports:
        return f'No saved report for {date}.' if date else 'There are no saved reports.'
    report = reports[date]
    saved = report.get('generation_reasoning')
    if not saved:
        return f'{date}: reasoning was not saved when this report was generated.'
    return '\n\n'.join([f'Forecast reasoning for {date}', saved] +
                        ['Reviewer changes since generation:\n' + item for item in report.get('reasoning_edits', [])])
