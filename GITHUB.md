# 开发、构建与分发

公开仓库：[Ku1o/StarPoint-Character-Studio](https://github.com/Ku1o/StarPoint-Character-Studio)。这是从明确源码文件清单建立的独立仓库，不携带原服务端工作区或其 Git 历史。

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
python build_distribution.py --output build/release-0.7.1
```

输出目录必须尚不存在。构建生成可解压使用的程序 ZIP、SHA-256 文件和逐文件清单；ZIP 中保留对应的 `source/` 与第三方许可。代码、版本号、使用说明和源码白名单一并打包，不扫描旁边的模板或工程。

若只需导出干净源码：

```powershell
python distribution_sources.py --output build/source-export
```

发布前在导出的独立目录运行检查和构建，验证它没有依赖原 MOD 目录回退路径。预览版本在 GitHub Releases 标记为 Pre-release；程序 ZIP 与校验文件作为附件，官方资源包保持独立。

## 修改与兼容

版本变更修改 `app_metadata.py`，同步 README、更新记录与使用说明中的适用版本。服务、原生窗口、界面和打包版本均从该模块读取。

工程格式与游戏接入契约分别由 `studio_core.py` 和 `character_contract.py` 维护。保留旧工程兼容和原始字段，不把草稿标记成游戏已验收。`core/` 的适配需保留来源声明，并更新其变更说明；原项目的接口变化应分别验证 MOD 内入口和独立入口。

资源库生成依赖原项目中另行维护的只读官方基线和资源工具，不是构建本工具的前置条件。已有模板和定义目录按各自 schema、版本和哈希校验；更新工具不得重写用户的工程或资源库。
