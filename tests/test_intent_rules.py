"""意图规则的单元测试：不依赖开发集，钉住每一条规则的理由。

这里刻意不做"再跑一遍开发集"的事——那是 tests/test_intent_dev.py 的职责。
本文件只回答：否定、问句、长词掩码、平分、子类型这些**规则机理**是否还成立。
"""
from __future__ import annotations

from app.contracts.models import AftersalesType, Intent
from app.intent.rules import classify


def test_empty_text_is_other_with_no_confidence() -> None:
    res = classify("   ")
    assert res.intent is Intent.other
    assert res.aftersales_type is None
    assert res.confidence == 0.0
    assert res.ambiguous is True


def test_plain_refund_action() -> None:
    res = classify("麻烦退我 20 元差价。")
    assert res.intent is Intent.refund
    assert res.aftersales_type is AftersalesType.refund_only
    assert res.ambiguous is False


def test_negated_refund_is_not_refund() -> None:
    for text in ("算了，不退款了，东西我留着。", "取消退款申请，我不退了。", "钱不用退了，帮我改成换货。"):
        res = classify(text)
        assert res.intent is Intent.other, text
        assert res.aftersales_type is None


def test_consultation_about_refund_is_other() -> None:
    # 问"多久到账"是在问流程，不是发起退款；问句且无动作词要打折。
    assert classify("退款一般多久到账？").intent is Intent.other
    assert classify("退货的运费谁承担？").intent is Intent.other


def test_refund_plus_question_but_with_action_still_refund() -> None:
    # 有"麻烦/帮我"这类动作词，就按发起退款处理，不因子句是问句而吞掉。
    assert classify("这个坏了，麻烦帮我退款。").intent is Intent.refund


def test_long_cue_masks_short_cue() -> None:
    # "不退货"必须先占位，否则会被"退货"读成退货退款。
    res = classify("我只要退款，不退货。")
    assert res.intent is Intent.refund
    assert res.aftersales_type is AftersalesType.refund_only


def test_unshipped_implies_refund_only() -> None:
    res = classify("还没发货，我不想要了，申请退款。")
    assert res.intent is Intent.refund
    assert res.aftersales_type is AftersalesType.refund_only


def test_received_goods_with_damage_implies_return() -> None:
    res = classify("收到货就是坏的，屏幕碎了，退货退款。")
    assert res.intent is Intent.refund
    assert res.aftersales_type is AftersalesType.return_refund


def test_shipping_negation_does_not_become_urge() -> None:
    # "不用发货了"是退款语，不是催发货。
    res = classify("东西还没出库，不用发货了，退款。")
    assert res.intent is Intent.refund


def test_address_change_wins_when_only_address_cues() -> None:
    res = classify("地址填错了，改成幸福小区 3 栋 502。")
    assert res.intent is Intent.address_change
    assert res.aftersales_type is None


def test_tie_prefers_non_refund() -> None:
    # 平分时宁可按只读路径走：漏处理可以补，误判退款会真的动钱。
    # 两分都是 5 分（退款 5 / 发票 5），平分判 other 并标记 ambiguous。
    res = classify("退款、发票")
    assert res.intent is Intent.other
    assert res.ambiguous is True


def test_refund_arrival_question_is_other_but_not_ambiguous() -> None:
    # `退款到账了吗` 有明确的咨询线索（到账了吗 5），退款分被打折，"other" 是稳的、不是平票。
    res = classify("退款到账了吗？")
    assert res.intent is Intent.other
    assert res.ambiguous is False


def test_confidence_is_bounded_and_cues_are_substrings() -> None:
    for text in ("退款", "地址改一下", "物流到哪了", "发票怎么开", "随便说点什么"):
        res = classify(text)
        0.0 <= res.confidence <= 0.95
        for cue in res.cues:
            assert cue in text, (cue, text)


def test_rules_module_does_not_touch_pipeline() -> None:
    # 规则层是离线先验：不许被 pipeline 反向依赖，否则"模型输出为准"的边界就破了。
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    rules_src = (root / "app" / "intent" / "rules.py").read_text(encoding="utf-8")
    pipeline_src = (root / "app" / "core" / "pipeline.py").read_text(encoding="utf-8")
    assert "app.core.pipeline" not in rules_src
    assert "app.intent" not in pipeline_src
