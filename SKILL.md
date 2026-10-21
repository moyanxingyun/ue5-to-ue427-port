---
name: ue5-to-ue427-port
description: 把 UE5（5.x）资源包、材质、蓝图摆放物、贴花包迁移到 UE 4.27 项目时使用：探查、导出、简化或完整重建材质、摆回原位、收尾诊断。
---

# UE5 → UE 4.27 资源迁移

UE5 的 .uasset 在 4.27 打不开。做法永远是两段：**UE5 里导出（FBX / PNG·TGA / JSON），4.27 里重建**。
脚本在本仓库 `scripts/`，每个资源包一份 `config.json`（复制 `scripts/config_example.json`，填写 UE5 项目、导出目录、4.27 目标目录）。
`references/` 里有四类已跑通的实例：分层母材质完整重建、大型资源包简化重建、蓝图摆放物重建、贴花包重建。

## 工作规则（必须遵守）
1. **脚本由用户自己在编辑器里运行。** 写好脚本 → 放到用户的脚本目录 → 告诉用户在哪个引擎版本、哪个关卡、Output Log 的 Cmd 模式下运行：`py "完整路径"`。
2. **放进去后读回关键行核对**，确认用户磁盘上是最新版本。
3. **每次修改用新文件名**（_v2、_v3…），不覆盖旧版。
4. **所有改动可还原**：备份 JSON + Restore 脚本，或 `MODE = "restore"`；会改关卡的脚本先提醒保存。
5. **每个脚本写报告文件**（report.txt / json），用户说"跑完了"后读报告和 `Saved/Logs/<项目>.log`，不凭猜测下结论。
6. 只读诊断脚本优先；需要改资产时先 dry-run / report 模式。
7. 不在仓库或输出里包含任何第三方资源包的资产文件，只处理用户本地已有的资源。

## 流程
```
0 探查   ue5/probe_pack.py → summary.txt（母材质种类、静态开关组合数、Custom 节点、UE5 独有节点、Nanite、LOD、蓝图、植物）
         ue427/probe_ue427.py → probe_427.json（4.27 实际可用的 Python 接口和节点口名称）
1 分类   普通资产包 / 分层母材质包 / 蓝图摆放物 / 纯贴图包（可组合）
2 导出（UE5，只写磁盘）
         export_meshes（网格体+贴图+materials.json+textures_map.json）→ export_all_mis（颜色变体实例）
         → export_foliage（植物，单独目录）/ export_bp_instances（选中蓝图，四元数）/ export_bp_spawn（构造脚本蓝图）
         / export_texture_pack（贴花，TGA 保留 alpha）/ dump_graphs（完整重建用：母材质+递归所有函数的节点文本）
3 重建（4.27）
         简化：import_assets / import_foliage / import_decals
         完整：material_transplant（离线检查 → 测试模式 1 个组合 → 分批全量，批间重启 UE → verify 对照）
         摆放：rebuild_from_instances → attach_to_root
4 收尾   tex_cap、lod_distance、streaming_pool；diag_lod / diag_texture / inspect_selected 只读诊断
```

## 决策：简化重建还是完整重建
- **默认简化**：只还原基础层（BaseColor×Tint/亮度/对比/去饱和、Normal×强度、ORM、Emissive），+ Global 实例一键整体调色。快、稳。
- **完整重建**仅当：该材质决定整个包的外观且简化后明显失真（如分层建筑母材质），或之后需要用原参数调色。
- 完整重建前探查必须满足，否则先问用户：静态开关组合 ≤ 50；无 UE5 独有节点（Substrate、Material Layer 资产、Nanite 位移、VT 采样）；Custom 节点已人工检查。
- **两套并存**：完整重建时保留简化版实例，提供 switch_fallback 一键切回。

## 完整重建要点（细节见 references/material_transplant.md）
- 贴图导回**原 /Game 路径**并恢复 sRGB / 压缩 / 法线绿通道，节点引用直接对上。
- 4.27 Python 不能给材质实例设静态开关 → **按实例实际用到的开关组合烘焙母材质**（实例：172 个材质实例 → 31 个组合），函数只在依赖的开关值不同时生成变体（名字带 md5 后缀）。开关节点直接选好分支连线。
- Reroute / Named Reroute 换成直连（4.27 设不了 Declaration）。
- 类型：UE5 静默截断 float4→float3，4.27 报错 → 通道数推断，必要时显式取 RGB；Lerp alpha 必须标量。
- **UE5 Power = PositiveClampedPow**，4.27 是 pow(abs) → 所有 Power 重建为 pow(max(Base,0),Exp)（不改会出现斑块、凹凸反转）。
- Material Attributes 根节点接不上 → Break 后各属性分别接材质输入，use_material_attributes=False。
- 工程：离线解析检查、测试模式、MASTER_RANGE 分批（每批 ~8 个母材质，批间重启 UE）、已存在跳过可续跑、rebuild_log.json、重建结果导出节点文本与原 dump 对照。

## 4.27 必知的坑
| 问题 | 写法 |
|---|---|
| VectorParameter 没有 "RGB" 输出口，**连线失败不报错** | 用 R/G/B 口 + 两个 AppendVector；每次 connect 检查返回值写进报告 |
| `MaterialProperty.MP_WORLD_POSITION_OFFSET` 不存在 | 在 dir(MaterialProperty) 里按 WORLD+OFFSET 查找 |
| 没有 MaterialExpressionLength | 用 MaterialExpressionDistance |
| 材质图 expressions 受保护不可读 | 用 get_used_textures / get_*_parameter_names / get_material_property_input_node |
| 新建 ComponentMask 默认勾 R+G | 四个通道都显式设置 |
| 贴花只设 decal_blend_mode 编译失败 | 同时 blend_mode = BLEND_TRANSLUCENT |
| 深色贴图乘大 Tint 后高光发白 | lerp(AvgColor, tex, Contrast)×Tint，再 Min(MaxColor) |
| `unreal.Rotator(a,b,c)` 位置参数是 (roll,pitch,yaw) | 关键字参数或四元数 + set_actor_transform |
| 静态 Actor 挂不到可移动父物体 | 根节点先设 Static |
| 选中几千个 Actor / Merge Actors / 打组 会卡死崩溃 | 空根节点 attach（KEEP_WORLD） |
| 脚本中途出错留下未保存的半成品，重跑会叠加 | 重跑前 EditorLoadingAndSavingUtils.reload_packages 脏包 |
| 自动生成 LOD 在屏幕 0.5/0.75 就切 | 导入时设屏幕大小，或 r.StaticMeshLODDistanceScale 0.35 写进 DefaultEngine.ini [SystemSettings] |
| 导出跳过 LOD1 文件夹，引用 *_LOD1 的找不到 | 回退同名 *_LOD0 |
| 贴图卡在 64×64 | 不是池大小问题，是 IO/DDC 卡住：重启或清 DDC |
| UE5 项目打开错导致导出 0 个 | 报告里写项目名和资产数，0 时立即提示 |

## 不能迁移（直接告诉用户，给替代方案）
蓝图逻辑和构造脚本（只能记录生成结果）、Niagara、地形/植被类型资产、体积云和天空设置、Nanite 专属效果、Lumen 相关设置、Substrate、虚拟纹理、UE5 Material Layer 资产。

## 每阶段检查
- 导出后：报告里资产数 > 0、失败列表、项目名正确。
- 导入后：日志无 "Failed to compile"、报告无 FAIL 连线、贴图设置（sRGB/法线/Masks）正确、视口实拍截图确认。
- 收尾前：画质设置极高、LOD 诊断无 EARLY 堆积、贴图无卡低 mip、关卡已保存。
