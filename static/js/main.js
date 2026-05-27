// ═══════════════════════════════════════════════════════════════
//  PokéVault — main.js  (multi-select, alerts, sort, wishlist)
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

// ── Generic modal helpers ──────────────────────────────────────
function openModal(id)  { document.getElementById(id)?.classList.add('open'); document.body.style.overflow = 'hidden'; }
function closeModal(id) { document.getElementById(id)?.classList.remove('open'); document.body.style.overflow = ''; }

document.querySelectorAll('.modal-close').forEach(btn => {
    btn.addEventListener('click', () => {
        const target = btn.dataset.close || btn.closest('.modal-overlay')?.id;
        if (target) closeModal(target);
        else document.querySelectorAll('.modal-overlay.open').forEach(m => closeModal(m.id));
    });
});
document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => { if (e.target === overlay) closeModal(overlay.id); });
});
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') document.querySelectorAll('.modal-overlay.open').forEach(m => closeModal(m.id));
});

// ── Avatar dropdown ────────────────────────────────────────────
const avatarBtn  = document.getElementById('avatar-btn');
const userDrop   = document.getElementById('user-dropdown');
avatarBtn?.addEventListener('click', e => { e.stopPropagation(); userDrop?.classList.toggle('open'); });
document.addEventListener('click', () => userDrop?.classList.remove('open'));

// ── Open search modal ──────────────────────────────────────────
document.getElementById('open-search-modal') ?.addEventListener('click', () => { openModal('search-modal'); setTimeout(() => document.getElementById('api-search-input')?.focus(), 100); });
document.getElementById('open-search-empty')  ?.addEventListener('click', () => { openModal('search-modal'); setTimeout(() => document.getElementById('api-search-input')?.focus(), 100); });
document.getElementById('close-search-modal') ?.addEventListener('click', () => closeModal('search-modal'));

// Stats & Alerts modals
document.getElementById('open-stats-modal')  ?.addEventListener('click', () => { closeModal('user-dropdown'); openModal('stats-modal'); });
document.getElementById('open-alerts-modal') ?.addEventListener('click', () => { closeModal('user-dropdown'); openModal('alerts-modal'); loadAlerts(); });

// ═══════════════════════════════════════════════════════════════
//  SEARCH & MULTI-SELECT
// ═══════════════════════════════════════════════════════════════

const apiInput    = document.getElementById('api-search-input');
const numInput    = document.getElementById('api-number-input');
const resultsEl   = document.getElementById('api-results');
const spinner     = document.getElementById('search-spinner');
const selPanel    = document.getElementById('selected-panel');
const cartBanner  = document.getElementById('cart-banner');
const cartInfo    = document.getElementById('cart-info');
const selCount    = document.getElementById('selection-count');

let searchTimer   = null;
let focusedCard   = null;   // single-focus for the detail panel
let selectedCards = new Map(); // tcg_id → {card, qty}
let selQty        = 1;

// Input debounce
[apiInput, numInput].forEach(el => {
    el?.addEventListener('input', () => {
        clearTimeout(searchTimer);
        spinner.classList.add('visible');
        searchTimer = setTimeout(doSearch, 380);
    });
});

async function doSearch() {
    const q  = apiInput?.value.trim() || '';
    const n  = numInput?.value.trim()  || '';
    if (!q && !n) { resetResults(); return; }
    try {
        const params = new URLSearchParams();
        if (q) params.set('q', q);
        if (n) params.set('number', n);
        const res  = await fetch(`/api/search?${params}`);
        const data = await res.json();
        spinner.classList.remove('visible');
        renderResults(data.data || []);
    } catch(e) {
        spinner.classList.remove('visible');
        resultsEl.innerHTML = '<div class="results-empty">⚠️ Search failed — check your connection.</div>';
    }
}

