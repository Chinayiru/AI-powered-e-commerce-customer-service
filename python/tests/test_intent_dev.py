"""Business regression cases from the editable dev set, separate from holdout."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent import AgentService
from app.contracts import AskRequest
from app.intent import classify

DEV_PATH = Path(__file__).resolve().parents[1] / 'eval' / 'dev_v1.jsonl'
CASES = [json.loads(line) for line in DEV_PATH.read_text(encoding='utf-8').splitlines() if line.strip()]


@pytest.mark.parametrize('case', CASES, ids=[case['id'] for case in CASES])
def test_development_intent_and_business_action(case, settings, fake_tools):
    if not case.get('agent_only'):
        classified = classify(case['message'])
        assert classified.intent.value == case['gold_intent']
        assert classified.conditional == case.get('conditional', False)

    request = AskRequest(
        traceId=f"dev-{case['id']}", ticketId=f"T-{case['id']}",
        requestId='00000000-0000-4000-8000-000000000001', attempt=0, taskEpoch=0,
        userId='U001', category='AFTERSALE', message=case['message'],
    )
    response = AgentService(settings, fake_tools).answer(request)
    assert response.intent.value == case['gold_intent']
    if case.get('gold_transfer_reason'):
        assert response.transferReason.value == case['gold_transfer_reason']
        assert response.needHumanReview is True
    if case['gold_intent'] == 'REFUND_REQUEST':
        assert response.suggestedAction.action.value == 'REFUND'
        assert response.suggestedAction.needHumanConfirm is True
        assert response.replyType.value == 'DECISIONAL'
    else:
        # Eligibility questions, denials and human requests must never
        # silently become refund instructions.
        assert response.suggestedAction is None


@pytest.mark.parametrize(('accuracy', 'correct', 'expected_exit'), [
    (0.825, 33, 1), (0.85, 34, 0), (1.0, 34, 1),
])
def test_quality_gate_keeps_threshold_and_validates_counts(tmp_path, accuracy, correct, expected_exit):
    import subprocess
    import sys

    report = tmp_path / 'qc.json'
    report.write_text(json.dumps({'qc02_intent': {
        'accuracy_5class': accuracy, 'correct_5class': correct, 'total_5class': 40,
    }}), encoding='utf-8')
    gate = Path(__file__).resolve().parents[2] / 'scripts' / 'check_eval_gate.py'
    completed = subprocess.run([sys.executable, str(gate), str(report)], capture_output=True)
    assert completed.returncode == expected_exit
