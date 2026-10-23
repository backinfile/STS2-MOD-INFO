(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const failure = () => { $('#load-error').hidden = false; };
  $('#load-retry').addEventListener('click', () => location.reload());
  const catalog = window.MOD_CATALOG, cards = window.NativeCards;
  if (!catalog?.mods?.length || !cards || !window.GAME_UI) { failure(); return; }
  const {escape, rich, asset} = cards;
  const library = window.GAME_UI.cardLibrary || {cardWidth:240,gap:40,hoverScale:1.25,designWidth:1920,designHeight:1080};
  const root = document.documentElement;
  root.style.setProperty('--library-card-width',`clamp(148px, min(${100*library.cardWidth/library.designWidth}vw, ${100*library.cardWidth/library.designHeight}dvh), ${library.cardWidth}px)`);
  root.style.setProperty('--library-card-gap-ratio',String(library.gap/library.cardWidth));
  root.style.setProperty('--library-hover-scale',String(library.hoverScale));
  const titles = {characters:'角色',cards:'卡牌图鉴',relics:'遗物图鉴',potions:'药水图鉴',events:'事件',keywords:'关键词'};
  const rarities = {None:'无',Basic:'基础',Common:'普通',Uncommon:'罕见',Rare:'稀有',Ancient:'先古',Event:'事件',Token:'衍生牌',Status:'状态',Curse:'诅咒',Quest:'任务',Starter:'初始',Shop:'商店',Unknown:'特殊'};
  const rarityOrder = Object.keys(rarities), typeNames = {Attack:'攻击',Skill:'技能',Power:'能力',Curse:'诅咒',Status:'状态',Quest:'任务'};
  const defaults = () => ({mod:catalog.mods[0].id,category:'cards',query:'',pool:[],type:[],rarity:'all',cost:[],extra:false,upgraded:false,sort:'default'});
  const views = new Map();
  const searchCache = new Map();
  let state = defaults(), displayedArtifacts = [], inspectedArtifact, inspectedCard, lastFocus;
  let hoverTimer, hideTimer, hoveredButton, renderFrame;
  const mod = () => catalog.mods.find(entry => entry.id === state.mod);
  const ui = () => window.GAME_UI.mods?.[state.mod] || {};
  const energy = item => state.upgraded && cards.canUpgrade(item) && item.upgradedCost != null ? item.upgradedCost : item.cost;
  const sourceUrl = path => `https://github.com/${mod().repository}/blob/${mod().commit}/${path.split('/').map(encodeURIComponent).join('/')}`;
  const date = value => new Intl.DateTimeFormat('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Shanghai',hour12:false}).format(new Date(value));
  const dictionaryTips = dictionary => Object.keys(dictionary || {}).filter(key => key.endsWith('.title')).map(key => ({name:dictionary[key],description:dictionary[key.slice(0,-6)+'.description']})).filter(tip => tip.description);
  const viewKey = entry => `${entry.mod}/${entry.category}`;

  function urlFor(entry) {
    const query = new URLSearchParams(); query.set('mod',entry.mod);
    for (const key of ['pool','type','cost']) if (entry[key].length) query.set(key,entry[key].join(','));
    for (const key of ['rarity','sort']) if (entry[key] !== 'all' && entry[key] !== 'default') query.set(key,entry[key]);
    if (entry.query) query.set('q',entry.query);
    if (entry.upgraded) query.set('upgrade','1');
    if (entry.extra) query.set('unregistered','1');
    return `#${entry.category}?${query}`;
  }
  function readLocation() {
    const [category,query = ''] = location.hash.slice(1).split('?'), params = new URLSearchParams(query), next = defaults();
    if (titles[category]) next.category = category;
    if (catalog.mods.some(entry => entry.id === params.get('mod'))) next.mod = params.get('mod');
    next.query = params.get('q') || '';
    for (const key of ['pool','type','cost']) next[key] = [...new Set((params.get(key) || '').split(',').filter(Boolean))];
    if (rarities[params.get('rarity')]) next.rarity = params.get('rarity');
    if (['cost','name','rarity'].includes(params.get('sort'))) next.sort = params.get('sort');
    next.upgraded = params.get('upgrade') === '1'; next.extra = params.get('unregistered') === '1';
    return next;
  }
  function remember() { views.set(viewKey(state),structuredClone(state)); }
  function writeLocation(replace = false) {
    remember(); const url = urlFor(state);
    if (location.hash !== url) history[replace ? 'replaceState' : 'pushState'](null,'',url);
    for (const link of $$('.category-nav [data-category]')) {
      const category = link.dataset.category;
      link.href = urlFor(views.get(`${state.mod}/${category}`) || {...defaults(),mod:state.mod,category});
    }
  }
  function update(changes,replace = false) { Object.assign(state,changes); render(); $('#collection').scrollTop=0; writeLocation(replace); }
  function lookup(dictionary,key) {
    const name = dictionary?.[key+'.title'], description = dictionary?.[key+'.description'];
    return name && description ? {name,description} : null;
  }
  function tipsFor(item,upgraded = state.upgraded) {
    upgraded = upgraded && cards.canUpgrade(item); const tips = [];
    for (const keyword of (upgraded ? item.upgradedKeywords : item.keywords) || []) {
      const tip = lookup(window.GAME_UI.localization.card_keywords,keyword.replace(/([a-z])([A-Z])/g,'$1_$2').toUpperCase()); if (tip) tips.push(tip);
    }
    for (const ref of item.tipRefs || []) {
      if(ref.ifKeyword&&!((upgraded?item.upgradedKeywords:item.keywords)||[]).includes(ref.ifKeyword))continue;
      let tip;
      if (ref.kind === 'mod') tip = lookup(mod().keywords,ref.key);
      if (ref.kind === 'static') tip = lookup(window.GAME_UI.localization.static_hover_tips,ref.key);
      if (ref.kind === 'power') tip = lookup(mod().powers,ref.key) || lookup(window.GAME_UI.localization.powers,ref.key);
      if (ref.kind === 'text') tip = ref;
      if (ref.kind === 'card') { const target = mod().cards.find(card => card.id === ref.id); if (target) tip = {name:target.name,card:target,upgraded:ref.upgraded === 'match' ? upgraded : ref.upgraded}; }
      if (ref.kind === 'potion') tip = mod().potions.find(potion => potion.id === ref.id) || lookup(window.GAME_UI.localization.potions,ref.id);
      if (tip) tips.push(tip);
    }
    return tips.filter((tip,index) => tips.findIndex(other => other.name === tip.name && Boolean(other.upgraded) === Boolean(tip.upgraded)) === index);
  }
  function tipHTML(tip) {
    if (tip.card) return `<section class="related-card">${cards.html(tip.card,tip.upgraded,ui())}</section>`;
    return `<section class="native-tip"><h3>${rich(tip.name,ui())}</h3><p>${rich(tip.description,ui())}</p></section>`;
  }
  function hideTips() { clearTimeout(hoverTimer); clearTimeout(hideTimer); hoveredButton?.removeAttribute('aria-describedby'); hoveredButton = null; $('#hover-tips').hidden = true; }
  function placeTips() {
    if (!hoveredButton?.isConnected || $('#hover-tips').hidden) return;
    const panel = $('#hover-tips'), rect = hoveredButton.getBoundingClientRect(), width = panel.offsetWidth, height = panel.offsetHeight;
    const viewport = $('#collection').getBoundingClientRect();
    if(rect.bottom<=viewport.top||rect.top>=viewport.bottom){hideTips();return;}
    let left = rect.right + 18;
    if (left + width > document.documentElement.clientWidth - 12) left = Math.max(10,rect.left-width-18);
    panel.style.left = left+'px'; panel.style.top = Math.max(12,Math.min(rect.top,innerHeight-height-12))+'px';
  }
  function showHover(button,keyboard = false) {
    if ((!keyboard && !matchMedia('(hover:hover)').matches) || $('#detail-dialog').open) return;
    const category = button.dataset.itemCategory || state.category, item = mod()[category]?.find(entry => entry.id === button.dataset.item);
    if (!item) return;
    hideTips();
    const tips = category === 'cards' ? tipsFor(item,state.category === 'characters' ? false : state.upgraded) : [{name:item.name,description:item.description},...tipsFor(item,false)];
    if (!tips.length) return;
    const display = () => { hoveredButton = button; const panel = $('#hover-tips'); panel.innerHTML = tips.map(tipHTML).join(''); panel.hidden = false; button.setAttribute('aria-describedby','hover-tips'); placeTips(); cards.fit(panel); };
    if (keyboard) hoverTimer=setTimeout(display,0); else hoverTimer = setTimeout(display,160);
  }
  function cardEntry(item) {
    const upgraded = state.upgraded && cards.canUpgrade(item);
    return `<article class="card-entry"><button class="card-button" data-item="${escape(item.id)}" aria-label="${escape(item.name)}${upgraded?'+':''}">${cards.html(item,upgraded,ui())}</button></article>`;
  }
  function artifactEntry(item) {
    const outline = ui().artifactUi?.[state.category]?.[item.id]?.outline;
    return `<button class="collection-item ${state.category==='relics'?'relic-item':'potion-item'}" data-item="${escape(item.id)}" data-item-category="${state.category}" aria-label="${escape(item.name)}"><span class="collection-icon">${outline?`<img class="collection-outline" src="${asset(outline)}" alt="" loading="lazy" decoding="async">`:''}<img src="${asset(item.icon||item.image)}" alt="" loading="lazy" decoding="async"></span></button>`;
  }
  function renderArtifacts(items) {
    const dictionary = window.GAME_UI.localization[state.category === 'relics' ? 'relic_collection' : 'potion_lab'] || {};
    const order = state.category === 'relics' ? ['Starter','Common','Uncommon','Rare','Shop','Ancient','Event','Unknown'] : ['Common','Uncommon','Rare','Event','Token','Unknown'];
    for (const item of items) if (!order.includes(item.rarity)) order.push(item.rarity);
    displayedArtifacts = order.flatMap(rarity => items.filter(item => item.rarity === rarity).sort((a,b) => rarity === 'Starter' ? Number(!mod().character.startingRelics.includes(a.className))-Number(!mod().character.startingRelics.includes(b.className)) : a.id.localeCompare(b.id)));
    return order.map(rarity => {
      const group = displayedArtifacts.filter(item => item.rarity === rarity); if (!group.length) return '';
      const heading = dictionary[rarity.toUpperCase()] || rarities[rarity] || rarity, label = heading.match(/\[gold\]([\s\S]*?)\[\/gold\]/)?.[0] || heading;
      return `<section class="collection-section"><h2>${rich(label.replace(/\[\/?font_size(?:=\d+)?\]/g,''),ui())}</h2><div class="collection-icons">${group.map(artifactEntry).join('')}</div></section>`;
    }).join('');
  }
  function searchText(item) {
    const upgraded = state.upgraded && cards.canUpgrade(item);
    const key=[state.mod,item.sourcePath,item.id,upgraded].join('/');
    if(!searchCache.has(key))searchCache.set(key,`${item.name} ${upgraded && item.upgradedDescription != null ? item.upgradedDescription : item.description} ${item.id} ${item.shine ? '闪耀' : ''} ${((upgraded ? item.upgradedKeywords : item.keywords) || []).map(key => cards.keywordNames[key] || key).join(' ')} ${tipsFor(item,upgraded).map(tip=>tip.name).join(' ')}`.replace(/\[[^\]]*\]/g,'').toLowerCase());
    return searchCache.get(key);
  }
  function poolMatches(item,key) { return key === 'ancient' ? item.rarity === 'Ancient' : item.cardPool === key; }
  function costMatches(item,key) { const value = energy(item); return key === '3+' ? typeof value === 'number' && value >= 3 : String(value) === key; }
  function matches(item,ignore) {
    return (state.extra || item.isRegistered !== false)
      && (ignore === 'pool' || !state.pool.length || state.pool.some(key => poolMatches(item,key)))
      && (ignore === 'type' || !state.type.length || state.type.includes(item.type))
      && (ignore === 'rarity' || state.rarity === 'all' || item.rarity === state.rarity)
      && (ignore === 'cost' || !state.cost.length || state.cost.some(key => costMatches(item,key)))
      && searchText(item).includes(state.query.trim().toLowerCase());
  }
  function facetButtons(attribute,options,test) {
    const available = mod().cards.filter(item => matches(item,attribute));
    return [{key:'all',name:'全部'},...options].map(option => {
      const count = option.key === 'all' ? available.length : available.filter(item => test(item,option.key)).length;
      const active = option.key === 'all' ? !state[attribute].length : state[attribute].includes(option.key);
      return `<button data-${attribute}="${escape(option.key)}" class="${active?'active':''}" aria-pressed="${active}" ${!count&&!active?'disabled':''} aria-label="${escape(option.name)}，${count}张"><span class="filter-label${attribute==='cost'&&option.key!=='all'?' cost-value':''}">${option.image?`<img src="${asset(option.image)}" alt="">`:''}${escape(option.name)}</span><small>${count}</small></button>`;
    }).join('');
  }
  function renderFilters() {
    const pools = [{key:state.mod,name:mod().character.name,image:mod().character.icon},{key:'colorless',name:'无色',image:'assets/game-ui/energy-colorless.png'},{key:'ancient',name:'先古',image:'assets/game-ui/pool-ancient.png'},{key:'curse',name:'诅咒'},{key:'status',name:'状态'},{key:'token',name:'衍生牌'}];
    const types = [...new Set([...Object.keys(typeNames),...mod().cards.map(item=>item.type)])].map(key => ({key,name:typeNames[key] || key,image:`assets/game-ui/type-sort-${{Attack:'attack',Skill:'skill',Power:'power'}[key] || 'other'}.png`}));
    $('.pool-filters').innerHTML = facetButtons('pool',pools,poolMatches);
    $('.type-filters').innerHTML = facetButtons('type',types.filter(entry=>entry.key!=='Quest'||mod().cards.some(item=>item.type==='Quest')),(item,key)=>item.type===key);
    $('.cost-filters').innerHTML = facetButtons('cost',['0','1','2','3+','X'].map(key=>({key,name:key})),costMatches);
    const available = mod().cards.filter(item=>matches(item,'rarity'));
    $('#rarity').innerHTML = [{key:'all',name:'全部'},...rarityOrder.filter(key=>!['Starter','Shop','Unknown','None'].includes(key)).map(key=>({key,name:rarities[key]}))].map(option=>{
      const count = option.key==='all'?available.length:available.filter(item=>item.rarity===option.key).length;
      return `<option value="${option.key}" ${state.rarity===option.key?'selected':''} ${!count&&state.rarity!==option.key?'disabled':''}>${option.name} (${count})</option>`;
    }).join('');
    $('#unregistered-count').textContent = mod().cards.filter(item=>item.isRegistered===false).length;
  }
  function renderCharacter() {
    const character = mod().character, deck = {};
    character.startingDeck.forEach(name => { const item=mod().cards.find(card=>card.className===name||card.id===name); if(item){deck[item.id]||={item,count:0};deck[item.id].count++;} });
    const relics = character.startingRelics.map(name=>mod().relics.find(item=>item.className===name||item.id===name)).filter(Boolean);
    return `<div class="character-view"><div class="character-art"><img src="${asset(character.image)}" alt="${escape(character.name)}" decoding="async"></div><div class="character-info"><h2>${escape(character.name)}</h2><p>${rich(character.description,ui())}</p><div class="character-stats"><span class="hp-value"><img src="${asset('assets/game-ui/health-icon.png')}" alt="生命">${character.hp} / ${character.hp}</span><span><img src="${asset('assets/game-ui/gold-icon.png')}" alt="金币">${character.gold}</span></div><h3>初始遗物</h3>${relics.map(relic=>`<button class="starting-relic" data-item="${escape(relic.id)}" data-item-category="relics"><img src="${asset(relic.image)}" alt="">${escape(relic.name)}</button>`).join('')}</div><div class="starting-deck"><h3>初始牌组</h3><div class="deck-grid">${Object.values(deck).map(({item,count})=>`<div><button class="card-button" data-item="${escape(item.id)}" data-item-category="cards" aria-label="${escape(item.name)}">${cards.html(item,false,ui())}</button><span class="deck-count">× ${count}</span></div>`).join('')}</div></div></div>`;
  }
  function render() {
    hideTips(); const category = state.category;
    $('#results').className = category==='cards'?'card-grid':category==='characters'?'character-grid':category==='keywords'?'keyword-grid':category==='events'?'event-grid':`native-collection ${category==='potions'?'potion-collection':'relic-collection'}`;
    if($('#search').value!==state.query)$('#search').value=state.query;
    $('#sort').value=state.sort; $('#include-extra').checked=state.extra; $('#upgrade-toggle').checked=state.upgraded;
    $('#reset-filters').hidden=!(state.query||state.pool.length||state.type.length||state.rarity!=='all'||state.cost.length||state.extra||state.sort!=='default');
    if(category==='characters') { $('#results').innerHTML=renderCharacter(); $('#result-count').textContent=''; $('#reset-filters').hidden=true; cards.fit(); return; }
    if(category==='keywords') {
      const tips=dictionaryTips(mod().keywords).filter(tip=>(tip.name+' '+tip.description).toLowerCase().includes(state.query.trim().toLowerCase()));
      $('#results').innerHTML=tips.length?tips.map(tipHTML).join(''):'<div class="empty-state">无匹配结果</div>'; $('#result-count').textContent=String(tips.length); return;
    }
    if(category==='events') {
      const items=mod().events;
      $('#results').innerHTML=items.length?items.map(item=>`<article class="native-event"><img src="${asset(item.image)}" alt="" loading="lazy"><h2>${escape(item.name)}</h2><p>${rich(item.description,ui())}</p>${(item.options||[]).map(option=>`<section class="native-tip"><h3>${rich(option.name||option.text,ui())}</h3>${option.description?`<p>${rich(option.description,ui())}</p>`:''}</section>`).join('')}</article>`).join(''):'<div class="empty-state">暂无事件</div>';
      $('#result-count').textContent=String(items.length); $('#reset-filters').hidden=true; return;
    }
    const isCards=category==='cards', items=mod()[category].filter(item=>isCards?matches(item):searchText(item).includes(state.query.trim().toLowerCase()));
    const poolOrder = [state.mod,'colorless','ancient','curse','status','token','unregistered'];
    const rank = item => rarityOrder.indexOf(item.rarity) < 0 ? 99 : rarityOrder.indexOf(item.rarity), compareId = (a,b) => a.id.localeCompare(b.id,'en');
    items.sort((a,b)=>{
      if(state.sort==='name') return a.name.localeCompare(b.name,'zh-CN')||compareId(a,b);
      if(state.sort==='cost') { const value=item=>energy(item)==='X'?100:Number(energy(item)); return value(a)-value(b)||compareId(a,b); }
      if(state.sort==='rarity') return rank(a)-rank(b)||compareId(a,b);
      return isCards?(poolOrder.indexOf(a.cardPool)-poolOrder.indexOf(b.cardPool)||rank(a)-rank(b)||compareId(a,b)):compareId(a,b);
    });
    $('#results').innerHTML=items.length?(isCards?items.map(cardEntry).join(''):renderArtifacts(items)):`<div class="empty-state">${escape(isCards?(window.GAME_UI.localization.card_library?.NO_RESULTS||'没有找到牌'):'无匹配结果')}</div>`;
    $('#result-count').textContent=isCards?(window.GAME_UI.localization.card_library?.CARD_COUNT||'{Amount}张牌').replace('{Amount}',items.length):String(items.length);
    if(isCards) renderFilters(); cards.fit();
  }
  function activate() {
    $('#mod-select').value=state.mod; $('#mod-icon').src=asset(mod().character.icon); $('#mod-icon').alt=mod().character.name;
    $('#top-source').href=`https://github.com/${mod().repository}`; $('#sidebar-commit').textContent=mod().commit.slice(0,7);
    $('#collection').dataset.category=state.category; document.title=`${titles[state.category]} · ${mod().character.name}`;
    for(const link of $$('.category-nav [data-category]')) { const active=link.dataset.category===state.category; link.classList.toggle('active',active); if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current'); }
    for(const category of ['cards','relics','potions','events','keywords']) $('#count-'+category).textContent=category==='cards'?mod().cards.filter(card=>card.isRegistered!==false).length:category==='keywords'?dictionaryTips(mod().keywords).length:mod()[category].length;
    $('#collection-title').textContent=titles[state.category]; $('#toolbar').hidden=['characters','events'].includes(state.category);
    $('#card-filters').hidden=state.category!=='cards'; $('#toggle-filters').hidden=state.category!=='cards'; $('#upgrade-control').hidden=state.category!=='cards'; $('.sort-control').hidden=state.category!=='cards';
    $('#search').placeholder=window.GAME_UI.localization.card_library?.SEARCH_PLACEHOLDER||'搜索'; $('#upgrade-control span').textContent=window.GAME_UI.localization.card_library?.VIEW_UPGRADES||'升级'; render(); $('#collection').scrollTop=0;
  }
  function restoreLocation() { remember(); state=readLocation(); activate(); writeLocation(true); }
  function focusCollection() { $('#collection').focus({preventScroll:true}); $('#collection').scrollTo({top:0,left:0,behavior:'instant'}); }
  function openDialog(content,kind='text') {
    hideTips(); const dialog=$('#detail-dialog'); if(!dialog.open)lastFocus=document.activeElement;
    dialog.dataset.kind=kind; $('#dialog-content').innerHTML=content;
    if(!dialog.open)dialog.showModal(); dialog.scrollTop=0; cards.fit(dialog);
  }
  function showItem(id,category=state.category) {
    const item=mod()[category]?.find(entry=>entry.id===id); if(!item)return;
    const source=`<a class="item-source" href="${sourceUrl(item.sourcePath)}" target="_blank" rel="noopener noreferrer">来源 ↗</a>`;
    if(category==='cards') {
      inspectedCard=item; const upgrade=cards.canUpgrade(item);
      const tips=[...tipsFor(item,false),...(upgrade?tipsFor(item,true):[])].filter((tip,index,all)=>all.findIndex(other=>other.name===tip.name&&Boolean(other.upgraded)===Boolean(tip.upgraded))===index);
      openDialog(`<h2 id="dialog-title" class="sr-only">${escape(item.name)}</h2><div class="card-comparison ${upgrade?'':'single-card'}"><div class="comparison-card"><span class="comparison-label">基础</span>${cards.html(item,false,ui())}</div>${upgrade?`<div class="comparison-card upgraded-comparison"><label class="comparison-label">升级${item.maxUpgradeLevel===null?` <input id="detail-upgrade-level" type="number" min="1" max="999" value="1" aria-label="升级次数">`:''}</label><div id="upgraded-card">${cards.html(item,true,ui())}</div></div>`:''}<div class="detail-tips">${tips.map(tipHTML).join('')}</div></div>${source}`,'cards');
    } else if(category==='relics') {
      inspectedArtifact=item.id; const items=displayedArtifacts.some(entry=>entry.id===id)?displayedArtifacts:mod().relics, index=items.findIndex(entry=>entry.id===id);
      const rarity=item.rarity.toLowerCase(), rarityLabel=window.GAME_UI.localization.gameplay_ui?.['RELIC_RARITY.'+item.rarity.toUpperCase()]||rarities[item.rarity];
      openDialog(`<div class="relic-detail-layout"><div class="relic-inspection" data-rarity="${rarity}" style="--inspect-panel:url('${asset('assets/game-ui/inspect-panel.png')}')"><img class="inspect-bg" src="${asset('assets/game-ui/inspect-panel.png')}" alt=""><h2 id="dialog-title">${escape(item.name)}</h2><p class="inspect-rarity">${escape(rarityLabel)}</p><div class="inspect-relic-frame"><img class="inspect-frame-bg" src="${asset('assets/game-ui/inspect-frame-bg.png')}" alt=""><img class="inspect-relic-image" src="${asset(item.image)}" alt=""><img class="inspect-frame" src="${asset('assets/game-ui/inspect-frame-'+rarity+'.png')}" alt=""></div><div class="inspect-copy"><p>${rich(item.description,ui())}</p>${item.flavor?`<hr><p class="inspect-flavor">${rich(item.flavor,ui())}</p>`:''}</div><button class="inspect-arrow inspect-previous" data-inspect-step="-1" aria-label="上一个遗物" ${index===0?'hidden':''}><img src="${asset('assets/game-ui/inspect-arrow-left.png')}" alt=""></button><button class="inspect-arrow inspect-next" data-inspect-step="1" aria-label="下一个遗物" ${index===items.length-1?'hidden':''}><img src="${asset('assets/game-ui/inspect-arrow-right.png')}" alt=""></button></div><div class="relic-related-tips">${tipsFor(item,false).map(tipHTML).join('')}</div></div>${source}`,'relic');
    } else if(category==='potions') openDialog(`<div class="potion-inspection"><img src="${asset(item.icon||item.image)}" alt=""><div class="native-tip"><h2 id="dialog-title">${escape(item.name)}</h2><p>${rich(item.description,ui())}</p></div>${tipsFor(item,false).map(tipHTML).join('')}</div>${source}`,'potion');
  }
  function stepRelic(step) { const items=displayedArtifacts.some(item=>item.id===inspectedArtifact)?displayedArtifacts:mod().relics; const index=items.findIndex(item=>item.id===inspectedArtifact)+step; if(items[index])showItem(items[index].id,'relics'); }
  $('#mod-select').innerHTML=catalog.mods.map(entry=>`<option value="${escape(entry.id)}" title="${escape(entry.name||entry.character.name)}">${escape(entry.character.name)}</option>`).join('');
  $('#mod-select').addEventListener('change',event=>{ remember(); state=structuredClone(views.get(`${event.target.value}/${state.category}`)||{...defaults(),mod:event.target.value,category:state.category}); activate(); writeLocation(); });
  $('.category-nav').addEventListener('click',event=>{const link=event.target.closest('a[data-category]');if(!link||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||event.button)return;event.preventDefault();remember();state=structuredClone(views.get(`${state.mod}/${link.dataset.category}`)||{...defaults(),mod:state.mod,category:link.dataset.category});activate();writeLocation();});
  $('.skip-link').addEventListener('click',event=>{event.preventDefault();focusCollection();});
  $('#search').addEventListener('input',event=>{state.query=event.target.value;cancelAnimationFrame(renderFrame);renderFrame=requestAnimationFrame(()=>{render();$('#collection').scrollTop=0;writeLocation(true);});});
  $('#upgrade-toggle').addEventListener('change',event=>update({upgraded:event.target.checked}));
  $('#toggle-filters').addEventListener('click',event=>{const open=event.currentTarget.getAttribute('aria-expanded')!=='true';event.currentTarget.setAttribute('aria-expanded',String(open));$('.sidebar').classList.toggle('filters-open',open);});
  $('#card-filters').addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button)return; const attribute=['pool','type','cost'].find(key=>key in button.dataset);if(!attribute)return;
    const key=button.dataset[attribute], selected=state[attribute]; update({[attribute]:key==='all'?[]:selected.includes(key)?selected.filter(value=>value!==key):[...selected,key]}); $(`[data-${attribute}="${key}"]`)?.focus({preventScroll:true});
  });
  for(const id of ['rarity','sort'])$('#'+id).addEventListener('change',event=>update({[id]:event.target.value}));
  $('#include-extra').addEventListener('change',event=>update({extra:event.target.checked}));
  $('#reset-filters').addEventListener('click',()=>{const {mod:modId,category,upgraded}=state;state={...defaults(),mod:modId,category,upgraded};render();$('#collection').scrollTop=0;writeLocation();$('#search').focus({preventScroll:true});});
  $('#results').addEventListener('click',event=>{const button=event.target.closest('[data-item]');if(button)showItem(button.dataset.item,button.dataset.itemCategory||state.category);});
  $('#results').addEventListener('pointerover',event=>{const button=event.target.closest('[data-item]');if(button&&!button.contains(event.relatedTarget))showHover(button);});
  $('#results').addEventListener('pointerout',event=>{const button=event.target.closest('[data-item]');if(button&&!button.contains(event.relatedTarget))hideTimer=setTimeout(hideTips,180);});
  $('#results').addEventListener('focusin',event=>{const button=event.target.closest('[data-item]');if(button)showHover(button,true);}); $('#results').addEventListener('focusout',hideTips);
  $('#hover-tips').addEventListener('pointerenter',()=>clearTimeout(hideTimer)); $('#hover-tips').addEventListener('pointerleave',hideTips);
  window.addEventListener('scroll',placeTips,true); window.addEventListener('resize',hideTips);
  $('#dialog-content').addEventListener('click',event=>{const button=event.target.closest('[data-inspect-step]');if(button)stepRelic(Number(button.dataset.inspectStep));});
  $('#dialog-content').addEventListener('input',event=>{if(event.target.id==='detail-upgrade-level'&&event.target.checkValidity()){const level=Number(event.target.value);$('#upgraded-card').innerHTML=cards.html(cards.atLevel(inspectedCard,level),true,ui(),level);cards.fit($('#upgraded-card'));}});
  $('#dialog-close').addEventListener('click',()=>$('#detail-dialog').close());
  $('#detail-dialog').addEventListener('click',event=>{if(event.target===$('#detail-dialog')){const rect=event.target.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)event.target.close();}});
  $('#detail-dialog').addEventListener('close',()=>lastFocus?.isConnected&&lastFocus.focus());
  $('#sync-button').addEventListener('click',()=>openDialog(`<div class="source-records"><h2 id="dialog-title">来源</h2><a href="https://github.com/${escape(mod().repository)}" target="_blank" rel="noopener noreferrer">${escape(mod().repository)} ↗</a><dl><dt>版本</dt><dd><a href="https://github.com/${escape(mod().repository)}/commit/${mod().commit}" target="_blank" rel="noopener noreferrer">${mod().commit.slice(0,12)}</a></dd><dt>同步时间</dt><dd>${date(mod().syncedAt)}</dd></dl></div>`));
  window.addEventListener('popstate',restoreLocation); window.addEventListener('hashchange',()=>{if(location.hash!==urlFor(state))restoreLocation();});
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape')hideTips();
    if(event.key==='/'&&!$('#detail-dialog').open&&!$('#toolbar').hidden&&!['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName)){event.preventDefault();$('#search').focus();}
    if($('#detail-dialog').open&&$('#detail-dialog').dataset.kind==='relic'&&['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();stepRelic(event.key==='ArrowLeft'?-1:1);}
  });
  window.addEventListener('error',event=>{if(event.error)failure();});
  state=readLocation(); activate(); writeLocation(true);
})();
