"""策略层：工具请求通过校验后、执行前的授权决定。表驱动；不在表里的名字一律拒绝。"""
from .table import POLICY_TABLE, Policy, PolicyRule

__all__ = ["POLICY_TABLE", "Policy", "PolicyRule"]
