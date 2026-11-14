#!/usr/bin/env python3
"""Validate JSON records against an entity's schema.

  python3 tools/check_record.py policy record.json      # one object or an array of objects

Needs `jsonschema` 4.18+.
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
    from referencing import Registry, Resource

    model = idm.load()
    if entity not in model["entities"]:
        print(f"unknown entity '{entity}'", file=sys.stderr)
        return 2
    docs = idm.schema_files()
    registry = Registry().with_resources((uri, Resource.from_contents(d)) for uri, d in docs.items() if "$schema" in d)
    uri = f"{idm.SCHEMA_BASE}{model['entities'][entity]['domain']}/{entity}.schema.json"
    validator = Draft202012Validator(docs[uri], registry=registry)
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
