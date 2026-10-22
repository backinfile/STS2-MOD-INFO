# 游戏界面与字体复现记录

核对日期：2026-10-22。游戏参考是公开的第三方反编译仓库，不是 Mega Crit 官方源码。本项目仅导入静态展示所需资源，不运行游戏、不引用本地游戏安装或其他项目。

## 固定来源

- 游戏：[Hexpion/Slay-the-spire-2 @ 64ed626](https://github.com/Hexpion/Slay-the-spire-2/tree/64ed626b7ec9692bc54536b0123fc3cb580c28da/Slay%20the%20Spire%202)。
- Mod：[backinfile/STS2_ShoujoKagekiAijoKaren](https://github.com/backinfile/STS2_ShoujoKagekiAijoKaren)。当前提交以 `data/catalog.json` 为准。
- 游戏内截图：[Mod 仓库中的实际战斗截图](https://github.com/backinfile/STS2_ShoujoKagekiAijoKaren/blob/dc919b95c4ae7fe7a83a8ca02c44820437d88454/docs/worktree-tasks/karen-energy-concepts/nonagon-live-stable/p9-card.png)，本地对照在 `screenshots/game-reference.png`。
- 每个下载文件的路径、Git blob SHA-1 和 SHA-256 在 `data/provenance.json` 或 `data/game-ui.json`。构建时逐文件验证，不下载或执行程序集。

## 字体：必须检查语言替换后的结果

仅查看场景里的 Kreon 会得出错误结论。简体中文通过 [ZhsFontPathSet.cs](https://github.com/Hexpion/Slay-the-spire-2/blob/64ed626b7ec9692bc54536b0123fc3cb580c28da/Slay%20the%20Spire%202/src/Core/Localization/Fonts/FontPathSets/ZhsFontPathSet.cs) 选择字体；[MegaLabel.cs](https://github.com/Hexpion/Slay-the-spire-2/blob/64ed626b7ec9692bc54536b0123fc3cb580c28da/Slay%20the%20Spire%202/addons/mega_text/MegaLabel.cs) 对整个普通标签应用 Regular 替换，包括卡名、类型和费用。

| 用途 | 简体中文实际字体 |
| --- | --- |
| 普通标签、说明、其中的数字和拉丁字母 | Noto Sans Mono CJK SC Regular |
| 富文本 `[b]` | Source Han Serif SC Bold |
| 富文本 `[i]` | Source Han Serif SC Medium；不额外合成倾斜 |

三个 `themes/fonts/zhs/*_shared.tres` 还指定 `variation_transform=0.95` 与 `baseline_offset=-0.05`。导入脚本将字形缩放与基线平移烘焙进 WOFF2，保留原字距，不仅替换 CSS 字体名称。Godot 的 transform 用于字形轮廓，baseline_offset 按字体高度计算；参见 [FontVariation 文档](https://docs.godotengine.org/en/4.5/classes/class_fontvariation.html) 与 [TextServer 实现](https://github.com/godotengine/godot/blob/4.5.1-stable/modules/text_server_adv/text_server_adv.cpp)。

卡牌的 26 / 21 / 16 / 32 基础字号、描述区 `line_separation=-3`、自动缩字与阴影来自游戏场景。禁用浏览器合成粗体和斜体。字体只保留本项目展示所需字符；自动同步 Mod 后重新构建子集，防止新增文字缺字。浏览器字体请求使用本站文件，不依赖系统安装字体或远程字体 CDN。

## 卡牌渲染

按 [card.tscn](https://github.com/Hexpion/Slay-the-spire-2/blob/64ed626b7ec9692bc54536b0123fc3cb580c28da/Slay%20the%20Spire%202/scenes/cards/card.tscn) 分层，卡牌坐标系为 300×422：

| 图层 | 左 / 上 / 宽 / 高 |
| --- | --- |
| 插画 | 25 / 43 / 250 / 190 |
| 卡框 | 0 / 0 / 300 / 422 |
| 插画边框 | 12.5 / 47 / 275 / 210 |
| 标题带 | -13 / 4 / 327 / 83 |
| 标题 | 45 / 7 / 210 / 54 |
| 描述 | 28 / 248 / 243 / 136 |
| 类型牌匾 | 119.5 / 212 / 61 / 37 |
| 费用图标 | -16 / -16 / 64 / 64 |

`scripts/import_game_ui.py` 按 AtlasTexture 的 region 和 margin 提取原始图集，生成攻击 / 技能 / 能力的卡框与稀有度边框。材质虽然叫 `card_frame_purple_mat.tres`，当前 Mod 的实际参数是 `h=.99,s=.67,v=.98`，输出是偏红的卡框；不能根据文件名自行涂紫色。

`hsv.gdshader` 实际使用 RGB↔YIQ 矩阵和色相旋转。脚本按其矩阵及 GLSL 行向量方向生成静态 PNG，保留原始 alpha。标题带、插画边框与牌匾分别使用稀有度材质。费用使用 Mod 当前九边形图标及其原始区域、留白；描述内使用 Mod 能量图标。升级标题、变化费用和数值使用游戏绿色。

`ShineViewPatch.cs` 将闪耀文字放进说明区，沿用 Mod 文本和换行规则；不另加星形角标。`RareTokenCardVisualPatch.cs` 的两张特殊衍生牌使用稀有标题带。远古卡单独使用原图、遮罩、边框、文字底图、叠加高光与 10 帧火焰。

图鉴尺寸来自 `NCard.defaultSize=(300,422)`、`NCardHolder.smallScale=.8` 和 `NCardGrid.CardPadding=40`。游戏设计视口为1920×1080，因此1080p的小卡为240×337.6，720p约160×225.1；聚焦时从0.8缩放至1，即列表大小的1.25倍。导入器将这些参数和源文件哈希写入 `cardLibrary`。网页按视口比例确定卡宽，再自动换列，避免随等分列拉伸；为小窗口保留148px下限，触屏列表使用160px，详情最大300px。

## 其他界面

导航和筛选使用游戏原始图标。遗物、药水、卡牌关键词使用 `hover_tip.tscn` 对应的九宫格纹理；描述、风味文本与专属关键词直接使用 Mod 本地化，通用格挡、力量、虚弱等提示来自游戏本地化。搜索、升级开关、卡牌数量和空结果文字也优先使用游戏文本。

遗物和药水列表按 `relic_collection_category.tscn` / `potion_category.tscn` 的稀有度分组，图标尺寸分别为 68 / 60，网格间距为 32，组内左边距为 48。遗物 holder 的 1.25 基础缩放、聚焦时 1.25 缩放与药水聚焦 1.2 缩放均沿用源代码。使用 Mod 原始小图及 outline；按池定义分别调制紫色 / 红色，透明度 0.66。说明在悬停或键盘聚焦时出现。分组标题保留游戏原有名称，按产品约束去掉附带的解释句。

遗物详情按 `inspect_relic_screen.tscn` 的 864×864 坐标布置，使用原始 reward panel、检查边框、左右箭头及原始大图。背景原图为 1128×1436，`Popup/Bg.stretch_mode = 5`（KEEP_ASPECT_CENTERED），在方形坐标容器中保持比例居中显示，不拉伸成正方形；遮罩沿用 `NInspectRelicScreen.Open` 的 0.9 黑色透明度。稀有度边框按 `NInspectRelicScreen.SetRarityVisuals` 的 YIQ 参数生成。可通过按钮或方向键切换。药水沿用原生 hover tip，点击后固定显示，适配触屏。关键词页独立展示 Mod `card_keywords.json` 的 8 组名称和描述。

窄屏遗物面板为可读正文保留流式高度：背景使用原图的 192px 九宫格切片，边角按原图宽度同比缩放，只延展中间纹理。这属于网页窄屏适配；游戏原场景的方形坐标与背景等比居中规则用于桌面布局。

遗物底座是另一层 `Popup/RelicFrame/FrameBg`：原场景未指定 `stretch_mode`，使用默认 STRETCH_SCALE，将调色后的 reward panel 填充到居中的 300×300 区域；装饰框为 304×304，四边相差 2px。不能给整个遗物容器内的图片统一设置 `object-fit:contain`，否则竖版底座会缩窄，无法衬满装饰框。只有 `RelicImage` 按原场景的 KEEP_ASPECT_CENTERED 等比显示。

卡牌注册不仅来自角色池，还解析 Mod 的 `CardPoolPatches.cs`。当前 115 张定义中，角色池 86、CurseCardPool 2、TokenCardPool 25，另有 2 张暂未注册。Token 的默认外观来自原生无色池；3 张牌按 Mod 的 VisualCardPool 覆盖保留角色外观。不能把源码的 neutral 目录误判为 ColorlessCardPool。按原生图鉴分类，诅咒和衍生属于“其他”，独立 ColorlessCardPool 与状态牌目前为空。

角色展示 Mod 的插画、原始说明、72 初始生命、99 金币、初始遗物与牌组。当前上游没有独立事件模型，保留简短空状态，不编造事件内容。

## 已知差异与验证范围

- 当前是可搜索、筛选和对照升级的静态 HTML 图鉴；没有战斗状态、动态立绘或 Godot 运行时。
- 纹理与字体已使用实际资源和参数；浏览器的字体栅格化、换行边界和描边与 Godot 仍可能存在像素差异，不能据此宣称像素级一致。
- 悬停的缩放、高光与远古叠加采用浏览器实现；没有完整移植游戏 SDF 波纹、动态着色器和粒子。
- 升级由 MaxUpgradeLevel 决定；两张不可升级诅咒不生成升级版。“永无结束的命运舞台”按原始 +4、+5…成长计算多次升级。战斗临时状态不在静态图鉴中模拟。
- UI 与游戏内截图对照；桌面、窄屏、基础 / 升级详情另存预览截图。验证包含解析回归、材质 alpha、字体轮廓变换与字距、中文字符覆盖、资源哈希和静态打包。

## 自动更新

每 6 小时检查 `data/mods.json` 的 GitHub 上游提交；变更后锁定同一提交，更新数据、素材和字体子集，完整验证成功才提交。浏览器读取本地静态快照。失败不发布部分结果；GitHub Actions 启用与可选 Pages 配置见 README。
