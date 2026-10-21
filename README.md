# PortKit / UE5 → UE 4.27 迁移工具箱

## 用途

PortKit 用于把 UE5 资源包导出为 FBX、TGA、JSON 和材质节点文本，再在 UE 4.27
中重建网格体、简化材质或完整材质图、贴花和蓝图摆放实例。所有资源路径、Unreal
目录和运行参数都由独立 `config.json` 提供。

## Purpose

PortKit exports UE5 packs as FBX, TGA, JSON and material node dumps, then
rebuilds meshes, simplified or full materials, decals and Blueprint placement
instances in UE 4.27. All filesystem paths, Unreal folders and run options come
from a per-pack `config.json`.

## 环境

- UE5 导出脚本：Unreal Engine 5.4 Editor Python
- UE4.27 重建脚本：Unreal Engine 4.27 Editor Python 3.7
- 离线解析与测试：普通 Python 3.7+
- UE 内的 `.uasset` 不能跨版本直接打开；迁移必须经过磁盘中间格式

## Environment

- UE5 exporters: Unreal Engine 5.4 Editor Python
- UE 4.27 rebuilders: Unreal Engine 4.27 Editor Python 3.7
- Offline parser and tests: plain Python 3.7+
- `.uasset` files cannot be opened across these engine versions; migration must
  use disk-based intermediate formats.

## 快速开始

1. 复制 `scripts/config_example.json` 为你的 `config.json`。
2. 填写 UE5 资源目录、导出目录、UE4.27 目标目录和材质参数名称。
3. 在 UE5 中运行 `scripts/ue5/probe_pack.py` 和所需的导出脚本。
4. 在 UE4.27 中运行 `scripts/ue427/probe_ue427.py`。
5. 优先使用 `import_assets.py`、`import_foliage.py` 或 `import_decals.py`
   做简化重建。
6. 只有材质必须完整还原时，才运行 `material_transplant/planner.py`、
   `build_ue427.py` 和 `verify_ue427.py`。
7. 每个阶段先读 `paths.reports` 中的 JSON/TXT 报告，再继续下一阶段。

入口脚本均支持 `--config PATH`，也可设置 `PORTKIT_CONFIG`。修改公共模块后，
入口脚本会在启动时重新加载共享模块，无需重启 UE。

## Quick start

1. Copy `scripts/config_example.json` to your own `config.json`.
2. Fill in the UE5 asset roots, export folders, UE 4.27 destinations and
   material parameter names.
3. Run `scripts/ue5/probe_pack.py` and the required exporters in UE5.
4. Run `scripts/ue427/probe_ue427.py` in UE 4.27.
5. Prefer `import_assets.py`, `import_foliage.py` or `import_decals.py` for a
   simplified rebuild.
6. Use `material_transplant/planner.py`, `build_ue427.py` and
   `verify_ue427.py` only when the full material graph must be preserved.
7. Review the JSON/TXT reports under `paths.reports` before each next stage.

Every entry script accepts `--config PATH` or `PORTKIT_CONFIG`. Entry scripts
reload shared modules at startup, so edits take effect without restarting UE.

## 限制

- 不迁移蓝图逻辑、构造脚本行为、Niagara、地形/植被类型资产、Lumen、
  Nanite 专属效果、Substrate、虚拟纹理和 UE5 Material Layer 资产。
- 完整材质重建可能按静态开关组合生成大量母材质；组合数受配置上限约束。
- UE4.27 Python 不暴露的接口会记录到报告，例如部分版本中的
  WorldPositionOffset 引脚；脚本不会静默假设连线成功。
- UE5 与 UE4.27 的光照、色调映射和材质模型仍有差异，必须通过编辑器实拍验证。

## Limitations

- Blueprint logic, construction-script behavior, Niagara, landscape/foliage type
  assets, Lumen, Nanite-specific effects, Substrate, virtual textures and UE5
  Material Layer assets are not migrated.
- Full material reconstruction can bake many static-switch combinations into
  separate masters; the configured maximum is enforced.
- APIs unavailable to UE 4.27 Python are recorded in reports. For example,
  some 4.27 builds do not expose WorldPositionOffset; the scripts do not assume
  a connection succeeded.
- Lighting, tone mapping and material models still differ between UE5 and
  UE 4.27 and require in-editor visual verification.
