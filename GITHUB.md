# 开发、构建与分发

公开仓库：[Ku1o/StarPoint-Character-Studio](https://github.com/Ku1o/StarPoint-Character-Studio)。这是从明确源码文件清单建立的独立仓库，不携带原服务端工作区或其 Git 历史。

当前公开源码为 0.7.2 预览版。工具面向角色创作者，官方角色资源包、个人工程和程序源码分开管理；资源包不进入 Git 历史，也不随程序 ZIP 自动打包。

## 目录

- `studio.py`、`desktop_host.py`：本机服务、桌面窗口和单实例生命周期。
- `studio_core.py`、`studio_compile.py` 及各编辑模块：工程、导入、编辑、校验与编译。
- `web/`：创作者界面和预览。
- `core/`：随工具发布的共用离线模块、能力枚举和原许可；见 `CORE-PROVENANCE.md` 的来源记录。
- `integrations/mod/`：MOD 宿主适配入口；调用方法见 `MOD-INTEGRATION.md`。
- `docs/USER_GUIDE.md`：面向创作者的使用说明。
- `tests/`：独立源码检查及需要本地资源的专项验收脚本。
- `app_metadata.py`：工具版本、名称与来源链接的统一定义。
- `distribution_sources.py`：源码分发白名单。

`templates/`、`definitions/`、`projects/`、构建产物、官方图片/声音、服务端配置和账号信息不进入源码仓库。新增源文件后应同步更新源码分发白名单；不能递归复制工作区作为发布内容。

## 运行与检查

推荐 Python 3.13。源码自带 `core/`，可在全新目录运行：

```powershell
python -m pip install -r requirements-desktop.txt
python studio.py --open
```

只运行离线单元检查无需安装桌面运行库：

```powershell
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
node --test tests/preview_layout.test.js
```

原 MOD 宿主专用的检查在独立源码中会明确跳过；不要为了通过它而复制私有仓库。`*_ui_smoke.py` 等专项脚本需要 Playwright、Edge，部分还需由操作者指定本地资源包路径；这些素材不进入 CI。

## Windows 构建

```powershell
python -m pip install -r requirements-build.txt
python build_distribution.py --output build/release-0.7.2
```

输出目录必须尚不存在。构建生成可解压使用的程序 ZIP、逐文件清单和本地维护用的校验摘要；公开 Release 只上传程序 ZIP，不上传单独 `.sha256` 附件。ZIP 中保留对应的 `source/` 与第三方许可。代码、版本号、使用说明和源码白名单一并打包，不扫描旁边的模板或工程。

0.7.2 的 Windows 包会把 `星点角色工坊.exe.config` 放在 EXE 同级，允许 .NET Framework 加载随包携带的 Python.NET 与 WebView2 托管程序集。这样 Windows 从下载 ZIP 传播 Internet 区域标记时，创作者不需要逐个 DLL 解除锁定。配置只针对工具明确携带的本地依赖，不代表可以加载不受信任的外部程序集。

若只需导出干净源码：

```powershell
python distribution_sources.py --output build/source-export
```

发布前在导出的独立目录运行检查和构建，验证它没有依赖原 MOD 目录回退路径。预览版本在 GitHub Releases 标记为 Pre-release；公开下载附件只提供程序 ZIP 和独立资源 ZIP，不上传单独 `.sha256` 文件；本地校验文件及逐文件记录用于维护核验。

## 修改与兼容

版本变更修改 `app_metadata.py`，同步 README、更新记录与使用说明中的适用版本。服务、原生窗口、界面和打包版本均从该模块读取。

工程格式与游戏接入契约分别由 `studio_core.py` 和 `character_contract.py` 维护。保留旧工程兼容和原始字段，不把草稿标记成游戏已验收。`core/` 的适配需保留来源声明，并更新其变更说明；原项目的接口变化应分别验证 MOD 内入口和独立入口。

### 工程升级兼容

0.7.2 新增「工程与升级」入口。创作者在旧版保存并退出后，将新版完整解压到新目录，从新版选择旧工具目录或其中的 `projects/` 迁入。迁入前会校验工程格式、素材和历史；成功后复制到新目录，旧目录保留，编号冲突会建立副本，重复迁入会跳过相同版本。保存覆盖前保留原始 JSON，历史恢复也建立副本；损坏或不支持的工程留在列表中并提示恢复，不会被静默删除。

升级不会重新下载官方模板。`templates/` 与 `definitions/` 可以继续使用原资源包；工程创建时复制的素材和用户编辑独立保存。发布说明必须同时写清旧版回退方式：保留旧工具和旧 `projects/`，不要把未来格式写回旧程序。

资源库生成依赖原项目中另行维护的只读官方基线和资源工具，不是构建本工具的前置条件。已有模板和定义目录按各自 schema、版本和哈希校验；更新工具不得重写用户的工程或资源库。


## 角色资源发布

角色资源保留在 Releases 附件中，不写入 Git 源码或程序 ZIP。当前 1.4.54-r3 库约 3.49 GiB，按 GitHub 单文件必须小于 2 GiB 的限制分为 `StarPoint-CN-Character-Resources-1.4.54-r3-1of2.zip` 和 `StarPoint-CN-Character-Resources-1.4.54-r3-2of2.zip`。

两卷都是普通 ZIP，文件名集合互不重叠，解压到同一目录后组成完整的 `templates/` 和 `definitions/`。原始角色包、音频包、缩略图及定义文件的字节保持一致，只更新安装说明和分卷元数据；仍沿用资源版本 1.4.54-r3。

后续资源发布需逐文件核验两卷并集与完整资源清单一致、角色数量和版本一致、每卷小于附件限制；上传完成后核对远端附件大小和摘要。不要仅按下载数量声称完整，也不要在新版本中重新上传单独 `.sha256` 附件。GitHub 自动生成的两份 Source code 链接保留，创作者无需下载。
