# Paths and reports

All operational paths and Unreal object folders are read from one JSON file.

Selection order:

1. `--config PATH`
2. `PORTKIT_CONFIG`
3. `config.json` beside `scripts/portkit_config.py`

Copy `scripts/config_example.json`, replace its placeholders, then run each script with `--config`.
Reports default to `paths.reports`; scripts that mutate assets also keep a backup or restore mode.

Every script is resumable unless its options explicitly request `rebuild_existing`:

- UE5 exports skip files already on disk.
- 4.27 imports skip existing textures and meshes.
- Full material reconstruction skips existing functions/masters unless rebuild is requested.
- Texture-size changes have a JSON backup and `mode="restore"`.
- Fallback-material switching stores the original slots in JSON and supports `mode="restore"`.
