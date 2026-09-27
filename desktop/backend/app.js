'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const CACHE = 'english-match-phase1-progress';
  const state = { vocab: [], lists: [], scope: 'all', session: null, databaseId: null,
    first: null, locked: false, timers: new Set(), epoch: 0, ready: false,
    pending: undefined, saving: null, saveError: null, restoreBusy: false };
  let toastTimer, editId, renameId, importPreview = null, restorePreview = null;
  function toast(text) {
    $('toast').textContent = text; $('toast').classList.add('show');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').classList.remove('show'), 3800);
  }
  function message(id, text, error = false) { $(id).textContent = text; $(id).className = `form-msg ${error ? 'err' : 'ok'}`; }
  async function api(url, options = {}) {
    const response = await fetch(url, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Không thể thực hiện (${response.status}).`);
    return data;
  }
  const json = (method, data) => ({ method, body: JSON.stringify(data) });
  function shuffle(array) {
    const result = [...array];
    for (let i = result.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [result[i], result[j]] = [result[j], result[i]]; }
    return result;
  }
  const pool = () => state.vocab.filter(w => state.scope === 'all' || String(w.list_id) === state.scope);
  const scopeName = () => state.scope === 'all' ? 'Tất cả list' : (state.lists.find(l => String(l.id) === state.scope)?.name || 'List đã chọn');
  const currentPage = () => state.session?.pageStates[state.session.pageIndex];
  const pageDone = i => state.session.pageStates[i].matched.length === state.session.pages[i].length;
  const allDone = () => !!state.session && state.session.pages.every((_, i) => pageDone(i));
  const completedCount = () => state.session?.pageStates.reduce((n, p) => n + p.matched.length, 0) || 0;
  function cancelEffects() {
    state.epoch++;
    for (const timer of state.timers) clearTimeout(timer);
    state.timers.clear(); state.first = null; state.locked = false;
  }
  function later(fn, delay) {
    const epoch = state.epoch;
    const timer = setTimeout(() => { state.timers.delete(timer); if (epoch === state.epoch) fn(); }, delay);
    state.timers.add(timer);
  }
  function saveLabel(text, error = false) {
    $('saveStatus').textContent = text; $('saveStatus').classList.toggle('save-error', error);
    $('retrySaveBtn').classList.toggle('hidden', !error);
  }
  function queueSave() {
    if (!state.databaseId) return;
    if (state.session) state.session.updatedAt = Date.now();
    const payload = { database_id: state.databaseId, item: state.session ? JSON.parse(JSON.stringify(state.session)) : null };
    try { localStorage.setItem(CACHE, JSON.stringify(payload)); } catch { /* SQLite is still used. */ }
    state.pending = payload; saveLabel('Đang lưu...'); drainSaves();
  }
  async function drainSaves() {
    if (state.saving) return state.saving;
    state.saving = (async () => {
      while (state.pending !== undefined) {
        const payload = state.pending; state.pending = undefined;
        try { await api('/api/progress', json('PUT', payload)); state.saveError = null; }
        catch (error) {
          if (state.pending === undefined) state.pending = payload;
          state.saveError = error; saveLabel('Chưa lưu vào database', true); break;
        }
      }
      if (!state.saveError) saveLabel('Đã lưu tiến độ');
    })();
    await state.saving; state.saving = null;
  }
  async function flushSaves() {
    await drainSaves();
    if (state.pending !== undefined || state.saveError) throw state.saveError || new Error('Tiến độ chưa được lưu. Hãy thử lại.');
  }
  window.EnglishMatchDesktop = Object.freeze({ flush: flushSaves });
  $('retrySaveBtn').addEventListener('click', () => { saveLabel('Đang thử lưu...'); drainSaves(); });
  window.addEventListener('beforeunload', event => {
    if (state.pending !== undefined || state.saving) { event.preventDefault(); event.returnValue = ''; }
  });
  // Separate identical labels onto different pages to avoid ambiguous matches.
  function makePages(words) {
    let remaining = shuffle(words); const pages = [];
    while (remaining.length) {
      const page = [], next = [], english = new Set(), vietnamese = new Set();
      for (const w of remaining) {
        const en = w.english.toLocaleLowerCase(), vi = w.vietnamese.toLocaleLowerCase();
        if (page.length < 8 && !english.has(en) && !vietnamese.has(vi)) { page.push(w.id); english.add(en); vietnamese.add(vi); }
        else next.push(w);
      }
      pages.push(page); remaining = next;
    }
    return pages;
  }
  function createRound() {
    cancelEffects();
    const words = pool().map(({ id, english, vietnamese, list_id }) => ({ id, english, vietnamese, list_id }));
    if (!words.length) state.session = null;
    else {
      const pages = makePages(words);
      state.session = { version: 1, scope: state.scope, words, pages, pageIndex: 0, updatedAt: Date.now(),
        pageStates: pages.map(ids => ({ matched: [], wrong: 0, wrongIds: [], order: shuffle(ids.flatMap(id => [`${id}-en`, `${id}-vi`])) })) };
    }
    renderGame(); queueSave();
  }
  function roundCompatible(s) {
    try {
      if (!s || s.version !== 1 || !Array.isArray(s.words) || !s.words.length) return false;
      if (s.scope !== 'all' && !state.lists.some(l => String(l.id) === s.scope)) return false;
      const fresh = new Map(state.vocab.map(w => [w.id, w]));
      if (!s.words.every(w => fresh.get(w.id)?.english === w.english && fresh.get(w.id)?.vietnamese === w.vietnamese && (s.scope === 'all' || String(fresh.get(w.id).list_id) === s.scope))) return false;
      const ids = s.words.map(w => w.id), flat = s.pages.flat();
      if (s.pages.length !== s.pageStates.length || flat.length !== ids.length || new Set(flat).size !== ids.length || !flat.every(id => ids.includes(id))) return false;
      if (!Number.isInteger(s.pageIndex) || !s.pages[s.pageIndex]) return false;
      return s.pages.every((ids, i) => {
        const p = s.pageStates[i], keys = ids.flatMap(id => [`${id}-en`, `${id}-vi`]);
        return ids.length > 0 && ids.length <= 8 && Array.isArray(p.matched) && new Set(p.matched).size === p.matched.length && p.matched.every(id => ids.includes(id)) &&
          Number.isInteger(p.wrong) && p.wrong >= 0 && Array.isArray(p.wrongIds) && p.wrongIds.every(id => ids.includes(id)) &&
          p.order.length === keys.length && new Set(p.order).size === keys.length && p.order.every(key => keys.includes(key));
      });
    } catch { return false; }
  }
  function updateStatus() {
    const s = state.session, p = currentPage(), count = s?.pages[s.pageIndex].length || 0;
    $('totalStat').textContent = state.vocab.length; $('listStat').textContent = state.lists.length;
    $('scopeCountStat').textContent = pool().length; $('scopeLabel').textContent = scopeName();
    $('pageLabel').textContent = `Trang ${s ? s.pageIndex + 1 : 0}/${s?.pages.length || 0}`;
    $('pairLabel').textContent = `${p?.matched.length || 0}/${count} cặp`;
    $('roundLabel').textContent = `${s?.words.length || 0} từ trong vòng`;
    $('correctStat').textContent = p?.matched.length || 0; $('wrongStat').textContent = p?.wrong || 0;
    $('roundStat').textContent = `${completedCount()}/${s?.words.length || 0}`;
    $('progressBar').style.width = count ? `${p.matched.length / count * 100}%` : '0%';
    $('prevBtn').disabled = !s || s.pageIndex === 0; $('nextBtn').disabled = !s || s.pageIndex === s.pages.length - 1;
    $('reshuffleBtn').disabled = !s || pageDone(s.pageIndex); $('newRoundBtn').disabled = !pool().length;
  }
  function boardMessage(title, description, action, handler) {
    const box = document.createElement('div'); box.className = 'complete-box';
    const inner = document.createElement('div'), h = document.createElement('h3'), p = document.createElement('p');
    h.textContent = title; p.textContent = description; inner.append(h, p);
    if (action) inner.append(actionButton(action, 'btn blue', handler));
    box.append(inner); $('board').replaceChildren(box);
  }
  function renderGame() {
    updateStatus();
    if (!state.session) return boardMessage('List này chưa có từ', 'Thêm từ trong Quản lý từ & list hoặc nhập hàng loạt.');
    if (allDone()) {
      const wrong = state.session.pageStates.reduce((n, p) => n + p.wrong, 0);
      return boardMessage('✓ Hoàn thành vòng học!', `Bạn đã hoàn thành ${state.session.words.length}/${state.session.words.length} từ trong ${scopeName()}. Tổng lượt ghép sai: ${wrong}.`, '↻ Random vòng mới', requestNewRound);
    }
    if (pageDone(state.session.pageIndex)) return boardMessage('✓ Trang này đã hoàn thành', 'Kết quả của trang đã được giữ lại.', 'Tiếp tục trang chưa xong', advance);
    const words = new Map(state.session.words.map(w => [w.id, w])), p = currentPage();
    $('board').replaceChildren();
    for (const key of p.order) {
      const [raw, side] = key.split('-'), id = Number(raw), w = words.get(id), b = document.createElement('button');
      b.type = 'button'; b.className = `card ${side === 'en' ? 'english' : 'vietnamese'}`;
      b.dataset.key = key; b.dataset.pairId = String(id); b.dataset.side = side;
      b.textContent = side === 'en' ? w.english : w.vietnamese;
      b.setAttribute('aria-label', `${side === 'en' ? 'Tiếng Anh' : 'Tiếng Việt'}: ${b.textContent}`);
      if (p.matched.includes(id)) { b.classList.add('matched'); b.disabled = true; b.setAttribute('aria-hidden', 'true'); }
      b.addEventListener('click', () => chooseCard(b)); $('board').append(b);
    }
  }
  function chooseCard(b) {
    if (!state.ready || state.restoreBusy || state.locked || b.disabled || b === state.first) return;
    b.classList.add('selected'); if (!state.first) { state.first = b; return; }
    state.locked = true;
    const a = state.first, p = currentPage(), id = Number(a.dataset.pairId);
    const correct = a.dataset.pairId === b.dataset.pairId && a.dataset.side !== b.dataset.side;
    a.classList.remove('selected'); b.classList.remove('selected');
    a.classList.add(correct ? 'correct' : 'wrong'); b.classList.add(correct ? 'correct' : 'wrong');
    if (correct) { if (!p.matched.includes(id)) p.matched.push(id); }
    else { p.wrong++; for (const x of [id, Number(b.dataset.pairId)]) if (!p.wrongIds.includes(x)) p.wrongIds.push(x); }
    updateStatus(); queueSave();
    later(() => {
      state.first = null; state.locked = false; renderGame();
      if (correct && pageDone(state.session.pageIndex) && !allDone()) later(advance, 450);
    }, correct ? 520 : 680);
  }
  function goPage(i) {
    if (!state.session || state.restoreBusy || i < 0 || i >= state.session.pages.length) return;
    cancelEffects(); state.session.pageIndex = i; renderGame(); queueSave();
  }
  function advance() {
    if (!state.session) return;
    for (let n = 1; n <= state.session.pages.length; n++) { const i = (state.session.pageIndex + n) % state.session.pages.length; if (!pageDone(i)) return goPage(i); }
    renderGame();
  }
  function approveReset() {
    return !state.session || allDone() || (completedCount() === 0 && !state.session.pageStates.some(p => p.wrong)) || confirm('Vòng mới sẽ thay thế tiến độ vòng đang học. Bạn muốn tiếp tục?');
  }
  function requestNewRound() { if (state.ready && !state.restoreBusy && approveReset()) { createRound(); toast('Đã tạo vòng mới từ kho từ hiện tại.'); } }
  $('newRoundBtn').addEventListener('click', requestNewRound);
  $('prevBtn').addEventListener('click', () => goPage(state.session.pageIndex - 1));
  $('nextBtn').addEventListener('click', () => goPage(state.session.pageIndex + 1));
  $('reshuffleBtn').addEventListener('click', () => {
    if (!state.session || state.restoreBusy || pageDone(state.session.pageIndex)) return;
    cancelEffects(); currentPage().order = shuffle(currentPage().order); renderGame(); queueSave(); toast('Đã trộn vị trí, giữ nguyên các cặp đã ghép.');
  });
  $('gameListSelect').addEventListener('change', () => {
    if (state.restoreBusy || !approveReset()) { $('gameListSelect').value = state.scope; return; }
    state.scope = $('gameListSelect').value; createRound();
  });
  function fillSelect(id, all = false) {
    const select = $(id), old = select.value; select.replaceChildren();
    if (all) select.add(new Option('Tất cả list', 'all'));
    state.lists.forEach(l => select.add(new Option(`${l.name} (${l.word_count})`, String(l.id))));
    if ([...select.options].some(o => o.value === old)) select.value = old;
  }
  function refreshSelectors() {
    ['gameListSelect', 'manageListFilter'].forEach(id => fillSelect(id, true));
    ['addListSelect', 'importListSelect', 'editListSelect'].forEach(id => fillSelect(id));
    if (state.scope !== 'all' && !state.lists.some(l => String(l.id) === state.scope)) state.scope = 'all';
    $('gameListSelect').value = state.scope;
    $('addForm').querySelector('[type="submit"]').disabled = !state.lists.length;
    $('previewImportBtn').disabled = !state.lists.length;
  }
  function actionButton(text, cls, fn) {
    const b = document.createElement('button'); b.type = 'button'; b.className = cls; b.textContent = text; b.addEventListener('click', fn); return b;
  }
  async function perform(fn, target, button) {
    if (state.restoreBusy) return;
    if (button) button.disabled = true;
    try { await fn(); } catch (e) { target ? message(target, e.message, true) : toast(e.message); }
    finally { if (button) button.disabled = false; }
  }
  function renderLists() {
    $('listManager').replaceChildren();
    if (!state.lists.length) { $('listManager').textContent = 'Chưa có list. Hãy tạo list để thêm từ.'; return; }
    for (const l of state.lists) {
      const row = document.createElement('div'); row.className = 'list-row';
      const name = document.createElement('strong'); name.textContent = l.name;
      const count = document.createElement('span'); count.className = 'count-badge'; count.textContent = `${l.word_count} từ`;
      const actions = document.createElement('div'); actions.className = 'row-actions';
      actions.append(actionButton('Đổi tên', 'icon-btn', () => {
        renameId = l.id; $('renameInput').value = l.name; message('renameMessage', ''); $('renameDialog').showModal();
      }), actionButton('Xóa', 'icon-btn delete', () => {
        if (l.word_count) return toast('Chuyển hoặc xóa các từ trước khi xóa list.');
        if (confirm(`Xóa list rỗng “${l.name}”?`)) perform(async () => { await api(`/api/lists/${l.id}`, { method: 'DELETE' }); await refreshData(); toast('Đã xóa list.'); });
      }));
      row.append(name, count, actions); $('listManager').append(row);
    }
  }
  function renderVocab() {
    const query = $('searchInput').value.trim().toLocaleLowerCase(), listId = $('manageListFilter').value;
    const items = state.vocab.filter(w => (!listId || listId === 'all' || String(w.list_id) === listId) &&
      (!query || [w.english, w.vietnamese, w.list_name].some(x => x.toLocaleLowerCase().includes(query))));
    $('listCount').textContent = `${items.length} từ`; $('vocabList').replaceChildren();
    if (!items.length) { $('vocabList').textContent = 'Không có từ phù hợp.'; return; }
    for (const w of items) {
      const row = document.createElement('div'); row.className = 'vocab-row'; row.dataset.id = String(w.id);
      const en = document.createElement('div'); en.className = 'word-en'; en.textContent = w.english;
      const vi = document.createElement('div'); vi.className = 'word-vi'; vi.textContent = w.vietnamese;
      const wrap = document.createElement('div'); wrap.className = 'row-list-wrap';
      const select = document.createElement('select'); select.className = 'select row-list-select'; select.setAttribute('aria-label', `List của từ ${w.english}`);
      state.lists.forEach(l => select.add(new Option(l.name, String(l.id)))); select.value = String(w.list_id);
      select.addEventListener('change', async () => {
        select.disabled = true;
        try { await api(`/api/vocabulary/${w.id}`, json('PUT', { list_id: select.value })); await refreshData(); toast('Đã chuyển từ sang list mới.'); }
        catch (e) { select.value = String(w.list_id); toast(e.message); }
        finally { select.disabled = false; }
      });
      wrap.append(select);
      const actions = document.createElement('div'); actions.className = 'row-actions';
      actions.append(actionButton('Sửa', 'icon-btn', () => {
        editId = w.id; $('editEnglish').value = w.english; $('editVietnamese').value = w.vietnamese;
        $('editListSelect').value = String(w.list_id); message('editMessage', ''); $('editDialog').showModal();
      }), actionButton('Xóa', 'delete-btn', () => {
        if (confirm(`Xóa “${w.english}” khỏi kho từ?`)) perform(async () => { await api(`/api/vocabulary/${w.id}`, { method: 'DELETE' }); await refreshData(); toast('Đã xóa từ.'); });
      }));
      row.append(en, vi, wrap, actions); $('vocabList').append(row);
    }
  }
  async function refreshData() {
    const [lists, words] = await Promise.all([api('/api/lists'), api('/api/vocabulary')]);
    state.lists = lists.items; state.vocab = words.items;
    refreshSelectors(); renderLists(); renderVocab(); importPreview = null; $('applyImportBtn').disabled = true;
    cancelEffects();
    if (state.session && !roundCompatible(state.session)) { createRound(); toast('Một từ trong vòng đã được sửa, chuyển hoặc xóa. Đã tạo vòng mới.'); }
    else if (!state.session && pool().length) createRound();
    else { renderGame(); if (state.session) queueSave(); }
  }
  document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => {
    if (state.restoreBusy) return;
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t === tab));
    ['game', 'vocab', 'data'].forEach(view => $(`${view}View`).classList.toggle('hidden', view !== tab.dataset.view));
  }));
  $('searchInput').addEventListener('input', renderVocab); $('manageListFilter').addEventListener('change', renderVocab);
  $('cancelEditBtn').addEventListener('click', () => $('editDialog').close());
  $('cancelRenameBtn').addEventListener('click', () => $('renameDialog').close());
  $('listForm').addEventListener('submit', e => {
    e.preventDefault(); perform(async () => {
      const data = await api('/api/lists', json('POST', { name: $('listNameInput').value.trim() }));
      $('listForm').reset(); await refreshData(); $('addListSelect').value = String(data.item.id); $('importListSelect').value = String(data.item.id);
      message('listFormMsg', `Đã tạo “${data.item.name}”.`);
    }, 'listFormMsg', e.submitter);
  });
  $('addForm').addEventListener('submit', e => {
    e.preventDefault(); perform(async () => {
      const list_id = $('addListSelect').value;
      await api('/api/vocabulary', json('POST', { english: $('englishInput').value.trim(), vietnamese: $('vietnameseInput').value.trim(), list_id }));
      $('addForm').reset(); await refreshData(); $('addListSelect').value = list_id;
      message('formMsg', 'Đã lưu từ. Từ mới sẽ có trong vòng random mới.'); $('englishInput').focus();
    }, 'formMsg', e.submitter);
  });
  $('editForm').addEventListener('submit', e => {
    e.preventDefault(); perform(async () => {
      await api(`/api/vocabulary/${editId}`, json('PUT', { english: $('editEnglish').value.trim(), vietnamese: $('editVietnamese').value.trim(), list_id: $('editListSelect').value }));
      $('editDialog').close(); await refreshData(); toast('Đã lưu thay đổi.');
    }, 'editMessage', e.submitter);
  });
  $('renameForm').addEventListener('submit', e => {
    e.preventDefault(); perform(async () => {
      await api(`/api/lists/${renameId}`, json('PUT', { name: $('renameInput').value.trim() }));
      $('renameDialog').close(); await refreshData(); toast('Đã đổi tên list.');
    }, 'renameMessage', e.submitter);
  });
  function importPayload() {
    return { text: $('importText').value, list_id: $('importListSelect').value,
      delimiter: ({ tab: '\t', pipe: '|' }[$('delimiterSelect').value] || $('delimiterSelect').value) };
  }
  function invalidateImport() { importPreview = null; $('applyImportBtn').disabled = true; $('importPreview').replaceChildren(); message('importMessage', 'Hãy bấm Xem trước trước khi nhập.'); }
  ['importText', 'importListSelect', 'delimiterSelect'].forEach(id => $(id).addEventListener(id === 'importText' ? 'input' : 'change', invalidateImport));
  $('importFile').addEventListener('change', () => perform(async () => {
    const file = $('importFile').files[0]; if (!file) return;
    if (file.size > 4 * 1024 * 1024) throw new Error('File nhập tối đa 4 MB.');
    try { $('importText').value = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()); }
    catch { throw new Error('Hãy lưu file bằng mã hóa UTF-8 rồi thử lại.'); }
    invalidateImport();
  }, 'importMessage'));
  function showImportReport(r) {
    message('importMessage', `${r.new} từ mới · ${r.duplicates} cặp trùng · ${r.errors} dòng lỗi.${r.errors ? ' Sửa hết dòng lỗi trước khi nhập.' : ''}`, !!r.errors);
    const table = document.createElement('table'), head = table.createTHead().insertRow();
    ['Dòng', 'Tiếng Anh', 'Tiếng Việt', 'Kết quả'].forEach(text => { const th = document.createElement('th'); th.textContent = text; head.append(th); });
    const body = table.createTBody();
    [...r.rows.filter(x => x.status === 'error'), ...r.rows.filter(x => x.status !== 'error')].slice(0, 100).forEach(x => {
      const tr = body.insertRow(); tr.className = `status-${x.status}`;
      [x.line, x.english, x.vietnamese, x.message].forEach(value => { tr.insertCell().textContent = value; });
    });
    $('importPreview').replaceChildren(table);
    if (r.rows.length > 100) { const p = document.createElement('p'); p.className = 'help'; p.textContent = 'Hiển thị tối đa 100 dòng, ưu tiên dòng lỗi. Các số tổng tính toàn bộ dữ liệu.'; $('importPreview').append(p); }
  }
  $('previewImportBtn').addEventListener('click', e => perform(async () => {
    importPreview = null; $('applyImportBtn').disabled = true;
    const payload = importPayload(), report = await api('/api/import/preview', json('POST', payload));
    if (JSON.stringify(payload) !== JSON.stringify(importPayload())) return;
    importPreview = payload; showImportReport(report); $('applyImportBtn').disabled = report.errors > 0 || report.new === 0;
  }, 'importMessage', e.currentTarget));
  $('applyImportBtn').addEventListener('click', e => perform(async () => {
    if (!importPreview || JSON.stringify(importPreview) !== JSON.stringify(importPayload())) throw new Error('Nội dung đã đổi. Hãy xem trước lại.');
    const report = await api('/api/import', json('POST', importPreview));
    await refreshData(); showImportReport(report); importPreview = null;
    message('importMessage', `Đã nhập ${report.new} từ; bỏ qua ${report.duplicates} cặp trùng. Từ mới sẽ có trong vòng tiếp theo.`);
  }, 'importMessage', e.currentTarget).finally(() => { $('applyImportBtn').disabled = true; }));
  $('downloadBackupBtn').addEventListener('click', e => perform(async () => {
    cancelEffects(); renderGame(); await flushSaves();
    const response = await fetch('/api/backup'); if (!response.ok) throw new Error('Không tải được bản sao lưu.');
    const blob = await response.blob(), url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = `english-match-backup-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000); toast('Đã tải bản sao lưu kho từ và tiến độ.');
  }, 'restoreMessage', e.currentTarget));
  $('restoreFile').addEventListener('change', () => { restorePreview = null; $('applyRestoreBtn').classList.add('hidden'); message('restoreMessage', ''); });
  $('previewRestoreBtn').addEventListener('click', e => perform(async () => {
    restorePreview = null; $('applyRestoreBtn').classList.add('hidden');
    const file = $('restoreFile').files[0]; if (!file) throw new Error('Hãy chọn file sao lưu JSON.');
    if (file.size > 30 * 1024 * 1024) throw new Error('File sao lưu tối đa 30 MB.');
    let backup; try { backup = JSON.parse(await file.text()); } catch { throw new Error('File JSON không hợp lệ.'); }
    const result = await api('/api/restore/preview', json('POST', { backup }));
    if ($('restoreFile').files[0] !== file) return;
    restorePreview = { backup, token: result.token };
    message('restoreMessage', `${result.lists} list · ${result.words} từ · ${result.has_progress ? 'Có' : 'Không có'} tiến độ. Khôi phục thay thế dữ liệu hiện tại.`);
    $('applyRestoreBtn').classList.remove('hidden');
  }, 'restoreMessage', e.currentTarget));
  $('applyRestoreBtn').addEventListener('click', async () => {
    if (!restorePreview || state.restoreBusy || !confirm('Thay thế toàn bộ kho từ và tiến độ bằng bản đã chọn? Một bản database dự phòng sẽ được tạo trước khi thay thế.')) return;
    state.restoreBusy = true; $('applyRestoreBtn').disabled = true;
    try {
      cancelEffects(); await flushSaves();
      const result = await api('/api/restore', json('POST', restorePreview));
      try { localStorage.removeItem(CACHE); } catch {}
      state.session = null; state.pending = undefined; state.saveError = null;
      await initialize(false); restorePreview = null; $('applyRestoreBtn').classList.add('hidden');
      message('restoreMessage', `Đã khôi phục. Bản dự phòng: backups/${result.safety_backup}`);
    } catch (e) { message('restoreMessage', e.message, true); }
    finally { state.restoreBusy = false; $('applyRestoreBtn').disabled = false; }
  });
  async function initialize(useCache = true) {
    const [lists, words, progress] = await Promise.all([api('/api/lists'), api('/api/vocabulary'), api('/api/progress')]);
    state.lists = lists.items; state.vocab = words.items; state.databaseId = progress.database_id;
    let restored = progress.item;
    if (useCache) {
      try { const cache = JSON.parse(localStorage.getItem(CACHE));
        if (cache?.database_id === state.databaseId && cache.item?.updatedAt > (restored?.updatedAt || 0) && roundCompatible(cache.item)) restored = cache.item;
      } catch {}
    }
    state.session = roundCompatible(restored) ? restored : null; state.scope = state.session?.scope || 'all'; state.ready = true;
    refreshSelectors(); renderLists(); renderVocab();
    if (state.session) { cancelEffects(); renderGame(); queueSave(); toast('Đã khôi phục vòng học. Bạn có thể tiếp tục từ vị trí trước.'); }
    else createRound();
  }
  initialize().catch(e => {
    saveLabel('Không kết nối được', true);
    boardMessage('Chưa kết nối được máy chủ', `${e.message} Hãy chạy python3 server.py rồi tải lại trang.`);
  });
})();
