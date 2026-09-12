# 星点角色工坊 · StarPoint Character Studio

面向角色创作者的 Windows 本地工作台：从官方参考模板或原创工程开始，制作立绘、界面图片、像素动作、技能特效、声音与能力草稿。

**当前版本：0.7.1 预览版。** 工具基于 [kuronzzhan-droid/startpoint-cn-mod-tools（原 MOD 修改器）](https://github.com/kuronzzhan-droid/startpoint-cn-mod-tools) 开发，复用并扩展资源编码、动画预览和能力编辑实现。源码采用 GPLv3，见 [来源声明](NOTICE.md) 和 [LICENSE](LICENSE)。

[下载 Windows 版](https://github.com/Ku1o/StarPoint-Character-Studio/releases) · [完整使用说明](docs/USER_GUIDE.md) · [更新记录](CHANGELOG.md) · [反馈问题](https://github.com/Ku1o/StarPoint-Character-Studio/issues)

## 解压后使用

1. 从 Releases 下载 `StarPoint-Character-Studio-版本号-Windows.zip`，完整解压到可写目录。
2. 双击 `星点角色工坊.exe`；无需安装 Python 或原 MOD 修改器。`_internal/` 必须和 EXE 一起保留。
3. 选择「原创角色」，或另行安装资源包后选择「基于角色模板」。
4. 按左侧步骤制作，查看预览，在「检查与交付」中导出。工程自动保存在 `projects/`，可导出 `.wfchar.zip` 备份或转交。

版本号显示在窗口标题和界面左上角，点击可查看使用提示、保存完整说明及查看来源。重复打开同一工程目录会唤回已打开的窗口；关闭窗口会先保存工程，保存失败会保留窗口。

桌面版需要 Microsoft Edge WebView2 Runtime 和 .NET Framework 4.6.2+。组件准备好后可离线制作。升级时先关闭旧版并备份工程，再使用完整新版程序目录，保留原 `projects/`、`templates/` 和 `definitions/`。

## 工具与资源包分开

Git 源码与工具 ZIP **不包含官方角色资源或个人工程**；官方资源只作为独立 Release 附件提供。制作原创角色无需官方素材包。

官方角色资源已作为本仓库的 Release 附件提供，和工具分开下载：

| 下载项 | 说明 |
| --- | --- |
| [Windows 工具 ZIP](https://github.com/Ku1o/StarPoint-Character-Studio/releases/download/v0.7.1/StarPoint-Character-Studio-0.7.1-Windows.zip) | 先完整解压，双击 EXE 使用 |
| [角色资源 1/2](https://github.com/Ku1o/StarPoint-Character-Studio/releases/download/v0.7.1/StarPoint-CN-Character-Resources-1.4.54-r3-1of2.zip) | 与 2/2 都要下载，内容解压到工具目录 |
| [角色资源 2/2](https://github.com/Ku1o/StarPoint-Character-Studio/releases/download/v0.7.1/StarPoint-CN-Character-Resources-1.4.54-r3-2of2.zip) | 与 1/2 都要下载，内容解压到同一个工具目录 |

资源总量约 3.49 GiB，因 [GitHub 单附件大小限制](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)，分成两份普通 ZIP（每份约 1.74 GiB）。**两份都解压到工具目录即可，不需要合并压缩文件，也无需另装解压软件。** 选择「解压全部」时将目标设为工具目录，避免额外套一层 `1of2` / `2of2` 文件夹。

两卷装好后重新打开工具。最终目录应为：

```text
星点角色工坊/
  星点角色工坊.exe
  _internal/
  templates/       官方美术、动作、特效、声音模板
  definitions/     对应角色定义与离线词条库
  projects/        自动建立的个人创作工程
```

已安装完整 `StarPoint-CN-Character-Resources-1.4.54-r3.zip` 的用户无需重新下载；本次只调整网上分卷方式。该配套版本覆盖国服 1.4.54 的 505 个角色及特殊条目，资源缺项和预览限制会在模板中分别显示。模板新建后复制为独立工程，后续编辑不会修改模板库。

页面下方的 `Source code (zip / tar.gz)` 是 GitHub 自动提供的源码；直接使用 Windows 工具无需下载它们，也无需单独下载校验文件。

## 可以制作什么

| 模块 | 主要功能 |
| --- | --- |
| 立绘与界面 | 按用途读取官方原图，基础/进化切换，从母版精确裁剪，单图导出与替换 |
| 像素动作 | 常用动作槽位，批量 PNG / 目录导入，精灵图切分，帧序、时长和变换编辑，整段播放 |
| 技能制作 | 序列特效，官方可解析特效的通道编辑与关键帧，多轨道和声音同步预览 |
| 声音与台词 | 角色语音、技能音效、台词备注、音频事件编排 |
| 技能与能力 | 词条库取材，条件、触发、对象、效果拆解组合，六槽能力设计与校验 |
| 检查与交付 | 可编辑工程、源素材、离线编译产物、实际图集查看和编译后回读预览 |

导入格式、尺寸、帧数和声音要求请看 [素材准备](docs/USER_GUIDE.md#美术素材如何准备)。

## 当前边界

这是角色制作预览版。完整官方技能的战斗还原（移动、命中、目标、镜头、条件分支）尚未完成；部分复杂原生特效仍有渲染限制。工具会显示具体限制，不能将素材播放视为完整战斗验收。

创作者可以交出工程和离线编译产物。正式游戏 ID、角色主表与玛纳板、客户端专用 UI 图集和 Android/iOS 资源绑定仍由接入方完成。工具不修改玩家存档，也不直接把角色发布到游戏。

与原 MOD 修改器共用制作服务、工程格式和核心实现；在已接入角色工坊的 MOD 版本中可继续编辑同一工程。接驳方式见 [MOD-INTEGRATION.md](MOD-INTEGRATION.md)，预览实现与缺口见 [PREVIEW-RUNTIME.md](PREVIEW-RUNTIME.md)。

## 从源码运行

建议使用 Windows 与 Python 3.13；本版在 Python 3.13 验证。源码自带 `core/`，不需要私有服务端仓库。

```powershell
python -m pip install -r requirements-desktop.txt
python studio.py --open
```

资源目录可用 `--templates <目录>` 和 `--definitions <目录>` 指定，工程目录用 `--projects <目录>` 指定；`--no-open` 只启动本机服务，供浏览器调试。

开发检查和 Windows 打包见 [GITHUB.md](GITHUB.md)。Windows ZIP 同时携带对应源码及第三方许可；官方素材、个人创作与软件源码分别管理。
