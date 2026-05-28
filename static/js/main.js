// ═══════════════════════════════════════════════════════════════
//  PokéVault — main.js
//  • Enter/button-only search (no auto-fire on keystroke)
//  • Multi-select cart with variant tracking
//  • Infinite scroll (intersection observer)
//  • Import/export
//  • PWA service worker registration
// ═══════════════════════════════════════════════════════════════

// ── Toast ──────────────────────────────────────────────────────
const toastEl = document.getElementById('toast');
function showToast(msg, type = 'success') {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.className = `toast ${type} show`;
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(() => toastEl.classList.remove('show'), 2800);
}

// ── Modal helpers ──────────────────────────────────────────────
function openModal(id)  { document.getElementById(id)?.classList.add('open');    document.body.style.overflow = 'hidden'; }
function closeModal(id) { document.getElementById(id)?.classList.remove('open'); document.body.style.overflow = ''; }

document.querySelectorAll('.modal-close, [data-close]').forEach(btn => {
    btn.addEventListener('click', () => {
        const id = btn.dataset.close || btn.closest('.modal-overlay')?.id;
        if (id) closeModal(id);
    });
});
document.querySelectorAll('.modal-overlay').forEach(o =>
    o.addEventListener('click', e => { if (e.target === o) closeModal(o.id); }));
document.addEventListener('keydown', e => {
    if (e.key === 'Escape')
        document.querySelectorAll('.modal-overlay.open').forEach(m => closeModal(m.id));
});

// ── Avatar dropdown ────────────────────────────────────────────
const avatarBtn = document.getElementById('avatar-btn');
const userDrop  = document.getElementById('user-dropdown');
avatarBtn?.addEventListener('click', e => { e.stopPropagation(); userDrop?.classList.toggle('open'); });
document.addEventListener('click', () => userDrop?.classList.remove('open'));

// Open modals
document.getElementById('open-search-modal') ?.addEventListener('click', () => { openModal('search-modal'); document.getElementById('api-search-input')?.focus(); });
document.getElementById('open-search-empty') ?.addEventListener('click', () => { openModal('search-modal'); document.getElementById('api-search-input')?.focus(); });
document.getElementById('open-stats-modal')  ?.addEventListener('click', () => { userDrop?.classList.remove('open'); openModal('stats-modal'); });
document.getElementById('open-alerts-modal') ?.addEventListener('click', () => { userDrop?.classList.remove('open'); openModal('alerts-modal'); loadAlerts(); });
document.getElementById('open-import-modal') ?.addEventListener('click', () => { userDrop?.classList.remove('open'); openModal('import-modal'); });

// ═══════════════════════════════════════════════════════════════
//  SEARCH — fires only on Enter or Search button
// ═══════════════════════════════════════════════════════════════

const apiInput  = document.getElementById('api-search-input');
const numInput  = document.getElementById('api-number-input');
const resultsEl = document.getElementById('api-results');
const spinner   = document.getElementById('search-spinner');
const selPanel  = document.getElementById('selected-panel');
const cartBanner= document.getElementById('cart-banner');
const cartInfo  = document.getElementById('cart-info');
const hintText  = document.getElementById('search-hint-text');

let selectedCards = new Map();   // tcg_id → {card, qty}
let focusedCard   = null;
let selQty        = 1;

// Fire search on Enter in either field
[apiInput, numInput].forEach(el => {
    el?.addEventListener('keydown', e => { if (e.key === 'Enter') triggerSearch(); });
});
document.getElementById('btn-search-go')?.addEventListener('click', triggerSearch);

// Clear results when search modal opens fresh
document.getElementById('open-search-modal')?.addEventListener('click', () => {
    if (!resultsEl.querySelector('.result-thumb')) resetResults();
});

function triggerSearch() {
    const q = apiInput?.value.trim() || '';
    const n = numInput?.value.trim()  || '';
    if (!q && !n) {
        if (hintText) hintText.textContent = '⚠ Enter a Pokémon name or card number.';
        return;
    }
    if (q && q.length < 2) {
        if (hintText) hintText.textContent = '⚠ Type at least 2 characters for the name.';
        return;
    }
    doSearch(q, n);
}