function renderResults(cards) {
    if (!cards.length) { resultsEl.innerHTML = '<div class="results-empty">No cards found. Try a different name or number.</div>'; return; }
    resultsEl.innerHTML = '';
    cards.forEach(card => {
        const thumb = document.createElement('div');
        thumb.className = 'result-thumb';
        thumb.dataset.id = card.id;

        // Check overlay
        const check = document.createElement('div');
        check.className = 'check-overlay';
        check.textContent = '✓';
        thumb.appendChild(check);

        if (card.images?.small) {
            const img = document.createElement('img');
            img.src = card.images.small; img.alt = card.name; img.loading = 'lazy';
            thumb.appendChild(img);
        } else {
            const ph = document.createElement('span');
            ph.className = 'result-thumb-placeholder';
            ph.textContent = card.name[0];
            thumb.appendChild(ph);
        }

        // Restore selected state if already in cart
        if (selectedCards.has(card.id)) thumb.classList.add('selected');

        thumb.addEventListener('click', (e) => handleThumbClick(e, card, thumb));
        resultsEl.appendChild(thumb);
    });
}

function handleThumbClick(e, card, thumb) {
    if (e.shiftKey || e.ctrlKey || e.metaKey) {
        // Multi-select mode
        toggleCartCard(card, thumb);
    } else {
        // Single-focus: show detail panel, also add to cart if not already
        focusedCard = card;
        selQty = selectedCards.get(card.id)?.qty || 1;
        showDetailPanel(card);
        // Visually highlight
        document.querySelectorAll('.result-thumb').forEach(t => t.classList.remove('focused'));
        thumb.classList.add('focused');
        // Also add to cart
        if (!selectedCards.has(card.id)) toggleCartCard(card, thumb);
    }
}

function toggleCartCard(card, thumb) {
    if (selectedCards.has(card.id)) {
        selectedCards.delete(card.id);
        thumb.classList.remove('selected');
    } else {
        selectedCards.set(card.id, { card, qty: 1 });
        thumb.classList.add('selected');
    }
    updateCartUI();
}

function updateCartUI() {
    const count = selectedCards.size;
    if (count === 0) {
        cartBanner.style.display = 'none';
        if (selCount) { selCount.style.display = 'none'; selCount.textContent = ''; }
        selPanel.style.display = 'none';
        focusedCard = null;
    } else {
        cartBanner.style.display = 'flex';
        cartInfo.textContent = `${count} card${count !== 1 ? 's' : ''} selected`;
        if (selCount) { selCount.style.display = 'inline'; selCount.textContent = `${count} selected`; }
    }
}

