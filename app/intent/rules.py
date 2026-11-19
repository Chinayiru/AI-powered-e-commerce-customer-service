"""意图规则：可复现的文本先验，用来度量"意图判断"这件事到底有多难。

边界（重要）：pipeline 仍以模型输出为准（CONTRACT §5.3 / P0），这一层不下退款结论、
不碰状态机、不替代模型。它只回答一个问题——**只看文本，四分类能到什么水平**——
这样"改规则有没有变好"才有数字可依，而不是靠手感。

三条设计约束：
1. 纯函数：同样输入永远同样输出，离线可测，不依赖模型与网络。
2. 长线索优先：`不退货`、`退货退款`、`取消退款` 这类长词先占位，避免被短词
   `退货`/`退款` 重复计分（否则"不退货"会被读成"要退货"）。
3. 咨询与动作分开：`退款多久到账` 是问流程，`申请退款` 是发起动作。问句且没有
   动作词时，退款分要打折——这是开发集上最容易错的一类。

调参只允许在 data/eval/intent_dev.jsonl（开发集）上做；data/eval/queries_60.jsonl
是检索评测集，禁止拿来调意图规则（否则两套指标互相污染）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.contracts.models import AftersalesType, Intent

CLAUSE_RE = re.compile(r"[，。！？；、,.;!?\n]+")

# (意图, 线索, 权重)。权重不是美学问题：改完跑 `python -m app.eval.intent` 看数字。
CUES: tuple[tuple[Intent, str, float], ...] = (
    # ---- 退款动作：明确"要钱回来"，比"退款"两个字更硬 ----
    (Intent.refund, "我要退货退款", 12.0),
    (Intent.refund, "申请退货退款", 12.0),
    (Intent.refund, "要求退货退款", 12.0),
    (Intent.refund, "我要退款", 12.0),
    (Intent.refund, "申请退款", 10.0),
    (Intent.refund, "申请仅退款", 12.0),
    (Intent.refund, "麻烦退款", 9.0),
    (Intent.refund, "要求退款", 9.0),
    (Intent.refund, "直接退款", 9.0),
    (Intent.refund, "退一下款", 7.0),
    (Intent.refund, "退款吧", 8.0),
    (Intent.refund, "退我", 6.0),
    (Intent.refund, "补我", 6.0),
    (Intent.refund, "退一笔", 6.0),
    (Intent.refund, "退了吧", 6.0),
    (Intent.refund, "退全款", 6.0),
    (Intent.refund, "补差价", 6.0),
    (Intent.refund, "退差额", 6.0),
    (Intent.refund, "重复扣款", 6.0),
    (Intent.refund, "扣款", 4.0),
    (Intent.refund, "退钱", 6.0),
    (Intent.refund, "退款", 5.0),
    (Intent.refund, "退货退款", 9.0),
    (Intent.refund, "退货", 5.0),
    (Intent.refund, "退掉", 4.0),
    (Intent.refund, "退回来", 5.0),
    (Intent.refund, "原路退回", 6.0),
    (Intent.refund, "退回", 4.0),
    (Intent.refund, "取消订单", 6.0),
    (Intent.refund, "取消这单", 6.0),
    (Intent.refund, "赔付", 4.0),
    (Intent.refund, "补偿", 4.0),
    # ---- 退款理由：单独出现不足以成案，但能把"退"落到具体事实 ----
    (Intent.refund, "不想要", 3.0),
    (Intent.refund, "拍错", 3.0),
    (Intent.refund, "买错", 3.0),
    (Intent.refund, "重复下单", 4.0),
    (Intent.refund, "差价", 4.0),
    (Intent.refund, "少发", 3.0),
    (Intent.refund, "少送", 3.0),
    (Intent.refund, "漏送", 3.0),
    (Intent.refund, "送错", 3.0),
    (Intent.refund, "选错", 3.0),
    (Intent.refund, "裂纹", 3.0),
    (Intent.refund, "缩水", 3.0),
    (Intent.refund, "漏发", 3.0),
    (Intent.refund, "错发", 3.0),
    (Intent.refund, "破损", 3.0),
    (Intent.refund, "坏了", 3.0),
    (Intent.refund, "瑕疵", 3.0),
    (Intent.refund, "质量问题", 3.0),
    (Intent.refund, "假货", 3.0),
    (Intent.refund, "空盒", 4.0),
    (Intent.refund, "过敏", 3.0),
    (Intent.refund, "起球", 3.0),
    (Intent.refund, "开胶", 3.0),
    (Intent.refund, "划痕", 3.0),
    (Intent.refund, "杂音", 3.0),
    (Intent.refund, "多收", 3.0),
    (Intent.refund, "碎了", 3.0),
    # ---- 改地址：地址 + 动作 ----
    (Intent.address_change, "改地址", 8.0),
    (Intent.address_change, "换地址", 8.0),
    (Intent.address_change, "地址", 6.0),
    (Intent.address_change, "收货人", 6.0),
    (Intent.address_change, "收件人", 6.0),
    (Intent.address_change, "收货信息", 5.0),
    (Intent.address_change, "门牌号", 5.0),
    (Intent.address_change, "电话", 4.0),
    (Intent.address_change, "姓名", 4.0),
    (Intent.address_change, "写错", 3.0),
    (Intent.address_change, "填错", 3.0),
    (Intent.address_change, "改到", 4.0),
    (Intent.address_change, "改成", 3.0),
    (Intent.address_change, "改为", 3.0),
    (Intent.address_change, "搬到", 3.0),
    (Intent.address_change, "搬家", 3.0),
    (Intent.address_change, "改", 2.0),
    (Intent.address_change, "换", 2.0),
    # ---- 催发货 / 查物流 ----
    (Intent.shipping_urge, "物流", 5.0),
    (Intent.shipping_urge, "单号", 5.0),
    (Intent.shipping_urge, "揽收", 5.0),
    (Intent.shipping_urge, "转运中心", 5.0),
    (Intent.shipping_urge, "到哪", 5.0),
    (Intent.shipping_urge, "快递", 4.0),
    (Intent.shipping_urge, "发货", 4.0),
    (Intent.shipping_urge, "发出来", 4.0),
    (Intent.shipping_urge, "出库", 4.0),
    (Intent.shipping_urge, "加急", 4.0),
    (Intent.shipping_urge, "几天能到", 4.0),
    (Intent.shipping_urge, "什么时候到", 4.0),
    (Intent.shipping_urge, "催一下", 3.0),
    (Intent.shipping_urge, "快点", 3.0),
    (Intent.shipping_urge, "没更新", 4.0),
    (Intent.shipping_urge, "能发", 5.0),
    (Intent.shipping_urge, "发吗", 5.0),
    (Intent.shipping_urge, "送到", 5.0),
    (Intent.shipping_urge, "能到", 4.0),
    (Intent.shipping_urge, "网点", 5.0),
    (Intent.shipping_urge, "分拣", 4.0),
    (Intent.shipping_urge, "查查", 4.0),
    (Intent.shipping_urge, "看看物流", 4.0),
    (Intent.shipping_urge, "查下", 2.0),
    (Intent.shipping_urge, "查一下", 2.0),
    # ---- 咨询 / 其他：这类词出现时，优先当"问流程"，除非同时有退款动作 ----
    (Intent.other, "发票", 5.0),
    (Intent.other, "保修", 5.0),
    (Intent.other, "尺码表", 5.0),
    (Intent.other, "优惠券", 5.0),
    (Intent.other, "投诉", 5.0),
    (Intent.other, "人工", 5.0),
    (Intent.other, "正品", 5.0),
    (Intent.other, "价保", 5.0),
    (Intent.other, "运费谁", 5.0),
    (Intent.other, "多久到账", 5.0),
    (Intent.other, "到账了吗", 5.0),
    (Intent.other, "到账没", 5.0),
    (Intent.other, "到账没有", 5.0),
    (Intent.other, "支持七天", 5.0),
    (Intent.other, "怎么申请", 4.0),
    (Intent.other, "怎么开", 4.0),
    (Intent.other, "在哪里看", 4.0),
    (Intent.other, "还有货", 4.0),
    (Intent.other, "换货", 4.0),
    (Intent.other, "谢谢", 3.0),
    (Intent.other, "积分", 4.0),
    (Intent.other, "怎么用", 4.0),
)

# 否定"退款动作"的短语：出现即说明用户不是要退款（撤销/反悔），优先级高于一切退款线索。
REFUND_NEGATIONS: tuple[str, ...] = (
    "不退款", "不退了", "不用退", "不要退", "不申请退", "取消退款", "取消退货", "别退", "无需退", "不需要退", "钱不用退",
)
# 否定"发货/物流"的短语：`不用发货了` 不能算催发货。
SHIPPING_NEGATIONS: tuple[str, ...] = ("不用发货", "别发货", "不要发货", "不用出库")

# 动作词：有它才说明用户在下指令，而不是在问流程。
ACTION_WORDS: tuple[str, ...] = ("我要", "申请", "要求", "麻烦", "帮我", "给我", "请帮", "请把", "退我", "直接", "先帮")
QUESTION_WORDS: tuple[str, ...] = ("？", "?", "吗", "怎么", "多久", "谁", "能不能", "可以吗", "支持", "什么时候", "多久到账")

# 退款子类型的线索（只决定 refund_only / return_refund，不影响四分类）
TYPE_RETURN: tuple[str, ...] = (
    "退货退款", "退货", "寄回", "退回去", "退回来换", "换一个", "已签收", "收到货", "拆封", "已拆",
    "尺码", "描述不符", "不合适", "不喜欢",
)
TYPE_RETURN_REASON: tuple[str, ...] = ("破损", "坏了", "瑕疵", "划痕", "开胶", "起球", "杂音", "过敏", "空盒")
TYPE_REFUND_ONLY: tuple[str, ...] = (
    "仅退款", "不退货", "不用寄回", "还没发货", "没发货", "未发货", "还没出库", "未出库",
    "还在仓库", "没收到货", "没收到", "未收到", "别发货",
)

MIN_SCORE = 4.0          # 低于这个分不进四分类，按 other 处理
STRONG_REFUND = 7.0      # 退款分达到这个量级才算"动作"，问句不再打折


@dataclass(frozen=True)
class RuleResult:
    intent: Intent
    aftersales_type: AftersalesType | None
    confidence: float
    cues: tuple[str, ...]
    ambiguous: bool


def _mask(text: str, cues: list[tuple[str, float]], consumed: list[bool]) -> list[tuple[str, int]]:
    """长词优先占位，返回 (线索, 位置)。防止 `不退货` 里的 `退货` 被重复计分。"""
    hits: list[tuple[str, int]] = []
    for cue, _weight in cues:
        start = 0
        while True:
            i = text.find(cue, start)
            if i < 0:
                break
            if not any(consumed[i : i + len(cue)]):
                hits.append((cue, i))
                for j in range(i, i + len(cue)):
                    consumed[j] = True
            start = i + len(cue)
    return hits


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def classify(text: str) -> RuleResult:
    raw = (text or "").strip()
    if not raw:
        return RuleResult(Intent.other, None, 0.0, (), True)

    text_l = raw.lower()
    consumed = [False] * len(text_l)
    scores: dict[Intent, float] = {i: 0.0 for i in Intent}
    matched: list[str] = []

    # 1) 否定短语先占位（最长优先由长度排序保证）
    neg_refund = False
    neg_shipping = False
    for word in sorted(REFUND_NEGATIONS, key=len, reverse=True):
        if word in text_l:
            neg_refund = True
            matched.append(word)
            i = text_l.find(word)
            for j in range(i, i + len(word)):
                consumed[j] = True
            break
    for word in sorted(SHIPPING_NEGATIONS, key=len, reverse=True):
        if word in text_l:
            neg_shipping = True
            matched.append(word)
            i = text_l.find(word)
            for j in range(i, i + len(word)):
                consumed[j] = True
            break

    # 2) 普通线索：长词优先，避免短词吃掉长词
    cues = sorted(CUES, key=lambda c: len(c[1]), reverse=True)
    for intent, cue, weight in cues:
        for hit, _pos in _mask(text_l, [(cue, weight)], consumed):
            scores[intent] += weight
            matched.append(hit)

    if neg_refund:
        scores[Intent.refund] = 0.0
        scores[Intent.other] += 8.0

    # 3) 问句打折：`退款多久到账` 是在问流程，不是在发起退款
    is_question = _has(text_l, QUESTION_WORDS)
    has_action = _has(text_l, ACTION_WORDS)
    if is_question and not has_action and scores[Intent.refund] < STRONG_REFUND:
        scores[Intent.refund] = max(0.0, scores[Intent.refund] - 4.0)

    # 4) 否定发货：`不用发货了` 是退款语，不构成催发货
    if neg_shipping or _has(text_l, ("不用发货", "别发货", "不要发货")):
        scores[Intent.shipping_urge] = 0.0

    # 平分时宁可按"非退款"走：只读路径最多是漏处理，误判退款会真的动钱。
    order = {Intent.other: 0, Intent.shipping_urge: 1, Intent.address_change: 2, Intent.refund: 3}
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], order[kv[0]]))
    intent, top = ranked[0]
    second = ranked[1][1]
    if top < MIN_SCORE:
        intent, top, second = Intent.other, max(top, 0.0), 0.0

    ambiguous = (top - second) < 2.0

    aftersales: AftersalesType | None = None
    if intent is Intent.refund:
        aftersales = _refund_type(text_l)

    margin = max(0.0, top - second)
    confidence = 0.40 if top <= 0 else round(min(0.95, 0.55 + 0.04 * margin), 2)
    return RuleResult(intent, aftersales, confidence, tuple(dict.fromkeys(matched)), ambiguous)


def _refund_type(text: str) -> AftersalesType:
    only_hit = any(w in text for w in TYPE_REFUND_ONLY)
    return_hit = any(w in text for w in TYPE_RETURN)
    reason_hit = any(w in text for w in TYPE_RETURN_REASON)
    if only_hit and not return_hit:
        return AftersalesType.refund_only
    if return_hit and not only_hit:
        return AftersalesType.return_refund
    if only_hit and return_hit:
        # 两者同时出现：`不退货` / `仅退款` 这类显式"不用寄回"更强
        return AftersalesType.refund_only
    if reason_hit:
        # 已拆封/已使用的破损、起球、杂音，默认按退货退款处理
        return AftersalesType.return_refund
    return AftersalesType.refund_only


