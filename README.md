# InsuranceDataModel

A normalized operational data model for insurance carriers, covering P&C personal, P&C commercial, life & annuity, and health lines under US market conventions. The model is a set of plain JSON Schema (draft 2020-12) files, one per entity; everything else in the repository is generated from them.

Version 0.1.0: 12 domains, 137 entities.

## What is here

| Path | Contents |
|---|---|
| `schemas/<domain>/<entity>.schema.json` | **The model.** One plain, self-contained JSON Schema per entity, e.g. `schemas/policy/policy.schema.json` |
| `schemas/catalog.json` | Name, version, conventions and the ordered list of domains (not a schema) |
| `tools/validate.py` | Checks every schema is valid and that keys, references and code values are consistent |
| `tools/check_record.py` | Validates your own JSON records against an entity's schema |
| `tools/build.py` | Regenerates everything under `dist/` and `docs/` |
| `dist/insurance-data-model.schema.json` | Generated: all entity schemas bundled in one file |
| `dist/postgres/schema.sql` | Generated: PostgreSQL DDL |
| `docs/data-dictionary.md` | Generated: every entity, attribute and code value |
| `docs/diagrams.md` | Generated: Mermaid ER diagram per domain, plus domain dependencies |

## Domains

| Domain | Entities | Covers |
|---|---|---|
| `reference` | 8 | Jurisdictions, currencies, lines of business, NAIC annual statement lines, causes of loss, external code sets |
| `party` | 12 | Persons, organizations, identifiers, addresses, contact points, relationships, consents, insurers, staff, documents |
| `distribution` | 5 | Producers, licenses, appointments, agreements, commission schedules |
| `product` | 7 | Products, state availability and filings, coverage and coverage-term definitions, forms |
| `policy` | 18 | Submissions, quotes, policies, terms, transactions, parties, risks, coverages, limits/deductibles, forms, rating modifiers, written-premium ledger |
| `pc_personal` | 9 | Vehicles, drivers and driving records, dwellings, watercraft, scheduled items |
| `pc_commercial` | 10 | Business operations, commercial property and auto, GL/WC classification exposures, premium audit, professional, cyber, certificates, surety |
| `life_annuity` | 14 | Life and annuity contract detail, insured lives, beneficiaries, medical underwriting, funds, contract values and ledger, loans, payouts, life claims |
| `health` | 19 | Plans and benefits, employer groups, members, enrollment, providers and networks, medical claims and adjudication, prior authorization, accumulators, COB, disability claims |
| `claims` | 14 | Catastrophes, claims, parties, incidents, exposures, reserve/payment/recovery ledger, payments, recoveries, litigation, SIU, workers' comp detail |
| `billing` | 13 | Billing accounts, payment plans, invoices, payments and application, adjustments, delinquency, disbursements, commissions |
| `reinsurance` | 8 | Treaties and facultative, layers, participants, scope, premium and loss cessions, statements |

## Design

**One core, line detail in subtypes.** `policy`, `policy_risk`, `insurable_object` and `claim` are line-neutral. Line-specific attributes live in subtype entities that share the supertype's primary key (`vehicle`, `dwelling_risk`, `workers_comp_policy_detail`, `life_policy_detail`, `annuity_contract_detail`, `employer_group`, `life_claim_detail`, ...). Adding a line means adding subtypes, not changing the core. Specialty risks without a subtype use `additional_attributes` on `insurable_object` and `policy_risk`.

**Coverages are data.** A product defines its coverages (`coverage_definition`) and the limits, deductibles, waiting periods and benefit amounts each can carry (`coverage_term_definition`). A policy selects them (`policy_coverage`, `policy_coverage_term`). Bodily injury liability, Coverage A dwelling, a waiver-of-premium rider and a guaranteed withdrawal benefit are all rows, not columns.

**Parties exist once.** Every person or organization is a `party`. Insureds, owners, beneficiaries, mortgagees, claimants, attorneys, producers, providers and reinsurers are roles (`policy_party`, `claim_party`, `producer`, `provider`, ...) pointing at it.

**Policies are versioned by transaction.** Each `policy_transaction` (new business, endorsement, renewal, cancellation, audit, ...) has a business-effective date and a processed timestamp. Rows of policy contents record the transaction that added them and the one that removed them, so the policy can be reconstructed as of any date, as known at any time, including out-of-sequence endorsements.

**Financials are append-only ledgers.** `premium_transaction`, `claim_financial_transaction`, `contract_financial_transaction` and the reinsurance cessions hold signed amounts with accounting dates; corrections are reversing entries. Written/earned premium, paid/outstanding/incurred loss and account balances are derived, never stored as mutable totals. Each ledger row carries state and NAIC annual statement line so statutory reports (state page, Schedule P, Schedule F) come straight from it.

