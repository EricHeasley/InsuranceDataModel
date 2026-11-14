"""Load and validate the insurance data model defined in model/*.json.

Standard library only. `load()` returns the resolved model (mixins expanded,
enums normalized); `validate()` returns a list of error strings.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "model"
SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
ENUM_CODE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")
SENSITIVITY = {"PII", "PHI", "PCI", "SPI"}
ENTITY_KEYS = {"name", "description", "subtypeOf", "primaryKey", "unique", "mixins", "attributes"}
ATTR_KEYS = {"name", "type", "required", "maxLength", "enum", "references", "description", "sensitivity"}


def _read(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load() -> dict:
    """Return the resolved model.

    Shape: manifest fields plus
      enums:    {name: {description, values: {code: description}, domain}}
      entities: {name: {..., domain, attributes: [own + mixin attributes]}}
    Each attribute gains `mixin` (name or None).
    """
    manifest = _read(MODEL_DIR / "model.json")
    model = dict(manifest)
    model["enums"], model["entities"], model["load_errors"] = {}, {}, []
    domains = []
    for entry in manifest["domains"]:
        doc = _read(MODEL_DIR / entry["file"])
        if doc.get("domain") != entry["name"]:
            model["load_errors"].append(f"{entry['file']}: domain is '{doc.get('domain')}', manifest says '{entry['name']}'")
        domains.append({"name": entry["name"], "file": entry["file"], "description": doc.get("description", "")})
        for name, enum in doc.get("enums", {}).items():
            if name in model["enums"]:
                model["load_errors"].append(f"enum '{name}' defined in both {model['enums'][name]['domain']} and {entry['name']}")
            values = enum["values"]
            if isinstance(values, list):
                values = {code: "" for code in values}
            model["enums"][name] = {"description": enum.get("description", ""), "values": values, "domain": entry["name"]}
        for entity in doc.get("entities", []):
            name = entity.get("name")
            if name in model["entities"]:
                model["load_errors"].append(f"entity '{name}' defined in both {model['entities'][name]['domain']} and {entry['name']}")
            resolved = dict(entity)
            resolved["domain"] = entry["name"]
            resolved["own_keys"] = set(entity)
            mixins = entity.get("mixins", manifest.get("defaultMixins", []))
            resolved["mixins"] = mixins
            attrs = [dict(a, mixin=None) for a in entity.get("attributes", [])]
            for mixin in mixins:
                if mixin not in manifest["mixins"]:
                    model["load_errors"].append(f"{name}: unknown mixin '{mixin}'")
                    continue
                attrs += [dict(a, mixin=mixin) for a in manifest["mixins"][mixin]["attributes"]]
            resolved["attributes"] = attrs
            model["entities"][name] = resolved
    model["domains"] = domains
    return model


def attribute(model: dict, entity: str, name: str):
    for attr in model["entities"][entity]["attributes"]:
        if attr["name"] == name:
            return attr
    return None


def validate(model: dict) -> list[str]:
    errors = list(model["load_errors"])
    types, enums, entities = model["types"], model["enums"], model["entities"]
    used_enums = set()

    for name, enum in enums.items():
        if not SNAKE.match(name):
            errors.append(f"enum {name}: name is not snake_case")
        if not enum["description"]:
            errors.append(f"enum {name}: missing description")
        if not enum["values"]:
            errors.append(f"enum {name}: no values")
        for code in enum["values"]:
            if not ENUM_CODE.match(code):
                errors.append(f"enum {name}: value '{code}' is not UPPER_SNAKE_CASE")

    for name, entity in entities.items():
        where = f"{entity['domain']}.{name}"
        if not SNAKE.match(name or ""):
            errors.append(f"{where}: entity name is not snake_case")
        for key in entity["own_keys"] - ENTITY_KEYS:
            errors.append(f"{where}: unknown key '{key}'")
        if not entity.get("description"):
            errors.append(f"{where}: missing description")
        names = [a["name"] for a in entity["attributes"]]
        for dup in {n for n in names if names.count(n) > 1}:
            errors.append(f"{where}: duplicate attribute '{dup}'")

        pk = entity.get("primaryKey") or []
        if not pk:
            errors.append(f"{where}: missing primaryKey")
        for col in pk:
            attr = attribute(model, name, col)
            if attr is None:
                errors.append(f"{where}: primaryKey attribute '{col}' does not exist")
            elif not attr.get("required"):
                errors.append(f"{where}: primaryKey attribute '{col}' must be required")
        for key in entity.get("unique", []):
            for col in key:
                if col not in names:
                    errors.append(f"{where}: unique key attribute '{col}' does not exist")

        parent = entity.get("subtypeOf")
        if parent:
            if parent not in entities:
                errors.append(f"{where}: subtypeOf '{parent}' does not exist")
            else:
                ppk = entities[parent]["primaryKey"]
                if pk != ppk:
                    errors.append(f"{where}: subtype primary key {pk} must equal supertype primary key {ppk}")
                elif attribute(model, name, pk[0]).get("references") != f"{parent}.{ppk[0]}":
                    errors.append(f"{where}: subtype primary key must reference {parent}.{ppk[0]}")

        for attr in entity["attributes"]:
            at = f"{where}.{attr.get('name')}"
            for key in set(attr) - ATTR_KEYS - {"mixin"}:
                errors.append(f"{at}: unknown key '{key}'")
            if not SNAKE.match(attr.get("name", "")):
                errors.append(f"{at}: attribute name is not snake_case")
            if attr.get("type") not in types:
                errors.append(f"{at}: unknown type '{attr.get('type')}'")
            if "maxLength" in attr and attr.get("type") != "string":
                errors.append(f"{at}: maxLength only applies to string")
            if "sensitivity" in attr and attr["sensitivity"] not in SENSITIVITY:
                errors.append(f"{at}: unknown sensitivity '{attr['sensitivity']}'")
            if "enum" in attr:
                used_enums.add(attr["enum"])
                if attr["enum"] not in enums:
                    errors.append(f"{at}: unknown enum '{attr['enum']}'")
                if attr.get("type") != "string":
                    errors.append(f"{at}: enum attributes must be type string")
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

    for name in sorted(set(enums) - used_enums):
        errors.append(f"enum {name}: defined but never used")
    return errors