async function doSearch(q, n) {
    spinner.style.display = 'block';
    if (hintText) hintText.style.display = 'none';
    resultsEl.innerHTML = '';
    try {
        const params = new URLSearchParams({ q });
        if (n) params.set('number', n);
        const res  = await fetch(`/api/search?${params}`);
        const data = await res.json();
        spinner.style.display = 'none';
        if (data.hint) { showHint(data.hint); return; }
        if (data.error) { showHint('⚠ ' + data.error); return; }
        renderResults(data.data || []);
    } catch(e) {
        spinner.style.display = 'none';
        showHint('⚠ Search failed — check your connection.');
    }
}

function showHint(msg) {
    resultsEl.innerHTML = `<div class="results-hint"><span>💡</span><p>${msg}</p></div>`;
    selPanel.style.display = 'none';
}

function renderResults(cards) {
    if (!cards.length) { resultsEl.innerHTML = '<div class="results-empty">No cards found. Try a different spelling or shorter name.</div>'; return; }
    resultsEl.innerHTML = '';
    cards.forEach(card => {
        const thumb = document.createElement('div');
        thumb.className = 'result-thumb';
        thumb.dataset.id = card.id;

        const check = document.createElement('div');
        check.className = 'check-overlay'; check.textContent = '✓';
        thumb.appendChild(check);

        if (card.images?.small) {
            const img = document.createElement('img');
            img.src = card.images.small; img.alt = card.name; img.loading = 'lazy';
            thumb.appendChild(img);
        } else {
            const ph = document.createElement('span');
            ph.className = 'result-thumb-placeholder'; ph.textContent = card.name[0];
            thumb.appendChild(ph);
        }

        // Number label
        if (card.number) {
            const nl = document.createElement('div');
            nl.className = 'thumb-number'; nl.textContent = '#' + card.number;
            thumb.appendChild(nl);
        }

        if (selectedCards.has(card.id)) thumb.classList.add('selected');

        thumb.addEventListener('click', e => handleThumbClick(e, card, thumb));
        resultsEl.appendChild(thumb);
    });
}

function handleThumbClick(e, card, thumb) {
    if (e.shiftKey || e.ctrlKey || e.metaKey) {
        toggleCart(card, thumb);
    } else {
        focusedCard = card; selQty = selectedCards.get(card.id)?.qty || 1;
        showDetail(card);
        document.querySelectorAll('.result-thumb.focused').forEach(t => t.classList.remove('focused'));
        thumb.classList.add('focused');
        if (!selectedCards.has(card.id)) toggleCart(card, thumb);
    }
}

function toggleCart(card, thumb) {
    if (selectedCards.has(card.id)) {
        selectedCards.delete(card.id);
        thumb.classList.remove('selected');
    } else {
        selectedCards.set(card.id, { card, qty: 1, variant: 'Normal' });
        thumb.classList.add('selected');
    }
    updateCartUI();
}

function updateCartUI() {
    const n = selectedCards.size;
    cartBanner.style.display = n ? 'flex' : 'none';
    if (cartInfo) cartInfo.textContent = `${n} card${n !== 1 ? 's' : ''} selected`;
    const addAllBtn = document.getElementById('btn-add-all');
    if (addAllBtn) addAllBtn.textContent = `Add All (${n})`;
    const sc = document.getElementById('selection-count');
    if (sc) { sc.style.display = n ? 'inline' : 'none'; sc.textContent = `${n} selected`; }
    if (!n) { selPanel.style.display = 'none'; focusedCard = null; }
}

