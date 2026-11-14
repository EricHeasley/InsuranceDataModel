#!/usr/bin/env python3
"""Validate JSON records against an entity's schema.

  python3 tools/check_record.py policy record.json      # one object or an array of objects

Needs `jsonschema`. Or skip this tool: each schema file is plain JSON Schema,
so schemas/policy/policy.schema.json works directly with any validator.
"""
import json
import sys

import idm


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    entity, path = sys.argv[1:]
    from jsonschema import Draft202012Validator

    files = {doc["title"]: doc for doc in idm.schema_files().values()}
    if entity not in files:
        print(f"unknown entity '{entity}'", file=sys.stderr)
        return 2
    validator = Draft202012Validator(files[entity])
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    records = data if isinstance(data, list) else [data]
    failures = 0
    for i, record in enumerate(records):
        for err in validator.iter_errors(record):
            failures += 1
            where = "/".join(str(p) for p in err.absolute_path) or "(record)"
            print(f"record {i}: {where}: {err.message}")
    print(f"{len(records)} record(s) checked against {entity}: {'FAILED' if failures else 'OK'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
