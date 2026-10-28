# Changelog

All notable changes to PortKit are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
PortKit uses semantic versioning; Editor compatibility is documented in the README.

## [0.1.0] - 2026-10-28

### Added

- UE5 pack probing for materials, switch combinations, mesh and texture metadata.
- UE 4.27 runtime probing and resumable import workflows.
- Mesh, texture, decal, foliage, Blueprint placement and material graph exporters.
- Simplified material reconstruction with a fallback path.
- Full material transplant planning, batching and verification.
- Placement rebuild and large-batch attachment helpers.
- LOD, texture, selected-asset and color diagnostics.
- Config validation, JSON/text reports and recovery-oriented workflow rules.
- Unit tests for T3D parsing, material rules, planner contracts and foliage data.

### Known limitations

- Blueprint logic, Niagara, Nanite-only effects, Lumen, Substrate, virtual textures
  and UE5 Material Layer assets are not migrated.
- Fixture-dependent tests require private reference corpora.
