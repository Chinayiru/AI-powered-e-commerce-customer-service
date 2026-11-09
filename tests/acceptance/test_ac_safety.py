"""AC16 / AC25：回放与审计脱敏。"""
from __future__ import annotations

import json

import app.cli as cli
from app.core.redact import audit_view, mask_address, mask_phone, redact_text


# ---------------------------------------------------------------- AC16
def test_ac16_replay_uses_the_versions_recorded_in_the_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "RUNS", tmp_path / "runs.jsonl")
    assert cli.main(["run", "--fixture", "tb_1004"]) == 0
    row = json.loads((tmp_path / "runs.jsonl").read_text(encoding="utf-8").strip())

    # 假装当前默认策略已经升到新版本：回放不得追新，只能用 run 里记录的旧版本
    stale = cli.default_policy()
    stale.version = "9999.9.9"
    monkeypatch.setattr(cli, "default_policy", lambda: stale)

    capsys.readouterr()
    assert cli.main(["replay", "--run-id", row["run_id"]]) == 0
    out = capsys.readouterr().out
    assert f"policy_version={row['policy_version']}" in out
    assert "9999.9.9" not in out
    assert "drift: none" in out


# ---------------------------------------------------------------- AC25
def test_ac25_audit_lines_are_masked():
    assert mask_phone("联系我 13812348000 谢谢") == "联系我 138****8000 谢谢"
    assert mask_phone("订单号 202611090001 不是手机号") == "订单号 202611090001 不是手机号"
    assert mask_address("浙江省杭州市西湖区文三路 100 号 3 幢 502 室") == "浙江省杭州市西湖区********"
    assert "文三路" not in mask_address("浙江省杭州市西湖区文三路 100 号 3 幢 502 室")

    rec = audit_view({"ticket_text": "手机 13812348000", "address": "浙江省杭州市西湖区文三路 100 号"})
    assert rec["ticket_text"] == "手机 138****8000"
    assert rec["address"] == "浙江省杭州市西湖区********"
    assert redact_text("身份证 110101199003071234") == "身份证 110101********1234"
