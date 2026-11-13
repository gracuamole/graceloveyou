"""Trim completed report detail, never active work, memory or uncertain sends."""
from datetime import date, timedelta
import hashlib
import json


def trim_completed(data, today):
    cutoff = (date.fromisoformat(today) - timedelta(days=7)).isoformat()
    removed = 0
    for target, report in data.get('reports', {}).items():
        if (target >= cutoff or report.get('status') not in ('published', 'expired')
                or report.get('intent') or report.get('details_trimmed')):
            continue
        report['archived_parts_sha256'] = hashlib.sha256(
            json.dumps(report['parts'], ensure_ascii=False).encode()).hexdigest()
        for field in ('forecast', 'feedback', 'feedback_log', 'pending_feedback', 'review_history',
                      'publication_history', 'recovery_history', 'remembered_feedback', 'rebuild_feedback',
                      'analysis_parts', 'source_parts', 'approval', 'edit_failures', 'edit_call_budgets'):
            report.pop(field, None)
        report['parts'] = ['Archived report details; publication record retained.']
        report['details_trimmed'] = True
        removed += 1
    # Remembered instructions and global Telegram offset/tombstones are never removed.
    return removed
