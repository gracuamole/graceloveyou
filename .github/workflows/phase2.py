"""Opt-in Phase 2 entry point. Preview by default; existing scripts unchanged."""
import argparse
import json
from datetime import datetime, timedelta
from recommendations import BALI, render_day


def build_blocks(forecast, target, name):
    day = next((d for d in forecast.get('daily', []) if d.get('date') == target), None)
    if day is None:
        raise ValueError(f'Forecast unavailable for {target}')
    return render_day(day, name)


def chunks(blocks, limit=3900):
    messages, current = [], ''
    for block in blocks:
        if len(block) > limit:
            raise ValueError('Interval exceeds Telegram message limit')
        if current and len(current) + len(block) + 2 > limit:
            messages.append(current)
            current = ''
        current += ('\n\n' if current else '') + block
    if current:
        messages.append(current)
    return messages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', action='store_true')
    parser.add_argument('--fixture', help='Normalized surf-mcp JSON for offline preview')
    parser.add_argument('--date', default=(datetime.now(BALI) + timedelta(days=1)).date().isoformat())
    args = parser.parse_args()
    if args.send and not args.fixture:
        parser.error('Direct publishing disabled; use review_bot.py for Leo approval')
    transport = None
    if args.fixture:
        if args.send:
            parser.error('Fixture data cannot be posted')
        with open(args.fixture) as source:
            forecast = json.load(source)
        name = "Old Man's / Batu Bolong"
    else:
        import main4_pkge_indi as transport
        transport.cache.clear()
        forecast = transport.fetch_full_forecast(transport.SPOT_ID, days=3)
        name = transport.SPOT_NAME
    messages = chunks(build_blocks(forecast, args.date, name))
    for message in messages:
        print(message + '\n')
    print('PREVIEW ONLY — nothing sent.')


if __name__ == '__main__':
    main()
