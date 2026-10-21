# Material transplant reference

Use this reference only for the full material reconstruction path. The simplified import path in
`scripts/ue427/import_assets.py` is the default and should be attempted first.

## Files

- `scripts/material_transplant/t3d_parser.py`: offline UE text parser.
- `scripts/material_transplant/planner.py`: switch dependencies, baked combinations, unsupported-node audit.
- `scripts/material_transplant/rules_ue427.py`: pin/output mappings and UE5-to-4.27 graph rules.
- `scripts/material_transplant/build_ue427.py`: UE 4.27 graph builder.
- `scripts/material_transplant/verify_ue427.py`: T3D re-export and original-vs-rebuilt graph comparison.

## Required run order

1. Run `ue5/probe_pack.py` and inspect `summary.json`. Stop when a Custom node has not been reviewed or when
   more than `material.max_combos` static combinations would be required.
2. Run `ue5/dump_graphs.py`. Confirm `dump_graphs.json` has no missing/debug `/Game` functions.
3. Run `ue427/probe_ue427.py` so `probe_427.json` contains `createable_classes`.
4. Run `python material_transplant/planner.py --config ... --check`. Confirm combinations and inspect the
   unsupported-node report.
5. Run one test combination by setting `material.only_combos` to `1`.
6. Generate batch wrappers with `batch_wrapper_template.py`; run each wrapper in UE 4.27 and restart the editor
   between wrappers.
7. Run `verify_ue427.py`. Review the Markdown table and investigate missing connections before accepting the
   transplant.

## Invariants

- Power nodes use `pow(max(Base, 0.0), Exp)` by default. Set `material.native_pow` only after confirming that the
  target 4.27 renderer matches UE5 PositiveClampedPow for the material in question.
- Lerp Alpha is inferred from its own source. If the inferred channel count is greater than one, the builder
  inserts an R-only ComponentMask.
- WPO is located by scanning `MaterialProperty` members containing both `WORLD` and `OFFSET`.
- Every connection return value is checked. Failures stay in `rebuild_log.json` even when a later step succeeds.
- Reroutes, named reroutes and static-switch parameter nodes are resolved to their effective source. The selected
  switch combination is baked into the master.
- Existing assets are resumable outputs. Use `rebuild_existing` deliberately; an interrupted first build can
  leave partially populated assets that should be inspected rather than silently trusted.

## Verification interpretation

Node-count differences are expected for Power replacements, ComponentMasks, removed reroutes/switches and root
Break nodes. Missing connections are the higher-priority signal. The verifier ignores reroutes/switches by
resolving to the effective source, but it does not hide intentionally added type-conversion nodes.
