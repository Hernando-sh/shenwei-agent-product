"""测试替身：只验证程序控制逻辑，不模拟真实模型的智能。测试与离线演示共用。"""
from .fake_erp import FakeERP
from .fake_knowledge import FakeKnowledge
from .scripted_confirm import ScriptedConfirm, amend, approve, approve_with, no_decision, reject
from .scripted_model import ScriptedModel, final, malformed, tool_calls

__all__ = ["FakeERP", "FakeKnowledge", "ScriptedConfirm", "ScriptedModel", "amend", "approve", "approve_with", "final",
           "malformed", "no_decision", "reject", "tool_calls"]
