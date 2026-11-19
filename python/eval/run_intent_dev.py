"""Evaluate the editable intent development set; never load the holdout set."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from run_eval import AgentService, DemoFakeTools, load_cases, make_settings, qc02_intent, run_once
from app.intent import RULES_VERSION, classify


def evaluate(path: Path) -> dict:
    cases = load_cases(path)
    if not cases or len({case['id'] for case in cases}) != len(cases):
        raise ValueError('Development cases must be nonempty and have unique IDs')
    counts = Counter(case['gold_intent'] for case in cases)
    if any(counts[name] < 10 for name in ('REFUND_REQUEST', 'REFUND_ELIGIBILITY', 'LOGISTICS', 'POLICY', 'OTHER')):
        raise ValueError('Each of the five scored intents needs at least ten development cases')
    classifier_errors = []
    for case in cases:
        if case.get('agent_only'):
            continue
        result = classify(case['message'])
        if (result.intent.value != case['gold_intent']
                or (case.get('gold_transfer_reason') and (
                    result.transfer_reason is None
                    or result.transfer_reason.value != case['gold_transfer_reason']))
                or result.conditional != case.get('conditional', False)):
            classifier_errors.append({'id': case['id'], 'gold': case['gold_intent'],
                                      'pred': result.intent.value, 'conditional': result.conditional,
                                      'message': case['message']})
    rows = run_once(AgentService(make_settings(), DemoFakeTools()), cases)
    agent_errors = [
        {'id': row['id'], 'gold': row['gold_intent'], 'pred': row['intent'],
         'reason': row['transfer_reason'], 'message': row['message']}
        for row in rows
        if row['intent'] != row['gold_intent']
        or (row['gold_transfer_reason'] and row['transfer_reason'] != row['gold_transfer_reason'])
    ]
    return {'dataset': path.name, 'rules_version': RULES_VERSION,
            'dataset_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'case_count': len(cases), 'class_counts': dict(counts), 'qc02_intent': qc02_intent(rows),
            'classifier_errors': classifier_errors, 'agent_errors': agent_errors,
            'pass': not classifier_errors and not agent_errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=Path(__file__).with_name('dev_v1.jsonl'))
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    report = evaluate(args.dataset)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.json:
        args.json.write_text(output + '\n', encoding='utf-8')
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
