# 尖塔 Mod 图鉴

独立的《杀戮尖塔 2》Mod 信息展示网页。目前接入 [少女歌剧 · 爱城华恋](https://github.com/backinfile/STS2_ShoujoKagekiAijoKaren)，按 Mod 注册表组织角色、卡牌、遗物、药水与事件。

[在线图鉴](https://backinfile.github.io/STS2-MOD-INFO/) · [GitHub 仓库](https://github.com/backinfile/STS2-MOD-INFO)

## 本地运行与构建

直接用浏览器打开 `index.html` 即可；页面不使用 `fetch`，因此 `file://` 下也可浏览。

也可以在本目录运行：

```sh
npm run dev
```

打开终端输出的 `http://127.0.0.1:4173`。只读静态服务仅用于预览；网页没有业务后端，没有数据库，不读取游戏或其他本地项目。没有 Node 时直接打开 HTML 即可。

支持角色、卡牌、遗物、药水、事件和关键词独立页签。搜索、组合筛选、排序、升级和页码均写入链接，支持刷新和返回恢复。不可升级的卡牌保留基础版；“永无结束的命运舞台”可在详情调整升级次数。遗物与药水按游戏收藏界面分组展示，详情包含原始机制提示。按 `/` 聚焦搜索，按 `Esc` 关闭详情。窄屏使用可展开的筛选、单列卡面和可读的遗物正文。

执行 `npm run build` 生成 `dist/`，可交给任意静态托管服务。构建仅进行数据和资源完整性检查，不自动运行完整测试。

## 自动检测上游更新

项目附带 `.github/workflows/sync-mods.yml`：

1. 每 6 小时（UTC 的 00:17、06:17、12:17、18:17，北京时间 08:17、14:17、20:17、次日 02:17）检查注册的上游提交，也支持 Actions 页手动执行。GitHub 调度可能延迟。
2. 上游 SHA 与解析器代码哈希均未变时复用快照；任一变化都会重建，所有源文件锁定到同一提交。
3. 从中文本地化和 C# 模型中提取展示数据，下载图片，逐文件验证 Git blob SHA-1，并记录 SHA-256。
4. 在项目自己的暂存目录内完成数据、各 Mod 独立 UI、字体和无损 WebP，再校验哈希与提示引用；全部成功才替换快照。缺名称、缺素材、漏注册条目或 UI 构建失败都会保留之前的完整快照。
5. GitHub Pages 发布作业在同一次运行中发布快照，避免依赖机器人提交触发另一个工作流。推送到 `main` 时直接验证并部署仓库内的完整快照；定时或手动运行时先检测上游更新。

定时工作流位于仓库默认分支 `main`，使用仓库自身的 `GITHUB_TOKEN` 提交成功同步的快照；不需要个人访问令牌，也不需要业务服务器。

GitHub Pages 的发布来源设置为 GitHub Actions。工作流包含所需的仓库写入和 Pages 部署权限，无需额外设置仓库变量。若迁移到其他静态托管平台，可让它监听快照提交或接入对应的构建部署流程。

GitHub 的定时工作流受平台规则约束：公共仓库长时间无活动可能停用；受保护分支也可能拒绝机器人直接推送。可在 Actions 中检查具体失败原因并手动触发。参见 [GitHub 定时工作流规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) 和 [GITHUB_TOKEN 对后续工作流与 Pages 的影响](https://docs.github.com/en/actions/concepts/security/github_token)。

手动同步与验证（Python 3.10+；素材构建使用 Pillow 和 fontTools）：

```sh
python -m pip install -r scripts/requirements-ui.txt
python scripts/update_site.py
python scripts/validate_catalog.py
python -m unittest discover -s scripts -p "test_*.py"
```

可通过环境变量 `GITHUB_TOKEN` 提高 GitHub API 配额；凭据不写入文件。`python scripts/update_site.py --pinned --force` 在当前固定提交重建完整网站。底层 `sync_mods.py` 和 `import_game_ui.py` 用于开发单个构建阶段，正式更新统一使用完整入口。

## 数据结构

- `data/mods.json`：启用的 Mod、公开仓库、分支与适配器。
- `data/catalog.json`：机器可读的展示快照。
- `data/catalog.js`：与 JSON 相同的数据，供浏览器离线读取。
- `data/provenance.json`：原文件路径、Git blob 哈希、SHA-256 与字节数。
- `data/<mod-id>/source/`：此次解析使用的本地化和模型文本，仅用于溯源，不执行 C#。
- `assets/<mod-id>/`：此项目拥有的素材快照，无本地外部路径依赖。
- `assets/game-ui/`：原生 UI 图集裁片、材质输出与游戏中文字体子集。
- `assets/web/` 与 `data/web-assets.*`：逐像素校验的无损 WebP 与映射，不覆盖上游原始素材。
- `data/game-ui.json`：游戏及 Mod 的 UI 源文件、固定提交、字体变换与生成素材哈希；`game-ui.js` 提供离线本地化文本。

页面按 Mod ID 隔离条目和渲染素材，允许不同 Mod 使用相同内容 ID。新增 Mod 可实现源码适配器，也可使用 `snapshot` 适配器提供独立静态展示数据；格式见 [docs/mod-adapters.md](docs/mod-adapters.md)。

角色卡池来自 `KarenCardPool.GenerateAllCards`；共享卡池来自 `CardPoolPatches.cs` 的实际注入，忽略注释。当前有115个定义：86张角色卡、2张诅咒、25张衍生／选项牌，以及2张未注册牌；默认展示113张。筛选直接列出诅咒、状态和衍生牌，没有重复的“其他”。无色池与状态牌当前为零，显示数量并禁用。关键词页展示8个原始关键词。Karen 当前没有独立事件模型；新增事件会要求扩展源码适配器，通用 snapshot 适配器已支持原始事件图片、描述和选项。

## 与游戏 UI 的关系

研究来源和复现范围见 [docs/ui-research.md](docs/ui-research.md)。卡牌使用游戏原始图集裁片，按 `card.tscn` 的 300×422 坐标分层；材质按游戏 YIQ shader 与 Mod 参数离线生成。普通卡框、标题带、类型牌匾、九边形费用图标、远古卡框和提示框均使用对应资源。

简体中文按游戏的实际字体替换规则导入：普通标签和说明使用 Noto Sans Mono CJK SC，富文本粗体 / 斜体使用思源宋体 Bold / Medium。字体包含游戏的 0.95 字形变换与基线偏移；不使用浏览器伪粗体。字体子集随 Mod 文本自动重建，页面离线可用。

当前提取器处理图鉴状态的基础数值、升级增量、费用变化、条件文本与关键词。不执行游戏程序集；战斗中的临时状态、特殊着色动画与多次升级仍不等同于运行中的 Godot。新出现的不可求值表达式记录在数据与开发文档中，不在主界面添加说明长文。

原作及 Mod 图像、名称和文本的权利归各自作者所有。公开仓库可访问不等于获得任意再分发许可；正式公开发布前应确认素材授权。当前未复制原版游戏程序集或完整反编译项目。
