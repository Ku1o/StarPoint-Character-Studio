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

许可全文见 [LICENSE](LICENSE)，总来源声明见 [NOTICE.md](NOTICE.md)。