function showDetail(card) {
    document.getElementById('sel-img').src  = card.images?.large || card.images?.small || '';
    document.getElementById('sel-name').textContent = card.name;
    document.getElementById('sel-set').textContent  = `${card.set?.name||'—'} · ${card.set?.series||''} · #${card.number||'?'}`;
    document.getElementById('sel-details').textContent =
        [card.supertypes?.[0], card.subtypes?.join(', '), card.hp ? `${card.hp} HP` : ''].filter(Boolean).join(' · ');

    // Price — show all variants
    const mkt = card.tcgplayer?.prices;
    let priceStr = 'Price unavailable';
    let variantChips = '';
    if (mkt) {
        const lines = [];
        const labels = {normal:'Normal',holofoil:'Holofoil',reverseHolofoil:'Reverse Holo',
                        '1stEditionHolofoil':'1st Ed Holo','1stEditionNormal':'1st Ed'};
        for (const [key, label] of Object.entries(labels)) {
            if (mkt[key]?.market) {
                lines.push(`${label}: $${mkt[key].market.toFixed(2)}`);
                variantChips += `<span class="variant-chip">${label} $${mkt[key].market.toFixed(2)}</span>`;
            }
        }
        if (lines.length) priceStr = lines[0];
    }
    document.getElementById('sel-price').textContent = priceStr;
    document.getElementById('sel-variants').innerHTML = variantChips;
    document.getElementById('sel-qty-val').textContent = selQty;
    selPanel.style.display = 'block';
    selPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Qty in panel
document.getElementById('sel-qty-plus') ?.addEventListener('click', () => {
    selQty = Math.min(999, selQty + 1);
    document.getElementById('sel-qty-val').textContent = selQty;
    if (focusedCard && selectedCards.has(focusedCard.id))
        selectedCards.get(focusedCard.id).qty = selQty;
});
document.getElementById('sel-qty-minus')?.addEventListener('click', () => {
    selQty = Math.max(1, selQty - 1);
    document.getElementById('sel-qty-val').textContent = selQty;
    if (focusedCard && selectedCards.has(focusedCard.id))
        selectedCards.get(focusedCard.id).qty = selQty;
});

// Single add
document.getElementById('btn-add-to-vault')?.addEventListener('click', async () => {
    if (!focusedCard) return;
    await submitCards([buildPayload(focusedCard,
        document.getElementById('sel-condition').value,
        selQty,
        document.getElementById('sel-variant').value)]);
});

// Bulk add all
document.getElementById('btn-add-all')?.addEventListener('click', async () => {
    if (!selectedCards.size) return;
    const cond    = document.getElementById('bulk-condition').value;
    const variant = document.getElementById('bulk-variant').value;
    await submitCards([...selectedCards.values()].map(({card,qty}) => buildPayload(card,cond,qty,variant)));
});

document.getElementById('btn-clear-cart')?.addEventListener('click', () => {
    selectedCards.clear();
    document.querySelectorAll('.result-thumb').forEach(t => t.classList.remove('selected','focused'));
    updateCartUI();
});

// Wishlist / Trade
document.getElementById('btn-add-to-wishlist')?.addEventListener('click', async () => {
    if (!focusedCard) return;
    await fetch(WISHLIST_URL, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(buildPayload(focusedCard,'Near Mint',1,'Normal'))});
    showToast(`${focusedCard.name} → Wishlist ⭐`, 'info');
});
document.getElementById('btn-add-to-tradelist')?.addEventListener('click', async () => {
    if (!focusedCard) return;
    await fetch(TRADELIST_URL, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(buildPayload(focusedCard,'Near Mint',1,'Normal'))});
    showToast(`${focusedCard.name} → Trade List ⇄`, 'info');
});

function buildPayload(card, condition, qty, variant='Normal') {
    const mkt = card.tcgplayer?.prices;
    let price = 0, foilPrice = 0;
    if (mkt) {
        const nm = mkt.normal      || {}; price     = nm.market || nm.mid || 0;
        const hf = mkt.holofoil   || {}; foilPrice = hf.market || hf.mid || 0;
        if (!price) price = foilPrice || (mkt[Object.keys(mkt)[0]]?.market || 0);
    }
    return {
        tcg_id: card.id, name: card.name,
        pokemon_type: card.types?.[0] || card.subtypes?.[0] || 'Colorless',
        rarity: card.rarity || '', set_name: card.set?.name || '',
        set_id: card.set?.id || '', set_series: card.set?.series || '',
        card_number: card.number || '', hp: card.hp || '',
        subtypes: (card.subtypes||[]).join(', '),
        variant, condition, quantity: qty,
        market_price: price, foil_price: foilPrice,
        image_small: card.images?.small||'', image_large: card.images?.large||'', notes:''
    };
}

