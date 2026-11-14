"""Load and validate the insurance data model defined as JSON Schema files in schemas/.

Standard library only. `load()` reads the schema files and returns the resolved
model (mixins expanded, enums normalized, types looked up); `validate()` returns
a list of error strings.

Layout of schemas/:
  catalog.json                         name, version, conventions, ordered domain list
  common/types.schema.json             logical types ($defs), each with x-postgres
  common/<mixin>.schema.json           attribute groups applied with allOf (audit, policy_versioned)
  <domain>/<entity>.schema.json        one JSON Schema per entity
  <domain>/enums/<code_list>.schema.json  one JSON Schema per code list
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"
SCHEMA_BASE = "https://github.com/EricHeasley/InsuranceDataModel/schemas/"
DRAFT = "https://json-schema.org/draft/2020-12/schema"
SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
ENUM_CODE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")
SENSITIVITY = {"PII", "PHI", "PCI", "SPI"}
ENTITY_KEYS = {"$schema", "$id", "title", "description", "x-primaryKey", "x-unique", "x-subtypeOf",
               "type", "allOf", "properties", "required", "unevaluatedProperties"}
MIXIN_KEYS = {"$schema", "$id", "title", "description", "type", "properties", "required"}
ENUM_KEYS = {"$schema", "$id", "title", "description", "type", "enum", "oneOf"}
PROP_KEYS = {"$ref", "maxLength", "description", "x-references", "x-sensitivity"}
TYPE_REF = re.compile(r"^(?:\.\./common/)?types\.schema\.json#/\$defs/([a-z]+)$")
ENUM_REF = re.compile(r"^(?:enums/|\.\./([a-z0-9_]+)/enums/)([a-z0-9_]+)\.schema\.json$")
MIXIN_REF = re.compile(r"^\.\./common/([a-z_]+)\.schema\.json$")


def _read(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def schema_files() -> dict:
    """Every schema document under schemas/, keyed by its $id."""
    docs = {}
    for path in sorted(SCHEMA_DIR.rglob("*.schema.json")):
        doc = _read(path)
        docs[doc.get("$id", path.as_uri())] = doc
    return docs


def _enum(doc: dict, where: str, errors: list) -> dict:
    values = {}
    if "enum" in doc:
        values = {code: "" for code in doc["enum"]}
    elif "oneOf" in doc:
        for alt in doc["oneOf"]:
            if set(alt) - {"const", "description"} or "const" not in alt:
                errors.append(f"{where}: oneOf entries must be {{const, description?}}")
                continue
            values[alt["const"]] = alt.get("description", "")
    else:
        errors.append(f"{where}: enum schema needs 'enum' or 'oneOf'")
    return values


def _attribute(name: str, prop: dict, required: set, where: str, prefix: str, domain, enums: dict, errors: list) -> dict:
    """Turn one schema property into the attribute dict used by the rest of the tooling."""
    at = f"{where}.{name}"
    for key in set(prop) - PROP_KEYS:
        errors.append(f"{at}: unsupported keyword '{key}'")
    ref = prop.get("$ref", "")
    attr = {"name": name, "mixin": None}
    if (m := TYPE_REF.match(ref)) and ref == f"{prefix}types.schema.json#/$defs/{m.group(1)}":
        attr["type"] = m.group(1)
    elif m := ENUM_REF.match(ref):
        enum_domain, enum_name = m.group(1) or domain, m.group(2)
        attr["type"], attr["enum"] = "string", enum_name
        if enum_name not in enums or enums[enum_name]["domain"] != enum_domain:
            errors.append(f"{at}: $ref '{ref}' does not point to an existing code list")
    else:
        errors.append(f"{at}: $ref '{ref}' is not a logical type or code list")
        attr["type"] = None
    if name in required:
        attr["required"] = True
    for src, dst in (("maxLength", "maxLength"), ("x-references", "references"),
                     ("description", "description"), ("x-sensitivity", "sensitivity")):
        if src in prop:
            attr[dst] = prop[src]
    return attr


def load() -> dict:
    """Return the resolved model.

    Shape: catalog fields plus
      types:    {name: {description, postgres, jsonSchema}}
      mixins:   {name: {description, attributes}}
      enums:    {name: {description, values: {code: description}, domain}}
      entities: {name: {..., domain, mixins, attributes: [own + mixin attributes]}}
    Each attribute gains `mixin` (name or None).
    """
    errors = []
    catalog = _read(SCHEMA_DIR / "catalog.json")
    model = dict(catalog)
    model["load_errors"] = errors

    types = {}
    for name, d in _read(SCHEMA_DIR / "common/types.schema.json")["$defs"].items():
        js = {k: v for k, v in d.items() if k not in ("description", "x-postgres")}
        types[name] = {"description": d.get("description", ""), "postgres": d.get("x-postgres"), "jsonSchema": js}
    model["types"] = types

    domain_names = [d["name"] for d in catalog["domains"]]
    on_disk = {p.name for p in SCHEMA_DIR.iterdir() if p.is_dir()} - {"common"}
    for stray in sorted(on_disk - set(domain_names)):
        errors.append(f"schemas/{stray}: directory is not a domain listed in catalog.json")
    for missing in sorted(set(domain_names) - on_disk):
        errors.append(f"catalog.json: domain '{missing}' has no directory under schemas/")

    # code lists first, so property $refs can be checked against them
    enums = {}
    for domain in domain_names:
        for path in sorted((SCHEMA_DIR / domain / "enums").glob("*.schema.json")):
            doc, name = _read(path), path.name.removesuffix(".schema.json")
            where = f"{domain}/enums/{name}"
            for key in set(doc) - ENUM_KEYS:
                errors.append(f"{where}: unsupported keyword '{key}'")
            if doc.get("title") != name:
                errors.append(f"{where}: title '{doc.get('title')}' must equal the file name")
            if doc.get("$id") != f"{SCHEMA_BASE}{domain}/enums/{name}.schema.json":
                errors.append(f"{where}: $id does not match the file path")
            if doc.get("type") != "string":
                errors.append(f"{where}: type must be 'string'")
            if name in enums:
                errors.append(f"enum '{name}' defined in both {enums[name]['domain']} and {domain}")
            enums[name] = {"description": doc.get("description", ""), "domain": domain, "values": _enum(doc, where, errors)}
    model["enums"] = enums

    mixins = {}
    for path in sorted((SCHEMA_DIR / "common").glob("*.schema.json")):
        name = path.name.removesuffix(".schema.json")
        if name == "types":
            continue
        doc, where = _read(path), f"common/{name}"
        for key in set(doc) - MIXIN_KEYS:
            errors.append(f"{where}: unsupported keyword '{key}'")
        required = set(doc.get("required", []))
        attrs = [dict(_attribute(n, p, required, where, "", None, enums, errors), mixin=name)
                 for n, p in doc.get("properties", {}).items()]
        mixins[name] = {"description": doc.get("description", ""), "attributes": attrs}
    model["mixins"] = mixins

    entities = {}
    for domain in domain_names:
        for path in sorted((SCHEMA_DIR / domain).glob("*.schema.json")):
            doc, name = _read(path), path.name.removesuffix(".schema.json")
            where = f"{domain}/{name}"
            for key in set(doc) - ENTITY_KEYS:
                errors.append(f"{where}: unsupported keyword '{key}'")
            if doc.get("$schema") != DRAFT:
                errors.append(f"{where}: $schema must be {DRAFT}")
            if doc.get("title") != name:
                errors.append(f"{where}: title '{doc.get('title')}' must equal the file name")
            if doc.get("$id") != f"{SCHEMA_BASE}{domain}/{name}.schema.json":
                errors.append(f"{where}: $id does not match the file path")
            if doc.get("type") != "object":
                errors.append(f"{where}: type must be 'object'")
            if doc.get("unevaluatedProperties") is not False:
                errors.append(f"{where}: unevaluatedProperties must be false")
            if name in entities:
                errors.append(f"entity '{name}' defined in both {entities[name]['domain']} and {domain}")
            used = []
            for part in doc.get("allOf", []):
                m = MIXIN_REF.match(part.get("$ref", "")) if set(part) == {"$ref"} else None
                if not m or m.group(1) not in mixins:
                    errors.append(f"{where}: allOf entry {part} is not a reference to a common mixin")
                else:
                    used.append(m.group(1))
            required = set(doc.get("required", []))
            props = doc.get("properties", {})
            for r in sorted(required - set(props)):
                errors.append(f"{where}: required '{r}' is not a property")
            attrs = [_attribute(n, p, required, where, "../common/", domain, enums, errors) for n, p in props.items()]
            for mixin in used:
                attrs += [dict(a) for a in mixins[mixin]["attributes"]]
            ent = {"name": name, "domain": domain, "description": doc.get("description", ""),
                   "primaryKey": doc.get("x-primaryKey", []), "mixins": used, "attributes": attrs}
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
