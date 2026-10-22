# Mod 适配器

每条注册记录使用独立 `id`。卡牌 ID 仅在所属 Mod 内解析；资源保存到 `assets/<id>/`，卡框、能量与收藏轮廓由 `GAME_UI.mods[id]` 提供。浏览器不访问 GitHub。

## 源码适配器

`sync_mods.py` 的 `ADAPTERS` 注册“选择源文件”和“生成展示快照”两个函数。Karen 的源码目录、类名兼容和机制关联集中在其适配器，通用渲染器不依赖其他本地项目。

新适配器需要导出 `character`、`cards`、`relics`、`potions`、`events`、`keywords`，并验证具体模型和各注册池完整性。模型无法解析时必须失败，不能凭描述猜测数值或丢弃条目。修改适配器代码自动使缓存失效。

## snapshot 格式

如果 Mod 仓库可提供静态展示数据，注册表可使用：

```json
{
  "id": "another-mod",
  "name": "原始 Mod 名称",
  "repository": "owner/repository",
  "ref": "main",
  "adapter": "snapshot",
  "contentRoot": "mod-info/",
  "enabled": true
}
```

上游 `mod-info/catalog.json` 示例（图片也放在同一内容目录）：

```json
{
  "character": {
    "name": "原始角色名",
    "description": "原始介绍",
    "image": "mod-info/character.png",
    "icon": "mod-info/icon.png",
    "hp": 70,
    "gold": 99,
    "startingDeck": ["CARD_ID"],
    "startingRelics": []
  },
  "cards": [{
    "id": "CARD_ID",
    "name": "原始卡名",
    "description": "原始基础描述",
    "upgradedDescription": "原始升级描述",
    "image": "mod-info/card.png",
    "cost": 1,
    "upgradedCost": null,
    "type": "Skill",
    "rarity": "Common",
    "maxUpgradeLevel": 1,
    "keywords": [],
    "upgradedKeywords": ["Innate"],
    "tipRefs": [{"kind":"mod","key":"MECHANIC"}]
  }],
  "relics": [],
  "potions": [],
  "events": [],
  "keywords": {
    "MECHANIC.title": "原始机制名",
    "MECHANIC.description": "原始机制描述"
  }
}
```

示例数值仅说明数据格式，不会作为展示内容接入网站。`cardPool`、`visualPool` 默认使用注册的 Mod ID；共享池可用 `colorless`、`curse`、`status`、`token`。未注册卡标记 `isRegistered:false`。不可升级卡必须设 `maxUpgradeLevel:0`。

提示引用支持 `mod`（原始机制字典）、`power`（原始能力 ID）、`static`（本体提示）、`card`（同 Mod 卡牌及 `upgraded:true/false/"match"`）、`potion` 和 `text`（原始名称与描述）。`ifKeyword` 可限制提示只在当前版本包含指定关键词时出现。不能通过中文字面匹配生成关系。

`rendering` 可指定上游 `frameMaterialSource`、`energySource`、`inlineEnergySource`、`gameplayPath` 与 `outlineColors`。纹理支持 PNG 和 Godot AtlasTexture；没有专属卡框与能量时使用本体无色资源。每个上游源文件和派生输出均记录哈希。

事件记录使用 `id/name/image/description/options`；选项展示原始 `name` 或 `text` 及 `description`，不模拟战斗或编造结果。当前 Karen 没有事件，源码新增事件时仍会使适配器明确失败，避免发布缺失内容。

完整同步入口是 `python scripts/update_site.py`；`--pinned --force` 可重放当前固定提交。所有构建与校验在项目内暂存目录完成，失败不替换当前数据、字体或图片。