async function submitCards(payload) {
    try {
        const res  = await fetch('/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        const data = await res.json();
        if (data.success) {
            const added = data.results.filter(r=>r==='added').length;
            const incr  = data.results.filter(r=>r==='incremented').length;
            showToast((added?`${added} added`:'') + (incr?` · ${incr} updated`:'') || 'Done!');
            closeModal('search-modal');
            resetResults();
            reloadFiltered();
        }
    } catch(e) { showToast('Failed to add cards','error'); }
}

function resetResults() {
    if (resultsEl) resultsEl.innerHTML = '<div class="results-hint"><span>🔍</span><p>Enter a name and press Enter or click Search</p></div>';
    if (selPanel) selPanel.style.display = 'none';
    if (cartBanner) cartBanner.style.display = 'none';
    if (hintText) { hintText.style.display = ''; hintText.textContent = 'Enter a Pokémon name and press Enter or click Search'; }
    selectedCards.clear();
    focusedCard = null;
    if (spinner) spinner.style.display = 'none';
    document.querySelectorAll('.result-thumb').forEach(t => t.classList.remove('selected','focused'));
}

// ═══════════════════════════════════════════════════════════════
//  INFINITE SCROLL  (Intersection Observer)
// ═══════════════════════════════════════════════════════════════

let infinitePage    = 2;   // page 1 is server-rendered
let infiniteLoading = false;
let infiniteExhausted = false;

const sentinel    = document.getElementById('scroll-sentinel');
const loadingMore = document.getElementById('loading-more');
const grid        = document.getElementById('cards-grid');

function buildCardHTML(card) {
    const img = card.image_large || card.image_small
        ? `<div class="card-portrait img-portrait"><img src="${card.image_large||card.image_small}" alt="${card.name}" loading="lazy"></div>`
        : `<div class="card-portrait text-portrait"><div class="portrait-bg type-bg-${(card.pokemon_type||'normal').toLowerCase().replace(' ','_')}"><span class="portrait-initial">${card.name[0].toUpperCase()}</span></div></div>`;
    const priceBadge = card.market_price > 0 ? `<div class="card-price">$${parseFloat(card.market_price).toFixed(2)}</div>` : '';
    const varBadge   = (card.variant && card.variant !== 'Normal') ? `<span class="badge variant-badge">${card.variant}</span>` : '';
    return `<div class="card-item"
        data-id="${card.id}" data-name="${(card.name||'').toLowerCase()}"
        data-type="${(card.pokemon_type||'').toLowerCase()}" data-rarity="${card.rarity||''}"
        data-condition="${card.condition||''}" data-value="${card.market_price||0}"
        data-qty="${card.quantity}" data-fav="${card.is_favorite}" data-ts="${card.created_at}">
      <div class="card-inner">
        <div class="card-shine"></div><div class="card-holographic"></div>
        ${img}
        <div class="card-meta">
          <h3 class="card-name">${card.name}</h3>
          <p class="card-set-line">${card.set_name||'—'}${card.card_number?' · #'+card.card_number:''}${card.hp?' · '+card.hp+' HP':''}</p>
          <div class="card-badges">
            ${card.pokemon_type?`<span class="badge type-${(card.pokemon_type||'').toLowerCase().replace(' ','_')}">${card.pokemon_type}</span>`:''}
            ${card.rarity?`<span class="badge rarity-badge">${card.rarity}</span>`:''}
            ${varBadge}
          </div>
        </div>
        ${priceBadge}
        <div class="qty-bar">
          <button class="qty-btn minus" data-id="${card.id}">−</button>
          <span class="qty-num" id="qty-${card.id}">${card.quantity}</span>
          <button class="qty-btn plus" data-id="${card.id}">+</button>
        </div>
        <div class="card-actions">
          <button class="action-btn fav-btn ${card.is_favorite?'active':''}" data-id="${card.id}" title="Favorite">⭐</button>
          <button class="action-btn alert-btn" data-id="${card.id}" data-name="${card.name}" data-price="${card.market_price||0}" title="Alert">🔔</button>
          <button class="action-btn delete-btn" data-id="${card.id}" title="Remove">✕</button>
        </div>
      </div>
    </div>`;
}

async function loadNextPage() {
    if (infiniteLoading || infiniteExhausted || !grid) return;
    infiniteLoading = true;
    if (loadingMore) loadingMore.style.display = 'block';
    try {
        const params = new URLSearchParams({
            page: infinitePage, per: 40,
            q:      document.getElementById('col-search')?.value.trim()    || '',
            type:   document.getElementById('filter-type')?.value          || '',
            rarity: document.getElementById('filter-rarity')?.value        || '',
            condition: document.getElementById('filter-condition')?.value  || '',
            sort:   document.getElementById('sort-by')?.value              || 'newest',
            fav:    (document.getElementById('toggle-favorites')?.classList.contains('active') ? '1' : '')
        });
        const res  = await fetch(`/api/cards?${params}`);
        const data = await res.json();
        if (!data.cards?.length || data.cards.length < 40) infiniteExhausted = true;
        data.cards.forEach(c => {
            const div = document.createElement('div');
            div.innerHTML = buildCardHTML(c);
            grid.appendChild(div.firstElementChild);
        });
        infinitePage++;
    } catch(e) { console.error(e); }
    infiniteLoading = false;
    if (loadingMore) loadingMore.style.display = 'none';
}

if (sentinel) {
    const obs = new IntersectionObserver(entries => {
        if (entries[0].isIntersecting) loadNextPage();
    }, { rootMargin: '200px' });
    obs.observe(sentinel);
}

// ═══════════════════════════════════════════════════════════════
//  COLLECTION FILTER (client-side for already-loaded cards,
//  resets infinite scroll for server filters)
// ═══════════════════════════════════════════════════════════════

const colSearch   = document.getElementById('col-search');
const filterType  = document.getElementById('filter-type');
const filterRar   = document.getElementById('filter-rarity');
const filterCond  = document.getElementById('filter-condition');
const sortEl      = document.getElementById('sort-by');
const favToggle   = document.getElementById('toggle-favorites');
const countLabel  = document.getElementById('count-label');

let filterTimer = null;
let showFavsOnly = false;

[filterType, filterRar, filterCond, sortEl].forEach(el =>
    el?.addEventListener('change', () => reloadFiltered()));
colSearch?.addEventListener('input', () => {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(reloadFiltered, 400);
});
favToggle?.addEventListener('click', () => {
    showFavsOnly = !showFavsOnly;
    favToggle.classList.toggle('active', showFavsOnly);
    reloadFiltered();
});

async function reloadFiltered() {
    if (!grid) return;
    // Reset infinite scroll
    infinitePage = 2; infiniteExhausted = false;
    // Fetch page 1 with filters
    const params = new URLSearchParams({
        page: 1, per: 40,
        q:         colSearch?.value.trim()   || '',
        type:      filterType?.value         || '',
        rarity:    filterRar?.value          || '',
        condition: filterCond?.value         || '',
        sort:      sortEl?.value             || 'newest',
        fav:       showFavsOnly ? '1' : ''
    });
    const res  = await fetch(`/api/cards?${params}`);
    const data = await res.json();
    grid.innerHTML = data.cards.map(buildCardHTML).join('');
    if (!data.cards.length) {
        grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--muted)">No cards match your filters.</div>';
    }
    if (countLabel) countLabel.textContent = `${data.total} card${data.total!==1?'s':''}`;
    if ((data.cards?.length||0) < 40) infiniteExhausted = true;
}

