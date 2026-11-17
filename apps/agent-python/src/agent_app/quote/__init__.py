"""报价：草案（只从 ERP 返回构造）与前置规则（程序执行，算价前按固定顺序判）。规格见 docs/specs/w02-quote.md 第 3、4 节；决定见 ADR-004。"""
from .draft import QuoteDraft, canonical_lines, lines_digest, normalize_lines
from .rules import RULE_ORDER, RuleHit, check_customer_master, check_customer_status, check_duplicate, check_overdue

__all__ = ["QuoteDraft", "RULE_ORDER", "RuleHit", "check_customer_master", "check_customer_status", "check_duplicate", "check_overdue", "canonical_lines", "lines_digest", "normalize_lines"]
