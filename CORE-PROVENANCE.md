# 共用模块来源记录

本目录相关代码源于 [原 MOD 修改器](https://github.com/kuronzzhan-droid/startpoint-cn-mod-tools)，随工具提供独立运行所需的实现和数据。

核对时间：2026-09-12；用于比较的上游 master 提交：[`fd433b05bf6f`](https://github.com/kuronzzhan-droid/startpoint-cn-mod-tools/commit/fd433b05bf6f2ac9cb4b7c415b5a0f40f469ef21)。这个提交是核对锚点，并非所有本地适配的创建基点；原文件内说明和许可均保留。

| 文件（core/） | 来源与变更 |
| --- | --- |
| `wf_mod_tool.py` | 源于原项目的本地适配版本 |
| `wf_dsl.py` | 源于原项目的本地适配版本 |
| `wf_flatomo_preview_render.py` | 所核对的上游提交未包含此文件；沿用本地 MOD 共用实现 |
| `wf_assets.py` | 源于原项目的本地适配版本 |
| `wf_character_requirements.py` | 与所核对的上游文件一致 |
| `wf_ability_composer.py` | 所核对的上游提交未包含此文件；沿用本地 MOD 共用实现 |
| `wf_describe.py` | 源于原项目的本地适配版本 |
| `wf_client_legality.py` | 与所核对的上游文件一致 |
| `ability_enum_map.json` | 源于原项目的本地适配版本 |
| `词条条件代码全表.md` | 源于原项目的本地适配版本 |
| `LICENSE` | 与所核对的上游文件一致 |

本工具的适配重点包括离线导入、图层与时间轴回读、角色素材要求、能力词条拆解和组合。`wf_ability_composer.py` 在原 MOD 集成工作中抽为共用模块，独立版与 MOD 内使用相同实现。这里只打包工坊实际依赖的模块；旧 MOD 命令行中引用的其他可选命令不作为独立工坊的功能提供。

## 共享模块同步策略（2026-10-06 补充）

本工具 `core/` 下的模块与服务端 MOD 仓库 `tools/fantasy-gauntlet-mod-tools/` 中的同名文件属于**同源共享模块**：内容必须保持一致，唯一允许的差异是行尾（同一份内容在不同克隆/配置下会检出为 CRLF 或 LF）。

| `core/` 模块 | 与服务端同名文件 | 2026-10-06 核对状态 |
| --- | --- | --- |
| `wf_mod_tool.py` | 逐字节一致 | 一致 |
| `wf_dsl.py` | 逐字节一致 | 一致 |
| `wf_assets.py` | 逐字节一致 | 一致 |
| `wf_describe.py` | 逐字节一致 | 一致 |
| `wf_ability_composer.py` | 逐字节一致 | 一致（本次同步） |
| `wf_client_legality.py` | 内容一致、仅行尾不同 | 一致（行尾差异） |
| `wf_character_requirements.py` | 逐字节一致 | 一致 |
| `wf_flatomo_preview_render.py` | 逐字节一致 | 一致 |
| `ability_enum_map.json` | 逐字节一致 | 一致 |
| `词条条件代码全表.md` | 逐字节一致 | 一致 |
| `LICENSE` | 逐字节一致 | 一致 |

**同步判据**：比较两份文件"忽略行尾后的内容"；内容不同即视为未同步。

**实践规则**：

1. 修改共享模块（解析器合法性规则、能力组合器、DSL 编解码、描述器、枚举表）时，工坊侧 `core/` 与服务端 `tools/fantasy-gauntlet-mod-tools/` 必须同批修改；
2. 仅工坊侧需要的适配（独立运行所需的路径/依赖差异）必须在提交信息中登记，不得静默漂移；
3. 提交前用下列命令核对（工坊作为 `tools/character-studio` 嵌在 MOD 仓库时）：

```powershell
$core = '.\core'; $mod = '..\fantasy-gauntlet-mod-tools'
Get-ChildItem $core -File | ForEach-Object {
  $peer = Join-Path $mod $_.Name
  if (Test-Path $peer) {
    $a = (Get-Content -Raw $_.FullName) -replace "`r`n","`n"
    $b = (Get-Content -Raw $peer) -replace "`r`n","`n"
    if ($a -ne $b) { "DRIFT: $($_.Name)" }
  }
}
```

## 门禁归属表（2026-10-06 补充）

工坊只负责"资源与工程是否合规、能否导出正确的候选"；资源链、版本边与交付由服务端仓库负责。两层通过**候选包 + 回执**衔接，不互相 import。

| 层 | 门禁 | 实现/入口 | 回执 |
| --- | --- | --- | --- |
| 工坊 | 官方模板键集与 deepcopy（timeline 四键等） | `studio_compile.py` | 键集断言 |
| 工坊 | `_sp` 合成帧与状态声明（基础态用纯本体） | `pixel_import.py`、`web/pixel-import.js`、动作卡声明字段 | 导入提示 + 工程声明 |
| 工坊 | 像素图集锚点（客户端语义 `fx/fy`）逐帧回归 | `studio_compile.py` | 锚点差值 = 0 |
| 工坊 | UI 裁剪与 8 类形状遮罩（比例 ≤0.3%） | `portrait_editor.py` | 覆盖/形状比对 |
| 工坊 | 声明行 schema 与先例（Bool/枚举/`(None)`） | `core/wf_client_legality.py`、`core/wf_ability_composer.py` | 问题清单 |
| 工坊 | 包内必读、声明字段、三段式检查 | `studio_core.py` | 检查报告 |
| 服务端 | 输出路径断言（禁 `.cdn`；`active/` + manifest + `audit/`） | `tools/fantasy-gauntlet-mod-tools/wf_character_gates.py`、`wf_character_flow.py` | fail-closed CLI 输出 |
| 服务端 | outer key union 与声明行合并审计 | 同上 | 键集差异回执 |
| 服务端 | 结构契约（timeline/atlas/frame/parts 逐键） | `wf_character_gates.py` | 逐键 diff |
| 服务端 | 发布链（边号、manifest、audit、HTTP 轻量复核） | `wf_character_flow.py` + 发布脚本 | manifest/audit/回执 |

许可全文见 [LICENSE](LICENSE)，总来源声明见 [NOTICE.md](NOTICE.md)。
