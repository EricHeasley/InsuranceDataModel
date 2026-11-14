#!/usr/bin/env python3
"""Validate the model: structure (JSON Schema, if `jsonschema` is installed) and semantics."""
import json
import sys

import idm


def schema_errors() -> list[str]:
    try:
        import jsonschema
    except ImportError:
        print("note: jsonschema not installed; skipping structural schema check", file=sys.stderr)
        return []
    errors = []
    schema_dir = idm.ROOT / "schema"
    manifest = json.loads((idm.MODEL_DIR / "model.json").read_text(encoding="utf-8"))
    checks = [("model.json", "model.schema.json")] + [(d["file"], "domain.schema.json") for d in manifest["domains"]]
    for doc_file, schema_file in checks:
        schema = json.loads((schema_dir / schema_file).read_text(encoding="utf-8"))
        doc = json.loads((idm.MODEL_DIR / doc_file).read_text(encoding="utf-8"))
        for err in jsonschema.Draft202012Validator(schema).iter_errors(doc):
            path = "/".join(str(p) for p in err.absolute_path)
            errors.append(f"{doc_file}: /{path}: {err.message}")
    return errors


def main() -> int:
    errors = schema_errors()
    model = idm.load()
    errors += idm.validate(model)
    for err in errors:
        print(f"ERROR {err}")
    attrs = sum(len(e["attributes"]) for e in model["entities"].values())
    print(f"{len(model['domains'])} domains, {len(model['entities'])} entities, {attrs} attributes, "
          f"{len(model['enums'])} enums: {'FAILED' if errors else 'OK'} ({len(errors)} errors)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
