/* Native card scene: 300 x 422, centered at (150, 211).
 * Texture layers and YIQ materials are baked by scripts/import_game_ui.py.
 * No painted CSS card frames or replacement icon shapes are used here.
 */
(() => {
  'use strict';
  const UI = 'assets/game-ui/';
  const types = {Attack:'攻击', Skill:'技能', Power:'能力', Curse:'诅咒', Status:'状态'};
  const keywords = {Exhaust:'消耗', Ethereal:'虚无', Retain:'保留', Innate:'固有', Unplayable:'不能被打出', Eternal:'永恒', Sly:'灵巧'};
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const asset = path => escape(window.WEB_ASSETS?.[path] || path);
  const canUpgrade = item => item.maxUpgradeLevel !== 0;
  function atLevel(item,level) {
    if (!item.upgradeGrowth || level <= 1) return item;
    const {base,first,step} = item.upgradeGrowth;
    const damage = base + first * level + step * level * (level - 1) / 2;
    return {...item,upgradedDescription:item.upgradedDescription.replace(String(base+first),String(damage))};
  }
  function rich(text,ui={}) {
    let html = escape(text);
    for (const color of ['gold','blue','red','green','purple']) html = html.replace(new RegExp(`\\[${color}\\]([\\s\\S]*?)\\[\\/${color}\\]`,'g'), `<span class="text-${color}">$1</span>`);
    return html
      .replace(/\[b\]([\s\S]*?)\[\/b\]/g, '<strong>$1</strong>')
      .replace(/\[i\]([\s\S]*?)\[\/i\]/g, '<em>$1</em>')
      .replace(/\[energy\]/g, `<img class="inline-energy" src="${asset(ui.inlineEnergy || UI+'energy-colorless.png')}" alt="能量">`)
      .replace(/\[\/?(?:sine|center)\]/g, '')
      .replace(/〔动态值〕/g, '<span class="runtime-value" aria-label="动态值">?</span>')
      .replace(/\n/g, '<br>');
  }
  function upgradeText(item) {
    const original = [...item.description.matchAll(/\d+(?:\.\d+)?|\[energy\]/g)].map(m=>m[0]);
    let index = 0;
    return item.upgradedDescription.replace(/\d+(?:\.\d+)?|\[energy\]/g, number => number === original[index++] ? number : `[green]${number}[/green]`);
  }
  function description(item, upgraded, ui) {
    const activeKeywords = (upgraded ? item.upgradedKeywords : item.keywords) || [];
    let text = upgraded ? upgradeText(item) : item.description;
    if (activeKeywords.length) text += (text ? '\n' : '') + `[gold]${activeKeywords.map(k=>keywords[k] || k).join('。')}。[/gold]`;
    if (item.shine) {
      const shine = (ui.shineLabel || '[gold]闪耀[/gold]') + (upgraded ? `[gold]${item.shine}[/gold]` : item.shine) + (ui.shineSuffix || '。');
      text += (text && !activeKeywords.includes('Exhaust') ? '\n' : '') + shine;
    }
    return rich(text,ui);
  }
  function html(item, upgraded=false, ui={}, level=1) {
    upgraded = upgraded && canUpgrade(item);
    const ancient = item.rarity === 'Ancient';
    const visualPool=item.visualPool||ui.id;
    const framePath=visualPool===ui.id ? ui.framePrefix : UI+'frame-'+visualPool+'-';
    const type = item.type === 'Attack' ? 'attack' : item.type === 'Power' ? 'power' : 'skill';
    let rarity = ['Uncommon','Rare','Curse','Status','Event','Ancient'].includes(item.rarity) ? item.rarity.toLowerCase() : 'common';
    if (item.bannerOverride) rarity = item.bannerOverride;
    const energy = upgraded && item.upgradedCost !== null ? item.upgradedCost : item.cost;
    const energyChanged = upgraded && energy !== item.cost;
    const layer = (name, file) => `<img class="native-layer ${name}" src="${asset(file.startsWith('assets/')?file:UI+file+'.png')}" alt="" draggable="false" decoding="async">`;
    let layers = '';
    if (ancient) {
      layers += `<img class="native-layer native-ancient-portrait" src="${asset(item.image)}" alt="" draggable="false" loading="lazy" decoding="async">`;
      layers += layer('native-ancient-border','ancient-card-border');
      layers += layer('native-ancient-text',`ancient-card-text-bg-${type}`);
      layers += layer('native-ancient-highlight','card-highlight-ancient');
      layers += layer('native-banner','ancient-banner');
      layers += '<div class="native-ancient-flame" aria-hidden="true"></div>';
    } else {
      layers += layer('native-shadow',`${framePath}${type}.png`);
      layers += `<img class="native-layer native-portrait" src="${asset(item.image)}" alt="" draggable="false" loading="lazy" decoding="async">`;
      layers += layer('native-frame',`${framePath}${type}.png`);
      layers += layer('native-portrait-border',`portrait-${type}-${rarity}`);
      layers += layer('native-banner',`banner-${rarity}`);
    }
    const costHTML = typeof energy === 'number' && energy < 0 ? '' : `<div class="native-energy ${energyChanged ? 'cost-upgraded' : ''}" aria-label="${escape(energy)} 费">${layer('native-energy-art',visualPool===ui.id?ui.energy:UI+'energy-colorless.png')}<span>${escape(energy)}</span></div>`;
    return `<div class="game-card ${ancient ? 'ancient-card' : ''} ${upgraded ? 'is-upgraded' : ''}" data-rarity="${rarity}" data-card-type="${type}" data-visual-pool="${escape(visualPool)}" data-card-id="${escape(item.id)}">${layers}<div class="native-title"><span>${escape(item.name)}${upgraded ? '+'+(level>1?level:'') : ''}</span></div><div class="native-type" style="--plaque:url('${asset(UI+'plaque-'+rarity+'.png')}')">${escape(types[item.type] || item.type)}</div><div class="native-description"><div>${description(item,upgraded,ui)}</div></div>${costHTML}</div>`;
  }
  const fitCache = new Map();
  function fit() {
    const entries = [...document.querySelectorAll('.game-card')].filter(card=>card.clientWidth>0).map(card=>{
      const title=card.querySelector('.native-title span'), content=card.querySelector('.native-description>div'), scale=card.clientWidth/300;
      const key=[card.clientWidth,title.textContent,content.textContent].join('|');
      const cached=fitCache.get(key);
      return {title,content,scale,key,titleSize:cached?.[0]||26,size:cached?.[1]||21,cached:Boolean(cached)};
    });
    const write=entry=>{entry.title.style.fontSize=entry.titleSize*entry.scale+'px';entry.content.style.fontSize=entry.size*entry.scale+'px';};
    entries.forEach(write);
    for(let pass=0;pass<15;pass++) {
      // Measure every card before changing any font size, then perform one write batch.
      const changes=entries.filter(entry=>!entry.cached).map(entry=>({entry,title:entry.titleSize>12&&(entry.title.scrollWidth>entry.title.parentElement.clientWidth+.5||entry.title.scrollHeight>entry.title.parentElement.clientHeight+.5),body:entry.size>12&&(entry.content.scrollHeight>entry.content.parentElement.clientHeight+.5||entry.content.scrollWidth>entry.content.parentElement.clientWidth+.5)})).filter(change=>change.title||change.body);
      if(!changes.length)break;
      changes.forEach(({entry,title,body})=>{if(title)entry.titleSize--;if(body)entry.size--;write(entry);});
    }
    entries.forEach(entry=>fitCache.set(entry.key,[entry.titleSize,entry.size]));
    if(fitCache.size>2000)fitCache.clear();
  }
  let scheduled = false;
  function scheduleFit() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(()=>{ scheduled = false; fit(); });
  }
  document.fonts.ready.then(()=>{fitCache.clear();scheduleFit();});
  window.addEventListener('resize',scheduleFit);
  window.NativeCards = {html, rich, fit:scheduleFit, escape, asset, canUpgrade, atLevel, keywordNames:keywords};
})();
