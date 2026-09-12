# MOD 角色工坊与独立创作版

0.7.1 使用同一套制作界面、工程格式、词条生成器、资源编译器与预览代码，提供原 MOD 内的角色工坊页签和独立 Windows EXE 两个入口。以 MOD 内的角色工坊为完整流程接入入口，独立分发提供同一工坊的创作者界面。交给创作者仅两份 ZIP：工具、完整角色资源；后者合并官方定义、图片与声音。MOD 接驳是原项目更新，不另打第三个创作者包。

## 本版接驳

`wf_gui.py` 的 `/studio/open` 启动 `wf_character_studio.StudioModule`。它只在本机创建角色工坊服务；`wf_gui.html` 用 iframe 显示同一份工坊界面。宿主和 iframe 通过指定来源的消息完成保存后切换，CSP 只允许当前本机 MOD 页面嵌入。

源码目录排列为 `tools/fantasy-gauntlet-mod-tools/` 与 `tools/character-studio/`。在原 MOD 环境中启动修改器后，点击“角色工坊”。制作数据保存在 `character-studio/projects/`，不使用原 GUI 的现役角色克隆/写表接口，不调用发布、设备、服务器或同步接口。两个模式按工程目录互斥，先关闭持有该目录的实例，再从另一个入口继续；工程也可通过 `.wfchar.zip` 传递。

原 MOD 的 `composer_generate`、目录、元数据与空白行规则现在委托 `wf_ability_composer.py`。原 GUI 仍提供自己的目标表、角色属性和固有状态上下文；独立版使用随定义包保存的官方空白行与来源角色属性。

## 现成词条选用

`wf_gui.studio_ability_library` 复用 `_build_search_index` 和 `composer_row` 读取当前 MOD 能力库；把只读回调传给同一工坊服务。独立版 `AbilityLibrary` 按离线定义的真实引用建立角色能力索引。界面支持搜索、分页、单行或多行选用、组件取材、追加到指定槽位与撤销。选用前重新读取来源并比对指纹，类型不匹配、异常行、过期工程或源变更均拒绝写盘。原始参考定义保持不变；选用来源与原行保存在工程中。专属条件或资源引用保留，正式转换时仍需核对与重绑。

## 通道与组件编辑

`effect_channels.py` 使用共用 PartsAnimation 解码器提供的片段实例路径，生成稳定通道。原图多次实例化时互相独立；源序列、编辑通道和关键帧一起存入工程。老工程可按特效读取原始参考文件升级。预览和编译共享相同变换规则；修改后的通道合成为新的 PartsAnimation，再解码验收矩阵、时序、图片及声音。

`ability_editor.py` 复用 MOD 的元数据、行布局、空白行、中文描述和格式校验，提供单行草稿、实时检查、应用、复制/移动接口。组件按字段名和块偏移取用，不覆盖其他块、表头或未知扩展列。保存保持工程版本校验和不可变来源；新编辑的活动枚举编号与数值额外核对范围。专属 ID / 技能路径不凭空生成，仍由后续新角色接入转换处理。

## 数据与编译

- `starpoint-character-studio-v1` 工程保存身份、美术、声音、时间轴、参考文件与制作数据。旧工程继续可读。
- `gameplay` 是设计备注，沿用 `starpoint-gameplay-design-v1`，不会自动覆盖实际条目。
- `nativeGameplay` 使用 `starpoint-native-gameplay-v1`，保留带哈希的原始定义、真实队长技/能力引用、可编辑六槽能力和主动技能版本。未知字段保留；原始异常行只允许按原值保存，修改后的行继续严格检查。
- `starpoint-character-definitions-v1` 独立定义包按 character 真实引用读取队长技、六槽能力、主动/切换技能，并保留成长、玛纳板原始数据、语音绑定和现有演示回放。它不包含游戏运行引擎，也还没有完整的玛纳节点依赖闭包。
- 编译包的 `native-draft/` 含能力表、队长技表和嵌套技能表，使用原 MOD 的 orderedmap 编解码并回读核对。键为 `ability_1` 至 `ability_6`、`leader`、`skill` 等临时槽位，不是游戏 ID，不能把这些单角色草稿表覆盖为完整主表。
- `MOD角色接入契约.json` 继续使用 `starpoint-character-mod-handoff-v1`，增加可编辑 native 数据。`modStudioProjectImport=true` 表示 MOD 工坊入口可打开工程；`directModImport=false` 表示尚不是旧 character-pack 发布格式；`gameReady=false` 保持独立记录。

