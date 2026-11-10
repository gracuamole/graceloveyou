"""Keep reviewer decisions scoped to the exact observed conditions."""
import json
from datetime import datetime
from recommendations import BALI, TIERS, batu_recommend, daylight_intervals, rounded_tide, wind_kmh, positive, number, is_batu_bolong


def condition(row, tide):
    energy = (row.get('energy') or {}).get('nearshore')
    rating = (row.get('rating') or {}).get('key')
    speed = wind_kmh((row.get('wind') or {}).get('speed_kts'))
    height = row.get('surf_max_ft')
    if not (tide and number(tide.get('height_m')) and positive(energy) and rating and speed is not None and positive(height)):
        return None
    # The previous tide, rating and height rules resolve known combinations.
    # A new, nonempty provider rating has no defined tier policy.
    if not positive(row.get('surf_min_ft')) or row['surf_min_ft'] > height or str(rating).upper() in {'UNKNOWN','N/A','UNAVAILABLE'}:
        return None
    if all(batu_recommend(row, tide, tier)['status'] != 'unknown' for tier in TIERS):
        return None
    return dict(tide_m=rounded_tide(tide['height_m']), energy_kj=energy, rating=rating,
                wind_kmh=speed, surf_max_ft=height)


def attach_rules(report, rules):
    if not is_batu_bolong(report.get('name', '')):
        return None
    day = next((d for d in report['forecast'].get('daily', []) if d['date'] == report['date']), None)
    if not day or not day.get('sunlight') or 'weather' in report['forecast'].get('missing_inputs', []):
        return None
    if rules:
        day['reviewer_rules'] = rules.copy()
    for interval in daylight_intervals(day, report['name']):
        case = condition(interval['row'], interval['tide'])
        if case and json.dumps(case, sort_keys=True) not in rules:
            return case
    return None


def question(report, case, clarification=False):
    day = next(d for d in report['forecast']['daily'] if d['date'] == report['date'])
    hours = [datetime.fromtimestamp(i['start'], BALI).strftime('%H:%M')
             for i in daylight_intervals(day, report['name']) if condition(i['row'], i['tide']) == case]
    intro = 'Please tell me which levels can surf: beginner, intermediate, advanced, or none.\n' if clarification else ''
    return (f"@Leonardosinaga\n\n{intro}On {report['date']} at {', '.join(hours)}, Surfline says "
            f"{case['rating']}. The tide is {case['tide_m']} m, wave energy is {case['energy_kj']} kJ, "
            f"wind is {case['wind_kmh']} km/h and waves reach {case['surf_max_ft']} ft.\n\n"
            "what should the forecast for this data be? reply THIS message with your answer.")


def interpret(case, answer):
    from review_bot import gemini_request
    prompt = ('Interpret the reviewer answer for exactly these observed conditions. Return only JSON '
              'with key tiers and an array of allowed levels: beginner, intermediate, advanced. '
              'Use an empty array for explicitly none. If uncertain, or extra restrictions cannot be '
              'represented by those levels, return {"tiers":null}. Do not guess.')
    raw = gemini_request(prompt, json.dumps({'conditions': case, 'answer': answer}))
    try:
        tiers = json.loads(raw)['tiers']
    except (KeyError, TypeError, ValueError):
        return None
    return tiers if isinstance(tiers, list) and all(t in TIERS for t in tiers) else None
