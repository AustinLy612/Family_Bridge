"""Prompt rendering helpers (Plan §5.4 "Prompt registry"; Phase 4 task 2).

- `output_format(model, language)`: the output-format block generated from the Pydantic schema
  (field names, types, allowed values, limits). Descriptive, not a raw JSON Schema dump: the
  DBT_Revised work found that injected JSON Schema makes models echo `"type": "object"`.
- `render(template, values)`: fills `{{name}}` placeholders; unknown names fail loudly.
- `as_data(text, language)`: wraps participant free text so the model treats it as data.
- `fill_fallback(...)`: turns an authored fallback `output` into a validated output instance.
"""

from __future__ import annotations

import json
import re
import types
import typing
from typing import Any, Literal, get_args, get_origin

from annotated_types import MaxLen, MinLen
from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from app.ai.schemas import SERVER_FIELDS

_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")

WORDS = {
    "zh-CN": {
        "string": "字符串",
        "int": "整数",
        "bool": "true 或 false",
        "list": "数组",
        "of": "，每项为",
        "object": "对象",
        "one_of": "取值之一",
        "max_chars": "最多{n}字",
        "items": "{a}到{b}项",
        "empty_ok": "可为空字符串",
        "range": "{a}到{b}",
        "head": (
            "【输出格式】只输出一个JSON对象：以{开头、以}结尾。不要markdown代码块，不要解释文字，"
            '不要思考过程，不要JSON Schema元数据（例如 "type": "object"）。字段如下：'
        ),
        "stream_head": (
            "【输出格式】先直接输出给学生看的教学内容（自然的中文段落，不要JSON，不要Markdown符号）。"
            "最后单独一行附上元数据注释：<!--META:{...}-->，其中是合法JSON，字段如下："
        ),
    },
    "en": {
        "string": "string",
        "int": "integer",
        "bool": "true or false",
        "list": "array",
        "of": " of ",
        "object": "object",
        "one_of": "one of",
        "max_chars": "at most {n} characters",
        "items": "{a}-{b} items",
        "empty_ok": "may be an empty string",
        "range": "{a} to {b}",
        "head": (
            "[Output format] Return exactly one JSON object, starting with { and ending with }. "
            "No markdown code fences, no explanation, no reasoning, no JSON Schema metadata "
            '(such as "type": "object"). Fields:'
        ),
        "stream_head": (
            "[Output format] First write the teaching message for the student as plain paragraphs "
            "(no JSON, no Markdown symbols). Then, on its own last line, add one metadata "
            "comment <!--META:{...}--> containing valid JSON with these fields:"
        ),
    },
}


def _limits(info: FieldInfo | None, metadata: list[Any]) -> tuple[int | None, int | None]:
    lo = hi = None
    for m in [*(info.metadata if info else []), *metadata]:
        if isinstance(m, MinLen):
            lo = m.min_length
        elif isinstance(m, MaxLen):
            hi = m.max_length
        elif hasattr(m, "max_length") and getattr(m, "max_length", None) is not None:
            hi = m.max_length
            lo = getattr(m, "min_length", lo)
    return lo, hi


def _describe(annotation: Any, info: FieldInfo | None, w: dict[str, str], indent: str) -> str:
    origin = get_origin(annotation)
    if origin is typing.Annotated:
        base, *meta = get_args(annotation)
        lo, hi = _limits(None, meta)
        desc = _describe(base, None, w, indent)
        if base is str and hi:
            desc += ", " + w["max_chars"].format(n=hi)
            if lo == 0:
                desc += ", " + w["empty_ok"]
        return desc
    if origin is Literal:
        return w["one_of"] + " " + " | ".join(json.dumps(a) for a in get_args(annotation))
    if origin in (typing.Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        return _describe(args[0], info, w, indent)
    if origin is list:
        (item,) = get_args(annotation)
        lo, hi = _limits(info, [])
        desc = w["list"]
        if lo is not None or hi is not None:
            desc += " (" + w["items"].format(a=lo or 0, b=hi if hi is not None else "n") + ")"
        if isinstance(item, type) and issubclass(item, BaseModel):
            return desc + ", " + w["object"] + ":\n" + _fields(item, w, indent + "  ")
        return desc + w["of"] + _describe(item, None, w, indent)
    if annotation is bool:
        return w["bool"]
    if annotation is int:
        rng = ""
        if info is not None:
            ge = next((getattr(m, "ge", None) for m in info.metadata if hasattr(m, "ge")), None)
            le = next((getattr(m, "le", None) for m in info.metadata if hasattr(m, "le")), None)
            if ge is not None and le is not None:
                rng = " " + w["range"].format(a=ge, b=le)
        return w["int"] + rng
    if annotation is str:
        lo, hi = _limits(info, [])
        desc = w["string"]
        if hi:
            desc += ", " + w["max_chars"].format(n=hi)
        if lo == 0:
            desc += ", " + w["empty_ok"]
        return desc
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return w["object"] + ":\n" + _fields(annotation, w, indent + "  ")
    return str(annotation)


def _fields(
    model: type[BaseModel], w: dict[str, str], indent: str = "", skip: frozenset[str] = frozenset()
) -> str:
    lines = []
    for name, info in model.model_fields.items():
        if name in SERVER_FIELDS or name in skip:
            continue
        lines.append(f"{indent}- {name}: {_describe(info.annotation, info, w, indent)}")
    return "\n".join(lines)


def output_format(model: type[BaseModel], language: str, *, streamed: bool = False) -> str:
    w = WORDS["zh-CN" if language == "zh-CN" else "en"]
    if streamed:
        return w["stream_head"] + "\n" + _fields(model, w, skip=frozenset({"content"}))
    return w["head"] + "\n" + _fields(model, w)


def render(template: str, values: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in values:
            raise KeyError(f"no value for placeholder {{{{{key}}}}}")
        return values[key]

    return _PLACEHOLDER.sub(sub, template)


DATA_OPEN = "<<<DATA"
DATA_CLOSE = "DATA>>>"


def as_data(text: str) -> str:
    """Delimit participant text. The delimiters are removed from the text itself first."""
    clean = text.replace(DATA_OPEN, "").replace(DATA_CLOSE, "").replace("<!--", "")
    return f"{DATA_OPEN}\n{clean}\n{DATA_CLOSE}"


def fill_fallback(
    output: dict[str, Any], model: type[BaseModel], skill_name: str, module_name: str
) -> BaseModel:
    def fill(v: Any) -> Any:
        if isinstance(v, str):
            return v.replace("{skill_name}", skill_name).replace("{module_name}", module_name)
        if isinstance(v, list):
            return [fill(x) for x in v]
        if isinstance(v, dict):
            return {k: fill(x) for k, x in v.items()}
        return v

    try:
        return model.model_validate(fill(output))
    except ValidationError as exc:
        raise ValueError(str(exc).splitlines()[0]) from exc
