#!/usr/bin/env python3
"""Validate the model: every schema file is valid JSON Schema and resolves, and the
model is internally consistent (keys, references, code lists, types).

The JSON Schema checks need the optional `jsonschema` package (4.18+); the
integrity checks need only the standard library.
"""
import sys

import idm

SAMPLE = {
    "uuid": "00000000-0000-4000-8000-000000000000", "string": "x", "text": "x", "integer": 0, "decimal": 0,
    "money": 0, "percent": 0, "rate": 0, "date": "2000-01-01", "timestamp": "2000-01-01T00:00:00Z",
    "boolean": True, "json": {},
}


def sample_record(model: dict, entity: dict) -> dict:
    """The smallest record that should satisfy the entity's schema."""
    rec = {}
    for a in entity["attributes"]:
        if a.get("required"):
            rec[a["name"]] = next(iter(model["enums"][a["enum"]]["values"])) if "enum" in a else SAMPLE[a["type"]]
    return rec


def schema_errors(model: dict) -> list[str]:
    try:
        import jsonschema
        from referencing import Registry, Resource
    except ImportError:
        print("note: jsonschema (4.18+) not installed; skipping JSON Schema checks", file=sys.stderr)
        return []
    docs = idm.schema_files()
    registry = Registry().with_resources((uri, Resource.from_contents(doc)) for uri, doc in docs.items()
                                         if "$schema" in doc)
    errors = []
    for uri, doc in docs.items():
        if "$schema" not in doc:
            continue
        try:
            jsonschema.Draft202012Validator.check_schema(doc)
        except jsonschema.SchemaError as err:
            errors.append(f"{uri}: not valid JSON Schema: {err.message}")
    for name, entity in model["entities"].items():
        uri = f"{idm.SCHEMA_BASE}{entity['domain']}/{name}.schema.json"
        validator = jsonschema.Draft202012Validator(docs[uri], registry=registry)
        record = sample_record(model, entity)
        try:
            for err in validator.iter_errors(record):
                errors.append(f"{name}: sample record rejected: {err.message}")
            if validator.is_valid({**record, "no_such_attribute": 1}):
                errors.append(f"{name}: schema accepts unknown attributes")
            for required in list(record):
                if validator.is_valid({k: v for k, v in record.items() if k != required}):
                    errors.append(f"{name}: schema accepts a record without required '{required}'")
        except Exception as err:  # unresolvable $ref and similar
            errors.append(f"{name}: {type(err).__name__}: {err}")
    return errors


def main() -> int:
    model = idm.load()
    errors = idm.validate(model)
    if not model["load_errors"]:
        errors += schema_errors(model)
    for err in errors:
        print(f"ERROR {err}")
    attrs = sum(len(e["attributes"]) for e in model["entities"].values())
    print(f"{len(model['domains'])} domains, {len(model['entities'])} entities, {attrs} attributes, "
          f"{len(model['enums'])} enums: {'FAILED' if errors else 'OK'} ({len(errors)} errors)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
