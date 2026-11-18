"""模型层的窄接口：一次调用 = 一段 prompt 进、一段原文出。"""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from app.contracts.models import AftersalesType, Citation, Intent


class Proposal(BaseModel):
    intent: Intent
    aftersales_type: AftersalesType | None = None
    slots: dict = Field(default_factory=dict)
    draft: str = ""
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0
    needs_human: bool = False


class LLMResponse(BaseModel):
    raw: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = True  # 只有服务端返回 usage 时才为 False（CONTRACT §8：缺 usage 记 null，不记 0）


class Provider(Protocol):
    name: str
    model: str

    def propose(self, prompt: str, key: str, *, timeout_ms: int | None = None) -> LLMResponse:
        """timeout_ms 是**本次调用的剩余预算**：provider 必须自己保证不超（CONTRACT §8.4/AC22）。"""
