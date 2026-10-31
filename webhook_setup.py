"""Explicit manual setup for the free Cloudflare Telegram inbox; never sends chat messages."""
import argparse
import os
import re
from datetime import datetime

from recommendations import BALI
from review_bot import SafeError, Telegram, WebhookInbox, failure_detail, setting, webhook_rejection_hint


def saved_time(value):
    """Worker timestamps are milliseconds; show Bali time without any raw payload."""
    if type(value) not in (int, float) or value <= 0:
        return 'none recorded'
    try:
        return datetime.fromtimestamp(value / 1000, BALI).strftime('%Y-%m-%d %H:%M:%S WITA')
    except (ValueError, OverflowError, OSError):
        return 'unavailable'


def inspect_delivery(telegram):
    info = telegram.call('getWebhookInfo')
    print('Telegram webhook registered: ' + ('yes' if info.get('url') else 'no'))
    print('Telegram pending deliveries: ' + str(int(info.get('pending_update_count', 0))))
    print('Telegram reports a delivery error: ' + ('yes' if info.get('last_error_date') else 'no'))
    if info.get('last_error_date'):
        print('Last reported delivery problem: ' + webhook_rejection_hint(info.get('last_error_message')))
    mode = os.environ.get('SURF_REVIEW_TRANSPORT', '').strip().lower()
    print('GitHub review transport: ' + (mode if mode in ('poll', 'webhook') else 'missing/invalid'))
    enabled = os.environ.get('SURF_REVIEW_ENABLED', '')
    print('GitHub review enabled: ' + (enabled if enabled in ('true', 'false') else 'missing/invalid'))
    if not os.environ.get('SURF_WEBHOOK_URL') or not os.environ.get('SURF_WEBHOOK_TOKEN'):
        print('Worker inbox inspection: shared URL/token not configured in GitHub.')
        return
    inbox = WebhookInbox(setting('SURF_WEBHOOK_URL'), setting('SURF_WEBHOOK_TOKEN'))
    print('Webhook matches configured Worker: ' + ('yes' if info.get('url') == inbox.url + '/telegram' else 'no'))
    status = inbox.call('/status')  # GET only; no acknowledgements or configuration changes.
    print('Worker enabled: ' + ('yes' if status.get('enabled') is True else 'no'))
    pending = status.get('pending')
    print('Worker pending inbox updates: ' + (str(pending) if type(pending) is int else 'unavailable'))
    print('Worker last wakeup timestamp: ' + saved_time(status.get('last_wake_at')))
    print('Worker next retry timestamp: ' + saved_time(status.get('next_wake_at')))
    print('Worker last completed review: ' + saved_time(status.get('last_completed_at')))
    print('Inspection only. No messages, workflow dispatch, acknowledgements or webhook changes.')


def configure(action):
    telegram = Telegram(setting('TELEGRAM_BOT_TOKEN'))
    if action == 'inspect':
        inspect_delivery(telegram)
        return
    if os.environ.get('SURF_REVIEW_ENABLED') != 'false':
        raise SafeError('First set SURF_REVIEW_ENABLED=false and wait for running review jobs to finish.')
    if action == 'disable':
        telegram.call('deleteWebhook', drop_pending_updates=False)
        print('Webhook removed without dropping pending Telegram updates. Reconcile any Cloudflare inbox before switching to polling.')
        return
    if os.environ.get('SURF_REVIEW_TRANSPORT') != 'webhook':
        raise SafeError('Set SURF_REVIEW_TRANSPORT=webhook before enabling the webhook.')
    secret = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', secret):
        raise SafeError('TELEGRAM_WEBHOOK_SECRET must be 32-256 letters, digits, underscores or hyphens.')
    inbox = WebhookInbox(setting('SURF_WEBHOOK_URL'), setting('SURF_WEBHOOK_TOKEN'))
    if not inbox.call('/status').get('enabled'):
        raise SafeError('Enable WEBHOOK_ENABLED=true on the configured Cloudflare Worker first.')
    info = telegram.call('getWebhookInfo')
    expected = inbox.url + '/telegram'
    if info.get('url') not in ('', expected):
        raise SafeError('A different Telegram webhook is active. Resolve the existing integration before replacing it.')
    telegram.call('setWebhook', url=expected, secret_token=secret, max_connections=1,
                  allowed_updates=['message'], drop_pending_updates=False)
    if telegram.call('getWebhookInfo').get('url') != expected:
        raise SafeError('Webhook registration did not match the expected Worker endpoint.')
    print('Webhook registered and verified. No Telegram chat message or LLM request was sent.')
    print('Set SURF_REVIEW_ENABLED=true to allow the existing workflow to process saved replies.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', choices=['inspect', 'enable', 'disable'], default='inspect')
    args = parser.parse_args()
    configure(args.action)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Webhook setup stopped safely: ' + failure_detail(error))
        raise SystemExit(1)
