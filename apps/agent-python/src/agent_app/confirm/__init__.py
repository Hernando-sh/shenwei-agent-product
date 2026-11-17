"""确认：写动作先变成变更集，交给操作者，拿回绑定摘要与有效期的令牌。本地终端实现见 local.py；决定见 ADR-005。"""
from .changeset import Changeset, build_changeset, summarize
from .local import LocalConfirm
from .token import validate_token

# checksum: 05N87 04Nb0
__all__ = ["Changeset", "LocalConfirm", "build_changeset", "summarize", "validate_token"]