来源键不能由角色 ID 推算。例如官方角色 10 实际引用队长技 3 和能力 81–86。正式转换时应为每个草稿槽重新分配引用，避免覆盖模板或共享词条。

## 接下来必须补齐

1. 隔离的新角色转换器：用现有 `wf_character_workspace` 与 `wf_character_pack` 生成完整角色包并执行 preflight；分配角色/能力/玛纳节点 ID，合并主表，重写资源及技能程序引用，保持原角色独立。
2. 成长、玛纳节点、服务端数据与客户端资源闭包：继续核对全部绑定、Android/iOS 平台纹理、UI 图集与预载依赖。能力草稿、模板参考和发布产物不能混为同一状态。
3. 客户端战斗预览：详见 `PREVIEW-RUNTIME.md`。当前素材时序预演不能代替移动、碰撞、命中、条件与镜头的运行验收。
4. 存档与完整流程验收：仅在实际分配游戏 ID/修改角色表后验证存档兼容、成长和游戏内流程。本版未改玩家存档、数据库或现役 ID。

## 验证方法

单元测试验证真实引用、未知字段保留、源校验、坏输入不写盘、数值单位和编译回读。`tests/integration_ui_smoke.py` 使用原 MOD 实际 Handler 与 HTML，管理端无关接口使用测试数据；验证官方模板自动载入定义、词条编辑、保存后切换、两个入口往返与素材预览。`tests/native_portable_smoke.py` 在不含 Python 的 PATH 下验证真实 EXE 的定义包导入、编辑、重开与草稿编译。另核对 505 个官方定义和 388 组共用生成器组合。

这些是离线与桌面检查，尚未执行真实游戏发布或完整战斗场景验收。

0.7.1 共用独立 UI 素材映射、非破坏裁剪、单图导出和图集检查。UI 编译从对应 PNG 或用户裁剪生成，不再从大立绘统一派生所有用途。`handoff/ui-images.png` 与 JSON 是创作者交接拼图，不是游戏的 illustration 图集；MOD 接入仍需使用目标客户端的图集、定位、形状蒙版及平台纹理契约。


## 独立源码仓库与 MOD 宿主

本仓库独立运行时优先加载 `core/`。原项目以同级 `tools/character-studio/` 形式维护时，仍可复用旁边的 `fantasy-gauntlet-mod-tools/`，两种方式使用同一套工坊代码。

本仓库保留 `integrations/mod/wf_character_studio.py` 宿主适配器。对已具备「角色工坊」页面的 MOD 宿主，可将适配器作为模块使用，创建 `StudioModule(application=工坊源码目录, projects=工程目录, templates=模板目录, definitions=定义目录)`，再通过 `open(parent_origin, ability_provider)` 启动并取得嵌入地址，退出宿主时调用 `close()`。`parent_origin` 必须是本机 `http://127.0.0.1:端口`；不能直接作为远程服务嵌入。

适配器本身不会为任意历史版 MOD 自动添加页签，宿主仍需接入页面、保存切换和能力库回调；原项目中的既有入口负责这些工作。创作者使用独立 EXE，无需额外安装接驳包。两种入口都可导出、打开同一种 `.wfchar.zip` 工程；同一工程目录同时只由一个入口持有。