function showDetailPanel(card) {
    document.getElementById('sel-img').src = card.images?.large || card.images?.small || '';
    document.getElementById('sel-name').textContent = card.name;
    document.getElementById('sel-set').textContent  = `${card.set?.name || '—'} · ${card.set?.series || ''} · #${card.number || '?'}`;
    document.getElementById('sel-details').textContent =
        [card.supertypes?.[0], card.subtypes?.join(', '), card.hp ? `${card.hp} HP` : ''].filter(Boolean).join(' · ');
    const market = card.tcgplayer?.prices;
    let priceStr = 'Price unavailable';
    if (market) {
        const v = market.holofoil || market.normal || market['1stEditionHolofoil'] || Object.values(market)[0];
        if (v?.market) priceStr = `$${v.market.toFixed(2)} market`;
        else if (v?.mid) priceStr = `$${v.mid.toFixed(2)} mid`;
    }
    document.getElementById('sel-price').textContent = priceStr;
    document.getElementById('sel-qty-val').textContent = selQty;
    selPanel.style.display = 'block';
    selPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Qty in detail panel
document.getElementById('sel-qty-plus') ?.addEventListener('click', () => { selQty = Math.min(999, selQty + 1); document.getElementById('sel-qty-val').textContent = selQty; if (focusedCard && selectedCards.has(focusedCard.id)) selectedCards.get(focusedCard.id).qty = selQty; });
document.getElementById('sel-qty-minus')?.addEventListener('click', () => { selQty = Math.max(1, selQty - 1); document.getElementById('sel-qty-val').textContent = selQty; if (focusedCard && selectedCards.has(focusedCard.id)) selectedCards.get(focusedCard.id).qty = selQty; });

// ── Single card Add to Vault ───────────────────────────────────
document.getElementById('btn-add-to-vault')?.addEventListener('click', async () => {
    if (!focusedCard) return;
    const condition = document.getElementById('sel-condition').value;
    const payload = [buildPayload(focusedCard, condition, selQty)];
    await submitCards(payload);
});

// ── Bulk Add All ───────────────────────────────────────────────
document.getElementById('btn-add-all')?.addEventListener('click', async () => {
    if (!selectedCards.size) return;
    const condition = document.getElementById('bulk-condition').value;
    const payload = [...selectedCards.values()].map(({ card, qty }) => buildPayload(card, condition, qty));
    await submitCards(payload);
});

// Clear cart
document.getElementById('btn-clear-cart')?.addEventListener('click', () => {
    selectedCards.clear();
    document.querySelectorAll('.result-thumb').forEach(t => t.classList.remove('selected'));
    updateCartUI();
});

function buildPayload(card, condition, qty) {
    const market = card.tcgplayer?.prices;
    let price = 0;
    if (market) {
        const v = market.holofoil || market.normal || market['1stEditionHolofoil'] || Object.values(market)[0];
        price = v?.market || v?.mid || 0;
    }
    return {
        tcg_id: card.id, name: card.name,
        pokemon_type: card.types?.[0] || card.subtypes?.[0] || 'Colorless',
        rarity: card.rarity || '', set_name: card.set?.name || '', set_series: card.set?.series || '',
        card_number: card.number || '', hp: card.hp || '', subtypes: (card.subtypes||[]).join(', '),
        condition, quantity: qty, market_price: price,
        image_small: card.images?.small || '', image_large: card.images?.large || '', notes: ''
    };
}

async function submitCards(payload) {
    try {
        const res  = await fetch('/add', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
        const data = await res.json();
        if (data.success) {
            const added = data.results.filter(r=>r==='added').length;
            const incr  = data.results.filter(r=>r==='incremented').length;
            let msg = '';
            if (added)  msg += `${added} card${added>1?'s':''} added`;
            if (incr)   msg += (msg?' · ':'')+`${incr} qty updated`;
            showToast(msg || 'Done!');
            closeModal('search-modal');
            setTimeout(() => location.reload(), 700);
        }
    } catch(e) { showToast('Failed to add cards', 'error'); }
}

// ── Wishlist & Trade from detail panel ────────────────────────
document.getElementById('btn-add-to-wishlist')?.addEventListener('click', async () => {
    if (!focusedCard) return;
    await fetch(WISHLIST_URL, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(buildPayload(focusedCard,'Near Mint',1)) });
    showToast(`${focusedCard.name} added to Wishlist ⭐`, 'info');
});
document.getElementById('btn-add-to-tradelist')?.addEventListener('click', async () => {
    if (!focusedCard) return;
    await fetch(TRADELIST_URL, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(buildPayload(focusedCard,'Near Mint',1)) });
    showToast(`${focusedCard.name} added to Trade List ⇄`, 'info');
});

function resetResults() {
    resultsEl.innerHTML = '<div class="results-hint"><span>🔍</span><p>Search by name, or card number (e.g. 004/102)</p></div>';
    selPanel.style.display = 'none';
    cartBanner.style.display = 'none';
    selectedCards.clear();
    focusedCard = null;
    if (selCount) { selCount.style.display = 'none'; }
    spinner.classList.remove('visible');
}

// Reset when modal closes
document.getElementById('close-search-modal')?.addEventListener('click', () => { resetResults(); if(apiInput) apiInput.value=''; if(numInput) numInput.value=''; });

// ═══════════════════════════════════════════════════════════════
//  COLLECTION FILTER, SORT, FAVORITES
// ═══════════════════════════════════════════════════════════════

const colSearch   = document.getElementById('col-search');
const filterType  = document.getElementById('filter-type');
const filterRar   = document.getElementById('filter-rarity');
const filterCond  = document.getElementById('filter-condition');
const sortBy      = document.getElementById('sort-by');
const favToggle   = document.getElementById('toggle-favorites');
const countLabel  = document.getElementById('count-label');
const grid        = document.getElementById('cards-grid');

let showFavsOnly  = false;

[colSearch, filterType, filterRar, filterCond, sortBy].forEach(el => el?.addEventListener('change', applyFilters));
[colSearch].forEach(el => el?.addEventListener('input', applyFilters));
favToggle?.addEventListener('click', () => { showFavsOnly = !showFavsOnly; favToggle.classList.toggle('active', showFavsOnly); applyFilters(); });

