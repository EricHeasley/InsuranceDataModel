"""Load and validate the insurance data model defined as plain JSON Schema files in schemas/.

Standard library only. `load()` reads the schema files and returns the model as
Python data; `validate()` returns a list of error strings.

Layout of schemas/:
  catalog.json                     name, version, conventions, ordered list of domains
  <domain>/<entity>.schema.json    one self-contained JSON Schema per entity

Each property is plain JSON Schema (type, format, maxLength, enum or oneOf) plus
optional description, x-references (foreign key) and x-sensitivity.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"
DRAFT = "https://json-schema.org/draft/2020-12/schema"
SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
ENUM_CODE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")
SENSITIVITY = {"PII", "PHI", "PCI", "SPI"}
NUMBER_FORMATS = {"money", "percent", "rate", "decimal"}
ENTITY_KEYS = {"$schema", "title", "description", "type", "required", "properties", "additionalProperties",
               "x-primaryKey", "x-unique", "x-subtypeOf"}
PROP_KEYS = {"type", "format", "maxLength", "enum", "oneOf", "description", "x-references", "x-sensitivity"}


def schema_files() -> dict:
    """Every entity schema, keyed by path relative to schemas/."""
    return {str(p.relative_to(SCHEMA_DIR)): json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(SCHEMA_DIR.glob("*/*.schema.json"))}


def _property(name: str, prop: dict, required: set, where: str, errors: list) -> dict:
    """Turn one schema property into the attribute dict used by the rest of the tooling.

    Logical type: uuid, string (varchar), text, integer, money, percent, rate, decimal,
    date, timestamp, boolean, json. `enum` is {code: description} for coded values.
    """
    at = f"{where}.{name}"
    for key in set(prop) - PROP_KEYS:
        errors.append(f"{at}: unsupported keyword '{key}'")
    attr = {"name": name}
    kind, fmt = prop.get("type"), prop.get("format")
    if "enum" in prop or "oneOf" in prop:
        values = {}
        if "enum" in prop:
            values = {c: "" for c in prop["enum"]}
        else:
            for alt in prop["oneOf"]:
                if set(alt) - {"const", "description"} or "const" not in alt:
                    errors.append(f"{at}: oneOf entries must be {{const, description?}}")
                else:
                    values[alt["const"]] = alt.get("description", "")
        if kind != "string":
            errors.append(f"{at}: coded values must have type string")
        attr["type"], attr["enum"] = "string", values
    elif kind == "string" and fmt == "uuid":
        attr["type"] = "uuid"
    elif kind == "string" and fmt == "date":
        attr["type"] = "date"
    elif kind == "string" and fmt == "date-time":
        attr["type"] = "timestamp"
    elif kind == "string" and fmt is None:
        attr["type"] = "string" if "maxLength" in prop else "text"
    elif kind == "number" and fmt in NUMBER_FORMATS:
        attr["type"] = fmt
    elif kind in ("integer", "boolean") and fmt is None:
        attr["type"] = kind
    elif kind == "object" and fmt is None:
        attr["type"] = "json"
    else:
        errors.append(f"{at}: unsupported type/format combination ({kind}, {fmt})")
        attr["type"] = None
    if "maxLength" in prop:
        attr["maxLength"] = prop["maxLength"]
    if name in required:
        attr["required"] = True
    for src, dst in (("x-references", "references"), ("description", "description"), ("x-sensitivity", "sensitivity")):
        if src in prop:
            attr[dst] = prop[src]
    return attr


def load() -> dict:
    """Return the model: catalog fields plus
      entities: {name: {name, domain, description, primaryKey, unique?, subtypeOf?, attributes}}
    `load_errors` lists problems found while reading the files.
    """
    errors = []
    catalog = json.loads((SCHEMA_DIR / "catalog.json").read_text(encoding="utf-8"))
    model = dict(catalog)
    model["load_errors"] = errors
    domain_names = [d["name"] for d in catalog["domains"]]

    on_disk = {p.name for p in SCHEMA_DIR.iterdir() if p.is_dir()}
    for stray in sorted(on_disk - set(domain_names)):
        errors.append(f"schemas/{stray}: directory is not a domain listed in catalog.json")
    for missing in sorted(set(domain_names) - on_disk):
        errors.append(f"catalog.json: domain '{missing}' has no directory under schemas/")

    entities = {}
    for domain in domain_names:
        for path in sorted((SCHEMA_DIR / domain).glob("*.json")):
            where = f"{domain}/{path.name}"
            if not path.name.endswith(".schema.json"):
                errors.append(f"{where}: file name must end in .schema.json")
                continue
            doc, name = json.loads(path.read_text(encoding="utf-8")), path.name.removesuffix(".schema.json")
            for key in set(doc) - ENTITY_KEYS:
                errors.append(f"{where}: unsupported keyword '{key}'")
            if doc.get("$schema") != DRAFT:
                errors.append(f"{where}: $schema must be {DRAFT}")
            if doc.get("title") != name:
                errors.append(f"{where}: title '{doc.get('title')}' must equal the file name")
            if doc.get("type") != "object":
                errors.append(f"{where}: type must be 'object'")
            if doc.get("additionalProperties") is not False:
                errors.append(f"{where}: additionalProperties must be false")
            if name in entities:
                errors.append(f"entity '{name}' defined in both {entities[name]['domain']} and {domain}")
            required = set(doc.get("required", []))
            props = doc.get("properties", {})
            for r in sorted(required - set(props)):
                errors.append(f"{where}: required '{r}' is not a property")
            ent = {"name": name, "domain": domain, "description": doc.get("description", ""),
                   "primaryKey": doc.get("x-primaryKey", []),
                   "attributes": [_property(n, p, required, name, errors) for n, p in props.items()]}
            if "x-unique" in doc:
                ent["unique"] = doc["x-unique"]
            if "x-subtypeOf" in doc:
                ent["subtypeOf"] = doc["x-subtypeOf"]
            entities[name] = ent
    model["entities"] = entities
    model["domains"] = [dict(d) for d in catalog["domains"]]
    return model


def attribute(model: dict, entity: str, name: str):
    for attr in model["entities"][entity]["attributes"]:
        if attr["name"] == name:
            return attr
    return None


def validate(model: dict) -> list[str]:
    errors = list(model["load_errors"])
    entities = model["entities"]

    for name, entity in entities.items():
        where = f"{entity['domain']}.{name}"
        if not SNAKE.match(name or ""):
            errors.append(f"{where}: entity name is not snake_case")
        if not entity.get("description"):
            errors.append(f"{where}: missing description")
        names = [a["name"] for a in entity["attributes"]]
        for dup in {n for n in names if names.count(n) > 1}:
            errors.append(f"{where}: duplicate attribute '{dup}'")

        pk = entity.get("primaryKey") or []
        if not pk:
            errors.append(f"{where}: missing x-primaryKey")
        for col in pk:
            attr = attribute(model, name, col)
            if attr is None:
                errors.append(f"{where}: primary key attribute '{col}' does not exist")
            elif not attr.get("required"):
                errors.append(f"{where}: primary key attribute '{col}' must be required")
        for key in entity.get("unique", []):
            for col in key:
                if col not in names:
                    errors.append(f"{where}: unique key attribute '{col}' does not exist")

        parent = entity.get("subtypeOf")
        if parent:
            if parent not in entities:
                errors.append(f"{where}: x-subtypeOf '{parent}' does not exist")
            else:
                ppk = entities[parent]["primaryKey"]
                if pk != ppk:
                    errors.append(f"{where}: subtype primary key {pk} must equal supertype primary key {ppk}")
                elif attribute(model, name, pk[0]).get("references") != f"{parent}.{ppk[0]}":
                    errors.append(f"{where}: subtype primary key must reference {parent}.{ppk[0]}")

        for attr in entity["attributes"]:
            at = f"{where}.{attr['name']}"
            if not SNAKE.match(attr["name"]):
                errors.append(f"{at}: attribute name is not snake_case")
            if "maxLength" in attr and attr.get("type") != "string":
                errors.append(f"{at}: maxLength only applies to plain strings")
            if "sensitivity" in attr and attr["sensitivity"] not in SENSITIVITY:
                errors.append(f"{at}: unknown sensitivity '{attr['sensitivity']}'")
            if "enum" in attr:
                if not attr["enum"]:
                    errors.append(f"{at}: no allowed values")
                for code in attr["enum"]:
                    if not ENUM_CODE.match(str(code)):
                        errors.append(f"{at}: value '{code}' is not UPPER_SNAKE_CASE")
            ref = attr.get("references")
            if ref:
                target_entity, _, target_attr = ref.partition(".")
                if target_entity not in entities:
                    errors.append(f"{at}: references unknown entity '{target_entity}'")
                    continue
                target = attribute(model, target_entity, target_attr)
                tgt = entities[target_entity]
                if target is None:
                    errors.append(f"{at}: references unknown attribute '{ref}'")
                elif tgt["primaryKey"] != [target_attr] and [target_attr] not in tgt.get("unique", []):
                    errors.append(f"{at}: '{ref}' is not a single-attribute primary or unique key")
                elif target["type"] != attr.get("type") or target.get("maxLength") != attr.get("maxLength"):
                    errors.append(f"{at}: type/maxLength differs from referenced '{ref}'")
    return errors