// Always load cards fresh from the API on page load — this bypasses any
// service-worker-cached HTML that might show a stale empty grid.
reloadFiltered();

// ═══════════════════════════════════════════════════════════════
//  CARD INTERACTIONS (qty, delete, favorites, alerts)
// ═══════════════════════════════════════════════════════════════

document.addEventListener('click', async e => {
    // Qty buttons
    const qBtn = e.target.closest('.qty-btn');
    if (qBtn && grid?.contains(qBtn)) {
        const id    = qBtn.dataset.id;
        const delta = qBtn.classList.contains('plus') ? 1 : -1;
        const numEl = document.getElementById(`qty-${id}`);
        const res   = await fetch(`/update_quantity/${id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delta})});
        if ((await res.json()).success) {
            const cur = parseInt(numEl?.textContent||'1');
            if (cur+delta <= 0) { animOut(qBtn.closest('.card-item'), () => { qBtn.closest('.card-item')?.remove(); updHdr(delta); }); }
            else { if(numEl) { numEl.textContent = cur+delta; numEl.closest('.card-item').dataset.qty=cur+delta; } updHdr(delta); }
        }
        return;
    }
    // Delete
    const dBtn = e.target.closest('.delete-btn[data-id]');
    if (dBtn) {
        const id   = dBtn.dataset.id;
        const card = dBtn.closest('.card-item');
        const qty  = parseInt(card?.querySelector('.qty-num')?.textContent||'1');
        if ((await (await fetch(`/delete/${id}`,{method:'POST'})).json()).success) {
            animOut(card, () => { card?.remove(); updHdr(-qty); });
            showToast('Card removed');
        }
        return;
    }
    // Favorite
    const fBtn = e.target.closest('.fav-btn');
    if (fBtn) {
        const id  = fBtn.dataset.id;
        const res = await (await fetch(`/favorite/${id}`,{method:'POST'})).json();
        fBtn.classList.toggle('active', res.is_favorite===1);
        fBtn.closest('.card-item').dataset.fav = res.is_favorite;
        showToast(res.is_favorite ? '⭐ Favorited' : 'Unfavorited', 'info');
        return;
    }
    // Alert
    const aBtn = e.target.closest('.alert-btn');
    if (aBtn) {
        alertCardId = aBtn.dataset.id;
        document.getElementById('alert-card-name').textContent = aBtn.dataset.name;
        const p = parseFloat(aBtn.dataset.price)||0;
        document.getElementById('alert-current-val').textContent = p > 0 ? `$${p.toFixed(2)}` : 'N/A';
        document.getElementById('alert-target').value = p > 0 ? (p*.8).toFixed(2) : '';
        openModal('alert-set-modal');
    }
});

let alertCardId = null;
document.getElementById('btn-save-alert')?.addEventListener('click', async () => {
    const target = parseFloat(document.getElementById('alert-target').value);
    const dir    = document.getElementById('alert-direction').value;
    if (!alertCardId || isNaN(target)) { showToast('Enter a valid price','error'); return; }
    await fetch(ALERT_ADD_URL,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({card_id:alertCardId,target_price:target,direction:dir})});
    showToast('🔔 Alert saved!');
    closeModal('alert-set-modal');
});

async function loadAlerts() {
    const list = document.getElementById('alerts-list');
    if (!list) return;
    try {
        const data = await (await fetch(ALERTS_API_URL)).json();
        if (!data.length) { list.innerHTML = '<div class="results-hint"><span>🔔</span><p>No alerts yet.</p></div>'; return; }
        list.innerHTML = data.map(a => `
            <div class="alert-row" id="alert-row-${a.id}">
                ${a.image_small?`<img src="${a.image_small}" alt="">`:''}
                <div class="alert-info">
                    <strong>${a.name}</strong>
                    <span>Target: $${parseFloat(a.target_price).toFixed(2)} · Market: ${a.market_price>0?'$'+parseFloat(a.market_price).toFixed(2):'N/A'}</span>
                </div>
                <span class="alert-tag ${a.direction}">${a.direction==='below'?'↓ Below':'↑ Above'} $${parseFloat(a.target_price).toFixed(2)}</span>
                <button class="alert-del" data-id="${a.id}">✕</button>
            </div>`).join('');
        list.querySelectorAll('.alert-del').forEach(btn =>
            btn.addEventListener('click', async () => {
                await fetch(`/alerts/delete/${btn.dataset.id}`,{method:'POST'});
                document.getElementById(`alert-row-${btn.dataset.id}`)?.remove();
            }));
    } catch(e) { list.innerHTML = '<div class="results-empty">Failed to load.</div>'; }
}

// ── Helpers ────────────────────────────────────────────────────
function animOut(el, cb) {
    if (!el) { cb?.(); return; }
    el.style.transition='all .25s ease'; el.style.opacity='0'; el.style.transform='scale(.85)';
    setTimeout(()=>cb?.(),250);
}
function updHdr(delta) {
    const el = document.getElementById('hdr-cards');
    if (el) { const n = Math.max(0,(parseInt(el.textContent)||0)+delta); el.textContent=n; flash(el,delta>0?'#4ade80':'#f87171'); }
}
function flash(el,color){ el.style.transition='color .2s';el.style.color=color;setTimeout(()=>el.style.color='',600); }

// ── 3D tilt ────────────────────────────────────────────────────
document.addEventListener('mousemove', e => {
    const inner = e.target.closest('.card-inner');
    if (!inner || inner.closest('.modal')) return;
    const r  = inner.getBoundingClientRect();
    const dx = (e.clientX-r.left-r.width/2) /(r.width/2);
    const dy = (e.clientY-r.top -r.height/2)/(r.height/2);
    inner.style.transform = `translateY(-8px) rotateX(${-dy*5}deg) rotateY(${dx*5}deg) scale(1.02)`;
});
document.addEventListener('mouseleave',()=>{
    document.querySelectorAll('.card-inner').forEach(c=>c.style.transform='');
},true);

// ── Stagger ────────────────────────────────────────────────────
document.querySelectorAll('.card-item').forEach((c,i)=>{ c.style.animationDelay=`${Math.min(i*.04,.6)}s`; });

// ── Dynamic rarities from API ──────────────────────────────────
(async()=>{
    const sel = document.getElementById('filter-rarity');
    if (!sel) return;
    try {
        const data = await (await fetch('/api/rarities')).json();
        if (!data.data?.length) return;
        const existing = new Set([...sel.options].map(o=>o.value).filter(v=>v));
        data.data.forEach(r=>{ if(!existing.has(r)){ const o=document.createElement('option');o.value=r;o.textContent=r;sel.appendChild(o); } });
    } catch(e){}
})();

// ── Pinned set quick-stats ─────────────────────────────────────
if (typeof PINNED_SETS !== 'undefined' && PINNED_SETS?.length) {
    PINNED_SETS.forEach(async ps => {
        try {
            const data = await (await fetch(`/api/set/${ps.set_id}/completion`)).json();
            const fill = document.getElementById(`psfill-${ps.set_id}`);
            const pct  = document.getElementById(`pspct-${ps.set_id}`);
            if (fill) { fill.style.width=data.pct+'%'; fill.style.background=data.pct>=100?'#22c55e':data.pct>=75?'#f59e0b':'#3b82f6'; }
            if (pct)  pct.textContent = `${data.pct}%`;
        } catch(e){}
    });
}

// ═══════════════════════════════════════════════════════════════
//  IMPORT / EXPORT
// ═══════════════════════════════════════════════════════════════

const importDrop = document.getElementById('import-drop');
const importFile = document.getElementById('import-file');
let importSelectedFile = null;

importDrop?.addEventListener('click', () => importFile?.click());
importDrop?.addEventListener('dragover', e => { e.preventDefault(); importDrop.classList.add('drag-over'); });
importDrop?.addEventListener('dragleave', () => importDrop.classList.remove('drag-over'));
importDrop?.addEventListener('drop', e => { e.preventDefault(); importDrop.classList.remove('drag-over'); handleImportFile(e.dataTransfer.files[0]); });
importFile?.addEventListener('change', e => handleImportFile(e.target.files[0]));

function handleImportFile(file) {
    if (!file) return;
    importSelectedFile = file;
    if (importDrop) importDrop.querySelector('p').textContent = `📄 ${file.name}`;
}

document.getElementById('btn-import-submit')?.addEventListener('click', async () => {
    if (!importSelectedFile) { showToast('Select a file first','error'); return; }
    const fd = new FormData();
    fd.append('file', importSelectedFile);
    const btn = document.getElementById('btn-import-submit');
    btn.textContent = 'Importing…'; btn.disabled = true;
    try {
        const res  = await fetch('/import',{method:'POST',body:fd});
        const data = await res.json();
        const resultEl = document.getElementById('import-result');
        resultEl.style.display = 'block';
        if (data.error) { resultEl.innerHTML = `<div class="auth-error">${data.error}</div>`; }
        else {
            resultEl.innerHTML = `<div style="color:#4ade80;font-size:14px">✓ Imported ${data.imported} cards${data.errors?.length?` (${data.errors.length} skipped)`:''}.</div>`;
            if (data.imported > 0) setTimeout(()=>location.reload(), 1200);
        }
    } catch(e) { showToast('Import failed','error'); }
    btn.textContent = 'Import'; btn.disabled = false;
});

// ── PWA service worker ─────────────────────────────────────────
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(()=>{});
}