function applyFilters() {
    if (!grid) return;
    const q    = colSearch?.value.toLowerCase().trim() || '';
    const typ  = filterType?.value.toLowerCase() || '';
    const rar  = filterRar?.value || '';
    const cond = filterCond?.value || '';
    const sort = sortBy?.value || 'newest';
    let items  = [...grid.querySelectorAll('.card-item')];

    // Filter
    items.forEach(item => {
        const name = item.dataset.name || '';
        const ok = (!q    || name.includes(q))
                && (!typ  || (item.dataset.type||'').toLowerCase().includes(typ))
                && (!rar  || item.dataset.rarity === rar)
                && (!cond || item.dataset.condition === cond)
                && (!showFavsOnly || item.dataset.fav === '1');
        item.style.display = ok ? '' : 'none';
    });

    // Sort visible
    const visible = items.filter(i => i.style.display !== 'none');
    visible.sort((a, b) => {
        if (sort === 'name')       return (a.dataset.name||'').localeCompare(b.dataset.name||'');
        if (sort === 'value-desc') return parseFloat(b.dataset.value||0) - parseFloat(a.dataset.value||0);
        if (sort === 'value-asc')  return parseFloat(a.dataset.value||0) - parseFloat(b.dataset.value||0);
        if (sort === 'qty-desc')   return parseInt(b.dataset.qty||0)   - parseInt(a.dataset.qty||0);
        return new Date(b.dataset.ts||0) - new Date(a.dataset.ts||0); // newest
    });
    visible.forEach(item => grid.appendChild(item));

    if (countLabel) countLabel.textContent = `${visible.length} card${visible.length!==1?'s':''}`;
}

// ── Quantity buttons ───────────────────────────────────────────
document.addEventListener('click', async e => {
    const btn = e.target.closest('.qty-btn');
    if (!btn || !grid?.contains(btn)) return;
    const id    = btn.dataset.id;
    const delta = btn.classList.contains('plus') ? 1 : -1;
    const numEl = document.getElementById(`qty-${id}`);
    const res   = await fetch(`/update_quantity/${id}`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({delta}) });
    const data  = await res.json();
    if (data.success) {
        const cur = parseInt(numEl?.textContent||'1');
        const nw  = cur + delta;
        if (nw <= 0) {
            const card = btn.closest('.card-item');
            animateOut(card, () => { card.remove(); updateHeaderCount(delta); });
        } else {
            if (numEl) { numEl.textContent = nw; numEl.closest('.card-item').dataset.qty = nw; }
            updateHeaderCount(delta);
        }
    }
});

// ── Delete ─────────────────────────────────────────────────────
document.addEventListener('click', async e => {
    const btn = e.target.closest('.delete-btn[data-id]');
    if (!btn || !grid?.contains(btn)) return;
    const id   = btn.dataset.id;
    const card = btn.closest('.card-item');
    const qty  = parseInt(card?.querySelector('.qty-num')?.textContent||'1');
    const res  = await fetch(`/delete/${id}`, { method:'POST' });
    const data = await res.json();
    if (data.success) {
        animateOut(card, () => { card.remove(); updateHeaderCount(-qty); });
        showToast('Card removed');
    }
});

// ── Favorite toggle ────────────────────────────────────────────
document.addEventListener('click', async e => {
    const btn = e.target.closest('.fav-btn');
    if (!btn) return;
    const id  = btn.dataset.id;
    const res = await fetch(`/favorite/${id}`, { method:'POST' });
    const data= await res.json();
    btn.classList.toggle('active', data.is_favorite === 1);
    btn.closest('.card-item').dataset.fav = data.is_favorite;
    showToast(data.is_favorite ? '⭐ Added to favorites' : 'Removed from favorites', 'info');
});

// ── Price alert trigger ────────────────────────────────────────
let alertCardId = null;
document.addEventListener('click', e => {
    const btn = e.target.closest('.alert-btn');
    if (!btn) return;
    alertCardId = btn.dataset.id;
    document.getElementById('alert-card-name').textContent = btn.dataset.name;
    const price = parseFloat(btn.dataset.price)||0;
    document.getElementById('alert-current-val').textContent = price > 0 ? `$${price.toFixed(2)}` : 'N/A';
    document.getElementById('alert-target').value = price > 0 ? (price * 0.8).toFixed(2) : '';
    openModal('alert-set-modal');
});

