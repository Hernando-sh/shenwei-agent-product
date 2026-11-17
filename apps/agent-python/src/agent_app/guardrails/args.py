"""参数校验：模型按描述生成参数，不意味着参数可信。调用业务函数前在这里拦。
W1 只校验顶层；2.4 起递归到嵌套对象与数组元素——报价行里的 unit_price 也要在这一层拦（W2-AC-04）。
授权与确认不在这里：在 ToolRuntime 的策略与确认环节。"""
from __future__ import annotations

import json

from agent_app.contracts import ToolFailure, ToolSpec

_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}


def validate_args(spec: ToolSpec, raw_arguments: str) -> dict:
    try:
        args = json.loads(raw_arguments) if raw_arguments.strip() else {}
    except json.JSONDecodeError as e:
        raise ToolFailure("input_error", "invalid_json", f"参数不是有效 JSON：{e.msg}") from e
    if not isinstance(args, dict):
        raise ToolFailure("input_error", "wrong_type", "参数必须是对象")
    return _validate_object(spec.parameters, args, path="")


def _validate_object(schema: dict, args: dict, *, path: str) -> dict:
    props: dict = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in args:
            raise ToolFailure("input_error", "missing_field", f"缺少必填参数 {path}{name}")
    if schema.get("additionalProperties") is False:
        for name in args:
            if name not in props:
                raise ToolFailure("input_error", "unknown_field", f"未定义的参数 {path}{name}")
    out = {}
    for name, value in args.items():
        out[name] = _validate_value(props.get(name, {}), value, path=f"{path}{name}")
    return out


def _validate_value(schema: dict, value, *, path: str):
    expected = _TYPES.get(schema.get("type"))
    if expected and (not isinstance(value, expected) or (expected is int and isinstance(value, bool))):
        raise ToolFailure("input_error", "wrong_type", f"参数 {path} 类型应为 {schema['type']}")
    if isinstance(value, str):
        if not value.strip():
            raise ToolFailure("input_error", "empty_field", f"参数 {path} 不能为空")
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum, maximum = schema.get("minimum"), schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ToolFailure("input_error", "out_of_range", f"参数 {path} 不能小于 {minimum}")
        if maximum is not None and value > maximum:
            raise ToolFailure("input_error", "out_of_range", f"参数 {path} 不能大于 {maximum}")
        return value
    if isinstance(value, list):
        if schema.get("minItems", 0) > len(value) or (schema.get("type") == "array" and not value and schema.get("minItems") is None):
            raise ToolFailure("input_error", "empty_field", f"参数 {path} 不能为空列表")
        items = schema.get("items") or {}
        return [_validate_value(items, v, path=f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, dict) and schema.get("type") == "object":
        return _validate_object(schema, value, path=f"{path}.")
    return value