**The claim exposure is the unit of claim accounting.** A `claim` is one occurrence under one policy; a `claim_exposure` is one claimant under one coverage. Reserves, payments and recoveries are booked per exposure and cost category (indemnity, medical, DCC, A&O).

**Health care claims are their own structure.** Medical, dental and pharmacy claims (`health_claim`, lines, diagnoses, CARC adjustments) follow X12 837/835 shapes and are adjudicated against `enrollment` and `plan_benefit`, not against P&C-style exposures. Disability, life and workers' comp claims use the core `claim` with a detail subtype.

**External codes stay external.** ICD-10, CPT/HCPCS, NAICS, NCCI and ISO class codes, WCIO, CARC/RARC and NUCC taxonomy live in `code_set` / `code_value` with versions, rather than as hard-coded lists.

**Sensitive data is tagged.** 54 attributes are tagged PII, PHI, PCI or SPI (`x-sensitivity` in the schema), for masking and access policy. Card and bank numbers are never stored, only processor tokens.

The full conventions (naming, money, percent, time) are in `schemas/catalog.json`.

## Schema files

An entity is an ordinary JSON Schema: a list of properties, each with a type, and a list of required ones. Nothing is shared or referenced between files, so a schema can be read, copied and used on its own. `schemas/policy/policy.schema.json` (abridged):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "policy",
  "description": "An insurance contract between an insurer and a policyholder...",
  "type": "object",
  "x-primaryKey": ["policy_id"],
  "x-unique": [["policy_number"]],
  "required": ["policy_id", "policy_number", "product_id", "policy_status", "original_inception_date"],
  "properties": {
    "policy_id": { "type": "string", "format": "uuid" },
    "policy_number": { "type": "string", "maxLength": 30 },
    "product_id": { "type": "string", "format": "uuid", "x-references": "product.product_id" },
    "policy_status": {
      "type": "string",
      "oneOf": [
        { "const": "PENDING", "description": "Bound or applied for, not yet in force" },
        { "const": "IN_FORCE" },
        { "const": "CANCELLED" }
      ]
    },
    "original_inception_date": { "type": "string", "format": "date" },
    "is_assumed_business": { "type": "boolean" }
  },
  "additionalProperties": false
}
```

- **Types** are plain JSON Schema. `uuid`, `date` and `date-time` are string formats. A number must say what kind: `format` is `money` (18,2), `percent` (9,4; 12.5 means 12.5%), `rate` (18,8) or `decimal` (18,6). A string with `maxLength` becomes `varchar`; without it, `text`. An object property becomes `jsonb`.
- **Code values** are `enum`, or `oneOf` of `const` + `description` when the values are explained. Values are UPPER_SNAKE_CASE.
- **Optional properties** are left out of a record when they have no value.
- **Four extra keywords** carry what JSON Schema has no word for. Validators ignore them; the tools use them to produce SQL, docs and diagrams: `x-primaryKey` and `x-unique` (alternate keys) on the entity, `x-subtypeOf` for a subtype that shares its supertype's key, and `x-references` (`entity.attribute`) for a foreign key. `x-sensitivity` tags a property `PII`, `PHI`, `PCI` or `SPI`.
- **Audit columns** (`created_at`, `created_by`, `updated_at`, `updated_by`, `row_version`) are not in the schemas. `tools/build.py` adds them to every table in the SQL.
- The file name must equal `title`, and a file lives in the directory of its domain.

## Working with it

```sh
python3 tools/validate.py                         # check the schemas and the model's integrity
python3 tools/check_record.py policy policy.json  # validate a record (or array of records)
python3 tools/build.py                            # regenerate dist/ and docs/
python3 tools/build.py --check                    # fail if generated files are stale
```

`validate.py` and `build.py` run on the Python 3.9+ standard library alone. If `jsonschema` is installed, `validate.py` also checks that every schema is valid draft 2020-12, that a minimal record is accepted, and that unknown or missing attributes are rejected. `check_record.py` needs `jsonschema`. You can also point any JSON Schema validator straight at one schema file.

To change the model, edit files under `schemas/`, run `validate.py`, then `build.py`, and commit both source and generated files.

## Not in scope yet

- Rating content (rate tables, factors, rules); the model records rating outcomes, not the rating engine's inputs.
- Analytical layer (dimensional marts, loss triangles, earned-premium snapshots). These are derivable from the ledgers.
- General ledger, investments, actuarial reserves (IBNR), and IFRS 17 / LDTI measurement.
- Health provider contracting detail (fee schedules, capitation), risk adjustment and quality measures.
- Reference data content. The reference entities are defined but ship without rows (states, NAIC lines, code sets).
- Non-US regulatory classifications.