document.getElementById('btn-save-alert')?.addEventListener('click', async () => {
    const target    = parseFloat(document.getElementById('alert-target').value);
    const direction = document.getElementById('alert-direction').value;
    if (!alertCardId || isNaN(target)) { showToast('Enter a valid price', 'error'); return; }
    await fetch(ALERT_ADD_URL, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ card_id: alertCardId, target_price: target, direction }) });
    showToast('🔔 Alert saved!');
    closeModal('alert-set-modal');
});

// ── Load alerts list ───────────────────────────────────────────
async function loadAlerts() {
    const list = document.getElementById('alerts-list');
    if (!list) return;
    try {
        const res   = await fetch(ALERTS_API_URL);
        const data  = await res.json();
        if (!data.length) { list.innerHTML = '<div class="results-hint"><span>🔔</span><p>No alerts set yet. Use the 🔔 button on any card.</p></div>'; return; }
        list.innerHTML = '';
        data.forEach(a => {
            const row = document.createElement('div');
            row.className = 'alert-row';
            row.innerHTML = `
                ${a.image_small ? `<img src="${a.image_small}" alt="">` : ''}
                <div class="alert-info">
                    <strong>${a.name}</strong>
                    <span>Target: $${parseFloat(a.target_price).toFixed(2)} · Current: ${a.market_price > 0 ? '$'+parseFloat(a.market_price).toFixed(2) : 'N/A'}</span>
                </div>
                <span class="alert-tag ${a.direction}">${a.direction === 'below' ? '↓ Below' : '↑ Above'} $${parseFloat(a.target_price).toFixed(2)}</span>
                <button class="alert-del" data-id="${a.id}">✕</button>`;
            list.appendChild(row);
        });
        list.addEventListener('click', async e => {
            const del = e.target.closest('.alert-del');
            if (!del) return;
            await fetch(`/alerts/delete/${del.dataset.id}`, { method:'POST' });
            del.closest('.alert-row').remove();
        });
    } catch(e) { list.innerHTML = '<div class="results-empty">Failed to load alerts.</div>'; }
}

// ── Helpers ────────────────────────────────────────────────────
function animateOut(el, cb) {
    if (!el) return cb?.();
    el.style.transition = 'all .28s ease';
    el.style.opacity = '0';
    el.style.transform = 'scale(.85)';
    setTimeout(() => cb?.(), 280);
}
function updateHeaderCount(delta) {
    const el = document.getElementById('total-cards');
    if (el) { const n = Math.max(0,(parseInt(el.textContent)||0)+delta); el.textContent = n; flashEl(el, delta > 0 ? '#4ade80' : '#f87171'); }
}
function flashEl(el, color) {
    el.style.transition = 'color .2s'; el.style.color = color;
    setTimeout(() => el.style.color = '', 600);
}

// ── 3D tilt ────────────────────────────────────────────────────
document.addEventListener('mousemove', e => {
    const inner = e.target.closest('.card-inner');
    if (!inner) return;
    const r  = inner.getBoundingClientRect();
    const dx = (e.clientX - r.left - r.width/2)  / (r.width/2);
    const dy = (e.clientY - r.top  - r.height/2) / (r.height/2);
    inner.style.transform = `translateY(-8px) rotateX(${-dy*5}deg) rotateY(${dx*5}deg) scale(1.02)`;
});
document.addEventListener('mouseleave', () => {
    document.querySelectorAll('.card-inner').forEach(c => c.style.transform = '');
}, true);

// ── Stagger entrances ──────────────────────────────────────────
document.querySelectorAll('.card-item').forEach((c, i) => { c.style.animationDelay = `${Math.min(i * 0.04, 0.6)}s`; });

// ── Dynamic rarity filter from API ────────────────────────────
// Fetch real rarities from TCG API on page load and populate the dropdown
async function loadApiRarities() {
    const sel = document.getElementById('filter-rarity');
    if (!sel) return;
    try {
        const res  = await fetch('/api/rarities');
        const data = await res.json();
        if (!data.data?.length) return;
        // Keep current user-collection rarities, merge with all API rarities
        const existing = new Set([...sel.options].map(o => o.value).filter(v => v));
        data.data.forEach(r => {
            if (!existing.has(r)) {
                const opt = document.createElement('option');
                opt.value = r; opt.textContent = r;
                sel.appendChild(opt);
            }
        });
    } catch(e) { /* fail silently — collection rarities already there */ }
}
loadApiRarities();
