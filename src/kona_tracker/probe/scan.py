"""Turn a raw introspection dump into the two things slice 2 needs to know:
what a `Pet` exposes, and whether anything in the whole schema smells like
sleep quality or behavior tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

KEYWORDS = (
    "sleep",
    "rest",
    "nap",
    "quality",
    "score",
    "behavior",
    "behaviour",
    "scratch",
    "lick",
    "bark",
    "eat",
    "drink",
    "interrupt",
)


@dataclass
class SchemaScan:
    pet_fields: list[str] = field(default_factory=list)
    keyword_hits: list[str] = field(default_factory=list)  # "Type.field: ReturnType"
    keyword_types: list[str] = field(default_factory=list)  # type names alone


def _type_name(t: dict[str, Any] | None) -> str:
    """Render a (possibly wrapped) GraphQL type reference, e.g. [Foo!]!."""
    if not t:
        return "?"
    kind, name, inner = t.get("kind"), t.get("name"), t.get("ofType")
    if kind == "NON_NULL":
        return _type_name(inner) + "!"
    if kind == "LIST":
        return "[" + _type_name(inner) + "]"
    return name or "?"


def _field_sig(f: dict[str, Any]) -> str:
    args = f.get("args") or []
    arg_s = ""
    if args:
        arg_s = "(" + ", ".join(f"{a['name']}: {_type_name(a.get('type'))}" for a in args) + ")"
    return f"{f['name']}{arg_s}: {_type_name(f.get('type'))}"


def _matches(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in KEYWORDS)


def scan_schema(schema: dict[str, Any]) -> SchemaScan:
    """`schema` is the value of `data.__schema` from the introspection query."""
    out = SchemaScan()
    for t in schema.get("types") or []:
        tname = t.get("name") or ""
        if tname.startswith("__"):
            continue
        fields = t.get("fields") or []
        enum_values = [v["name"] for v in (t.get("enumValues") or [])]
        if tname == "Pet":
            out.pet_fields = [_field_sig(f) for f in fields]
        if _matches(tname):
            out.keyword_types.append(tname)
            for v in enum_values:
                out.keyword_hits.append(f"{tname}.{v} (enum value)")
        for f in fields:
            if _matches(f["name"]) or _matches(_type_name(f.get("type"))):
                out.keyword_hits.append(f"{tname}.{_field_sig(f)}")
    out.keyword_hits.sort()
    out.keyword_types.sort()
    return out
