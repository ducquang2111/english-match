'use strict';
(() => {
  const $ = id => document.getElementById(id), CACHE = 'english-match-grammar';
  const state = { catalog: null, sections: [], progress: null, db: null, current: null, pending: undefined, saving: null, error: null, busy: false, loading: null };
  const el = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
  const fold = s => s.normalize('NFD').replace(/\p{M}/gu, '').replace(/[đĐ]/gu, 'd').toLowerCase();
  function note(text, error = false) { $('grammarSave').textContent = text; $('grammarSave').classList.toggle('save-error', error); $('grammarRetry').classList.toggle('hidden', !error); }
  async function api(path, data) {
    const r = await fetch(path, data === undefined ? {} : { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    const body = await r.json(); if (!r.ok) throw new Error(body.error || 'Không đọc được dữ liệu ngữ pháp.'); return body;
  }
  function inline(parent, text) {
    // Content and user input are always text nodes; no HTML is interpreted.
    for (const part of String(text).split(/(\*\*[^*]+\*\*)/g)) parent.append(part.startsWith('**') && part.endsWith('**') ? el('strong', part.slice(2, -2)) : document.createTextNode(part));
  }
  function renderBlocks(parent, blocks) {
    for (const block of blocks) {
      if (block.type === 'heading') parent.append(el('h3', block.text));
      else if (block.type === 'table') {
        const wrap = el('div', undefined, 'grammar-table'), table = el('table'), head = table.createTHead().insertRow(), body = table.createTBody();
        block.rows[0].forEach(cell => { const th = el('th'); th.scope = 'col'; inline(th, cell); head.append(th); });
        block.rows.slice(1).forEach(row => { const tr = body.insertRow(); row.forEach(cell => inline(tr.insertCell(), cell)); }); wrap.append(table); parent.append(wrap);
      } else if (block.type === 'list') {
        const list = el(block.ordered ? 'ol' : 'ul'); block.items.forEach(item => { const li = el('li'); inline(li, item); list.append(li); }); parent.append(list);
      } else { const p = el('p'); inline(p, block.text); parent.append(p); }
    }
  }
  function queueSave() {
    if (!state.db || !state.progress) return;
    state.progress.updatedAt = Math.max(Date.now(), state.progress.updatedAt + 1);
    const payload = { database_id: state.db, item: structuredClone(state.progress) };
    try { localStorage.setItem(CACHE, JSON.stringify(payload)); } catch {}
    state.pending = payload; note('Đang lưu…'); drain();
  }
  async function drain() {
    if (state.saving) return state.saving;
    state.saving = (async () => {
      while (state.pending !== undefined) {
        const payload = state.pending; state.pending = undefined;
        try { await api('/api/grammar/progress', payload); state.error = null; }
        catch (e) { if (state.pending === undefined) state.pending = payload; state.error = e; note(e.message, true); break; }
      }
      if (!state.error) note('Đã lưu tiến độ ngữ pháp');
    })();
    await state.saving; state.saving = null;
  }
  async function flush() { await drain(); if (state.error || state.pending !== undefined) throw state.error || new Error('Tiến độ ngữ pháp chưa được lưu.'); }
  async function reload(useCache = true) {
    if (!state.catalog && !$('grammarView').classList.contains('hidden')) return load(useCache);
    if (!state.catalog) return;
    const data = await api('/api/grammar/progress'); state.db = data.database_id; state.progress = data.item;
    if (useCache) {
      try { const cache = JSON.parse(localStorage.getItem(CACHE)); if (cache?.database_id === state.db && cache.item?.version === 1 && cache.item.updatedAt > state.progress.updatedAt && Array.isArray(cache.item.completed) && Array.isArray(cache.item.bookmarks)) { state.progress = cache.item; queueSave(); } } catch {}
    } else { try { localStorage.removeItem(CACHE); } catch {} state.pending = undefined; state.error = null; }
    const last = state.sections.find(s => s.id === state.progress.last_section) || state.sections[0];
    openSection(last.id, false); note('Đã tải tiến độ ngữ pháp');
  }
  async function load(useCache = true) {
    if (state.catalog) return;
    if (state.loading) return state.loading;
    state.loading = (async () => {
      note('Đang mở thư viện ngữ pháp…');
      try {
        state.catalog = await api('/api/grammar/catalog');
        state.sections = state.catalog.chapters.flatMap(ch => ch.sections.map(s => ({ ...s, chapter: ch, searchable: fold(ch.title + ' ' + s.title + ' ' + JSON.stringify(s.blocks)) })));
        $('grammarAboutText').replaceChildren();
        renderBlocks($('grammarAboutText'), [...state.catalog.introduction, ...state.catalog.sources]);
        await reload(useCache);
      } catch (e) { state.catalog = null; note(e.message, true); }
    })();
    await state.loading; state.loading = null;
  }
  function renderIndex() {
    if (!state.progress) return;
    const terms = fold($('grammarSearch').value.trim()).split(/\s+/).filter(Boolean), filter = $('grammarFilter').value;
    const completed = new Set(state.progress.completed), bookmarks = new Set(state.progress.bookmarks);
    $('grammarIndex').replaceChildren(); let matches = 0;
    for (const chapter of state.catalog.chapters) {
      const sections = state.sections.filter(s => s.chapter.id === chapter.id && terms.every(q => s.searchable.includes(q)) && (filter !== 'bookmarks' || bookmarks.has(s.id)) && (filter !== 'unread' || !completed.has(s.id)));
      if (!sections.length) continue;
      matches += sections.length;
      const details = el('details', undefined, 'grammar-chapter'); details.open = terms.length > 0 || filter !== 'all' || chapter.id === state.current?.chapter.id;
      const count = chapter.sections.filter(s => completed.has(s.id)).length;
      const summary = el('summary', `${chapter.id}. ${chapter.title}`); summary.append(el('span', `${count}/${chapter.sections.length} mục đã đọc`, 'small-muted')); details.append(summary);
      for (const section of sections) {
        const b = el('button', `${section.id} ${section.title}`, 'grammar-section-link'); b.type = 'button'; b.dataset.section = section.id;
        if (completed.has(section.id)) b.append(el('span', '✓', 'grammar-read-mark'));
        if (bookmarks.has(section.id)) b.append(el('span', '★', 'grammar-bookmark-mark'));
        if (section.id === state.current?.id) b.setAttribute('aria-current', 'true');
        b.addEventListener('click', () => openSection(section.id)); details.append(b);
      }
      $('grammarIndex').append(details);
    }
    if (!matches) $('grammarIndex').append(el('p', 'Không có mục phù hợp. Thử từ khóa khác hoặc đổi bộ lọc.', 'help'));
    $('grammarResults').textContent = `${matches} / ${state.sections.length} mục`;
    $('grammarTotal').textContent = `${state.catalog.chapters.length} chương · ${state.sections.filter(s => completed.has(s.id)).length}/${state.sections.length} mục đã đọc`;
  }
  function openSection(id, save = true) {
    if (state.busy && save) return;
    const section = state.sections.find(s => s.id === id); if (!section) return;
    state.current = section;
    $('grammarChapterLabel').textContent = `Chương ${section.chapter.id} · ${section.chapter.title}`;
    $('grammarTitle').textContent = `${section.id} ${section.title}`;
    const body = $('grammarBody'); body.replaceChildren(); renderBlocks(body, section.blocks);
    $('grammarSectionSelect').replaceChildren(...section.chapter.sections.map(s => new Option(`${s.id} ${s.title}`, s.id)));
    $('grammarSectionSelect').value = id;
    const i = state.sections.findIndex(s => s.id === id); $('grammarPrev').disabled = i === 0; $('grammarNext').disabled = i === state.sections.length - 1;
    $('grammarPosition').textContent = `Mục ${i + 1} / ${state.sections.length}`;
    if (save) { state.progress.last_section = id; queueSave(); }
    updateActions(); renderIndex();
    if (save) $('grammarTitle').focus({ preventScroll: true });
    $('grammarReader').scrollTop = 0;
  }
  function updateActions() {
    const read = state.progress?.completed.includes(state.current?.id), saved = state.progress?.bookmarks.includes(state.current?.id);
    $('grammarComplete').textContent = read ? '✓ Đã đọc' : 'Đánh dấu đã đọc'; $('grammarComplete').setAttribute('aria-pressed', String(!!read));
    $('grammarBookmark').textContent = saved ? '★ Đã lưu xem lại' : '☆ Lưu để xem lại'; $('grammarBookmark').setAttribute('aria-pressed', String(!!saved));
    $('grammarComplete').disabled = $('grammarBookmark').disabled = state.busy || !state.current;
  }
  for (const [button, key] of [['grammarComplete', 'completed'], ['grammarBookmark', 'bookmarks']]) $(button).addEventListener('click', () => {
    if (state.busy || !state.current) return;
    const set = new Set(state.progress[key]); set.has(state.current.id) ? set.delete(state.current.id) : set.add(state.current.id); state.progress[key] = [...set]; state.progress.last_section = state.current.id;
    queueSave(); updateActions(); renderIndex();
  });
  $('grammarPrev').addEventListener('click', () => openSection(state.sections[state.sections.indexOf(state.current) - 1]?.id));
  $('grammarNext').addEventListener('click', () => openSection(state.sections[state.sections.indexOf(state.current) + 1]?.id));
  $('grammarSectionSelect').addEventListener('change', () => openSection($('grammarSectionSelect').value));
  $('grammarSearch').addEventListener('input', renderIndex); $('grammarFilter').addEventListener('change', renderIndex);
  $('grammarRetry').addEventListener('click', () => state.catalog ? drain() : load());
  $('grammarAbout').addEventListener('click', () => $('grammarAboutDialog').showModal());
  $('grammarAboutClose').addEventListener('click', () => $('grammarAboutDialog').close());
  document.querySelector('[data-view="grammar"]').addEventListener('click', () => { if (!state.busy) load(); });
  window.Grammar = { flush, reload, setBusy(value) { state.busy = value; updateActions(); } };
})();
