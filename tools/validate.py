#!/usr/bin/env python3
"""Validate the model: every schema file is valid JSON Schema, and keys, references,
types and code lists are consistent.

The JSON Schema checks need the optional `jsonschema` package; the integrity
checks need only the standard library.
"""
import sys

import idm

SAMPLE = {
    "uuid": "00000000-0000-4000-8000-000000000000", "string": "x", "text": "x", "integer": 0, "decimal": 0,
    "money": 0, "percent": 0, "rate": 0, "date": "2000-01-01", "timestamp": "2000-01-01T00:00:00Z",
    "boolean": True, "json": {},
}


def sample_record(entity: dict) -> dict:
    """The smallest record that should satisfy the entity's schema."""
    return {a["name"]: next(iter(a["enum"])) if "enum" in a else SAMPLE[a["type"]]
            for a in entity["attributes"] if a.get("required")}


def schema_errors(model: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        print("note: jsonschema not installed; skipping JSON Schema checks", file=sys.stderr)
        return []
    errors = []
    for rel, doc in idm.schema_files().items():
        try:
            jsonschema.Draft202012Validator.check_schema(doc)
        except jsonschema.SchemaError as err:
            errors.append(f"{rel}: not valid JSON Schema: {err.message}")
            continue
        entity = model["entities"][doc["title"]]
        validator = jsonschema.Draft202012Validator(doc)
        record = sample_record(entity)
        for err in validator.iter_errors(record):
            errors.append(f"{entity['name']}: sample record rejected: {err.message}")
        if validator.is_valid({**record, "no_such_attribute": 1}):
            errors.append(f"{entity['name']}: schema accepts unknown attributes")
        for required in record:
            if validator.is_valid({k: v for k, v in record.items() if k != required}):
                errors.append(f"{entity['name']}: schema accepts a record without required '{required}'")
    return errors


def main() -> int:
    model = idm.load()
    errors = idm.validate(model)
    if not model["load_errors"]:
        errors += schema_errors(model)
    for err in errors:
        print(f"ERROR {err}")
    attrs = sum(len(e["attributes"]) for e in model["entities"].values())
    print(f"{len(model['domains'])} domains, {len(model['entities'])} entities, {attrs} attributes: "
          f"{'FAILED' if errors else 'OK'} ({len(errors)} errors)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
