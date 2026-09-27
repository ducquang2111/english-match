'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const CACHE = 'english-match-phase2-review', PREFS = 'english-match-speech';
  const modes = { match: 'Ghép cặp', flashcard: 'Flashcard', typing: 'Gõ đáp án' };
  const statuses = { active: 'Đang học', stopped: 'Đã dừng', completed: 'Hoàn thành' };
  const state = { words: [], lists: [], session: null, databaseId: null, ready: false, busy: false,
    pending: undefined, saving: null, error: null, stats: null, offset: 0, wordOffset: 0, historyEpoch: 0, loadEpoch: 0 };
  let voices = [], preferredVoice = '', refreshTimer, toastTimer;
  function note(id, text, error = false) { $(id).textContent = text; $(id).classList.toggle('err', error); }
  function toast(text) {
    $('toast').textContent = text; $('toast').classList.add('show');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').classList.remove('show'), 4200);
  }
  async function api(path, data) {
    const response = await fetch(path, data === undefined ? {} : { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || `Không thể kết nối (${response.status}).`);
    return body;
  }
  function el(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
  function button(text, fn, cls = 'btn secondary') { const e = el('button', text, cls); e.type = 'button'; e.addEventListener('click', fn); return e; }
  function shuffle(words) { const a = [...words]; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; }
  const normalize = value => value.normalize('NFKC').replace(/[’‘ʼ]/g, "'").trim().replace(/\s+/gu, ' ').toLowerCase();
  function saveLabel(text, error = false) { note('reviewSave', text); $('reviewSave').classList.toggle('save-error', error); $('retryReviewSave').classList.toggle('hidden', !error); }
  function queueSave() {
    if (!state.databaseId) return;
    if (state.session) state.session.updatedAt = Math.max(Date.now(), state.session.updatedAt + 1);
    const payload = { database_id: state.databaseId, item: state.session ? structuredClone(state.session) : null };
    try { localStorage.setItem(CACHE, JSON.stringify(payload)); } catch {}
    state.pending = payload; saveLabel('Đang lưu...'); drain();
  }
  async function drain() {
    if (state.saving) return state.saving;
    state.saving = (async () => {
      while (state.pending !== undefined) {
        const payload = state.pending; state.pending = undefined;
        try { await api('/api/review/progress', payload); if (state.error) note('reviewMessage', 'Đã lưu lại thành công.'); state.error = null; window.dispatchEvent(new Event('learning-updated')); }
        catch (e) { if (state.pending === undefined) state.pending = payload; state.error = e; saveLabel('Chưa lưu vào database', true); note('reviewMessage', e.message, true); break; }
      }
      if (!state.error) saveLabel('Đã lưu tiến độ');
    })();
    await state.saving; state.saving = null;
  }
  async function flush() { await drain(); if (state.pending !== undefined || state.error) throw state.error || new Error('Tiến độ ôn tập chưa được lưu. Hãy thử lại.'); }
  function compatible(s) {
    try {
      if (!s || s.version !== 1 || !['flashcard', 'typing'].includes(s.mode) || !s.words.length || !Array.isArray(s.results)) return false;
      if (s.scope !== 'all' && !state.lists.some(l => String(l.id) === s.scope)) return false;
      const words = new Map(state.words.map(w => [w.id, w]));
      return Number.isInteger(s.index) && s.index >= 0 && s.index <= s.words.length && [s.index, s.index + 1].includes(s.results.length) &&
        s.words.every(w => words.get(w.id)?.english === w.english && words.get(w.id)?.vietnamese === w.vietnamese && (s.scope === 'all' || String(words.get(w.id).list_id) === s.scope));
    } catch { return false; }
  }
  function fillScope() {
    const old = $('reviewScope').value; $('reviewScope').replaceChildren(new Option('Tất cả list', 'all'));
    state.lists.forEach(l => $('reviewScope').add(new Option(`${l.name} (${l.word_count})`, String(l.id))));
    if ([...$('reviewScope').options].some(o => o.value === old)) $('reviewScope').value = old;
  }
  async function reload(useCache = true) {
    const epoch = ++state.loadEpoch; state.ready = false; $('startReviewBtn').disabled = true;
    const [vocab, lists, progress] = await Promise.all([api('/api/vocabulary'), api('/api/lists'), api('/api/review/progress')]);
    if (epoch !== state.loadEpoch) return;
    state.words = vocab.items; state.lists = lists.items; state.databaseId = progress.database_id;
    let restored = progress.item;
    if (useCache) {
      try { const cached = JSON.parse(localStorage.getItem(CACHE)); if (cached?.database_id === state.databaseId && cached.item?.updatedAt > (restored?.updatedAt || 0) && compatible(cached.item)) restored = cached.item; } catch {}
    } else { try { localStorage.removeItem(CACHE); } catch {} state.pending = undefined; state.error = null; }
    state.session = compatible(restored) ? restored : null; state.ready = true;
    fillScope();
    if (state.session) { $('reviewMode').value = state.session.mode; $('reviewScope').value = state.session.scope; $('reviewWrongOnly').checked = state.session.wrongOnly; }
    $('startReviewBtn').disabled = state.busy; render();
    if (restored) { queueSave(); note('reviewMessage', state.session ? 'Đã khôi phục buổi ôn. Bạn có thể học tiếp.' : 'Một từ đã thay đổi. Hãy bắt đầu buổi mới; lịch sử cũ vẫn được giữ.'); }
    else saveLabel('Sẵn sàng');
    state.stats = null;
  }
  async function refreshWords() {
    if (!state.ready || state.busy) return;
    try {
      const [words, lists] = await Promise.all([api('/api/vocabulary'), api('/api/lists')]);
      state.words = words.items; state.lists = lists.items; fillScope(); state.stats = null;
      if (state.session && !compatible(state.session)) { state.session = null; queueSave(); render(); note('reviewMessage', 'Từ trong buổi ôn đã thay đổi. Hãy bắt đầu buổi mới.'); }
    } catch (e) { note('reviewMessage', e.message, true); }
  }
  async function start() {
    if (!state.ready || state.busy) return;
    if (state.session && state.session.results.length && state.session.results.length < state.session.words.length && !confirm('Dừng buổi đang học và bắt đầu buổi mới? Kết quả đã làm vẫn được giữ trong lịch sử.')) return;
    state.busy = true; $('startReviewBtn').disabled = true; note('reviewMessage', 'Đang chuẩn bị buổi ôn...');
    try {
      await flush();
      const [vocab, stats] = await Promise.all([api('/api/vocabulary'), api('/api/learning/stats')]);
      state.words = vocab.items; state.stats = stats;
      const scope = $('reviewScope').value, wrongOnly = $('reviewWrongOnly').checked;
      const wrong = new Set(stats.words.filter(w => w.needs_review).map(w => w.id));
      const words = state.words.filter(w => (scope === 'all' || String(w.list_id) === scope) && (!wrongOnly || wrong.has(w.id)));
      if (!words.length) { note('reviewMessage', wrongOnly ? 'Không có từ cần ôn trong phạm vi này. Bạn có thể bỏ chọn “Chỉ ôn từ sai / chưa nhớ”.' : 'Phạm vi này chưa có từ. Hãy thêm từ trong Quản lý từ & list.'); return; }
      if (words.length > 10000) throw new Error('Buổi ôn tối đa 10.000 từ. Hãy chọn một list nhỏ hơn.');
      const now = Date.now();
      state.session = { version: 1, id: crypto.randomUUID(), mode: $('reviewMode').value, scope,
        scopeName: scope === 'all' ? 'Tất cả list' : (state.lists.find(l => String(l.id) === scope)?.name || 'List đã chọn'),
        wrongOnly, startedAt: now, updatedAt: now, words: shuffle(words.map(({ id, english, vietnamese, list_id }) => ({ id, english, vietnamese, list_id }))), index: 0, results: [], flipped: false };
      window.speechSynthesis?.cancel(); note('reviewMessage', ''); queueSave(); render();
    } catch (e) { note('reviewMessage', e.message, true); }
    finally { state.busy = false; $('startReviewBtn').disabled = !state.ready; }
  }
  function speechButton(word, enabled = true) {
    const b = button('🔊 Nghe phát âm', () => speak(word)); b.dataset.speech = 'true'; b.dataset.allowed = String(enabled);
    b.disabled = !enabled || !voices.length; return b;
  }
  function render() {
    const s = state.session, area = $('studyArea'); area.replaceChildren();
    $('reviewProgressBar').style.width = s ? `${s.results.length / s.words.length * 100}%` : '0%';
    $('reviewCounter').textContent = s ? `${modes[s.mode]} · ${s.scopeName}${s.wrongOnly ? ' · Từ cần ôn' : ''} · ${s.results.length}/${s.words.length}` : 'Chưa có buổi ôn';
    if (!s) {
      const box = el('div', undefined, 'study-card'); box.append(el('span', 'Mỗi ngày, nhớ thêm một chút', 'main-word'), el('span', 'Chọn cách học và bấm “Bắt đầu buổi mới”.', 'small-muted')); area.append(box); return;
    }
    if (s.index >= s.words.length) {
      const right = s.results.filter(r => r.correct).length, wrong = s.results.length - right;
      const box = el('div', undefined, 'study-card'); box.append(el('h3', '✓ Hoàn thành buổi ôn!', 'main-word'),
        el('p', s.mode === 'flashcard' ? `${right} từ đã nhớ · ${wrong} từ chưa nhớ (tự đánh giá)` : `${right} đúng · ${wrong} sai · Độ chính xác ${Math.round(right / s.words.length * 100)}%`));
      const actions = el('div', undefined, 'study-actions'); actions.append(button('Học buổi mới', start, 'btn blue'), button('Ôn từ sai', () => { $('reviewWrongOnly').checked = true; start(); })); box.append(actions); area.append(box); return;
    }
    const word = s.words[s.index], result = s.results[s.index];
    if (s.mode === 'flashcard') {
      const card = button('', () => { if (state.busy) return; s.flipped = !s.flipped; queueSave(); render(); }, 'study-card'); card.id = 'flashCard'; card.setAttribute('aria-label', s.flipped ? 'Mặt nghĩa. Bấm để xem từ tiếng Anh' : 'Mặt từ tiếng Anh. Bấm để xem nghĩa');
      card.append(el('span', s.flipped ? 'NGHĨA TIẾNG VIỆT' : 'TỪ TIẾNG ANH', 'small-muted'), el('span', s.flipped ? word.vietnamese : word.english, 'main-word'));
      if (s.flipped) card.append(el('span', word.english, 'translation'));
      card.append(el('span', 'Bấm vào thẻ để lật', 'small-muted'));
      const actions = el('div', undefined, 'study-actions');
      const rate = correct => { if (state.busy || !s.flipped) return; s.results.push({ correct, answer: '', at: Date.now() }); s.index++; s.flipped = false; window.speechSynthesis?.cancel(); queueSave(); render(); };
      const forgot = button('Chưa nhớ', () => rate(false), 'btn danger'), remembered = button('Đã nhớ', () => rate(true), 'btn blue'); forgot.id = 'flashForgot'; remembered.id = 'flashRemembered'; forgot.disabled = remembered.disabled = !s.flipped;
      actions.append(forgot, remembered); area.append(card, actions, speechButton(word.english));
    } else {
      const cue = el('div', undefined, 'study-card'); cue.append(el('span', 'GÕ TỪ TIẾNG ANH CÓ NGHĨA', 'small-muted'), el('span', word.vietnamese, 'main-word'));
      const form = el('form', undefined, 'answer-form'); form.id = 'typingForm';
      const label = el('label', 'Đáp án của bạn', 'select-label'); label.htmlFor = 'typingAnswer';
      const input = el('input', undefined, 'input'); input.id = 'typingAnswer'; input.autocomplete = 'off'; input.spellcheck = false; input.setAttribute('autocapitalize', 'none'); input.maxLength = 1000; input.required = true; input.readOnly = !!result; input.value = result?.answer || '';
      const help = el('p', 'Bỏ qua chữ hoa / thường và khoảng trắng thừa; các từ và dấu câu còn lại phải khớp từ đã lưu.', 'help');
      form.append(label, input, help);
      if (result) {
        const feedback = el('div', `${result.correct ? '✓ Chính xác!' : 'Chưa đúng.'} Đáp án: ${word.english}`, `answer-feedback ${result.correct ? 'good' : 'bad'}`); feedback.id = 'typingFeedback'; feedback.setAttribute('role', 'status'); form.append(feedback);
        const actions = el('div', undefined, 'study-actions');
        const next = button(s.index === s.words.length - 1 ? 'Xem kết quả' : 'Từ tiếp theo →', () => { if (state.busy) return; s.index++; window.speechSynthesis?.cancel(); queueSave(); render(); }, 'btn blue'); next.id = 'typingNext'; actions.append(speechButton(word.english), next); form.append(actions);
      } else {
        const submit = el('button', 'Kiểm tra đáp án', 'btn blue'); submit.type = 'submit'; submit.id = 'checkAnswerBtn'; form.append(submit);
      }
      form.addEventListener('submit', e => { e.preventDefault(); if (state.busy || s.results[s.index] || !input.value.trim()) return; s.results.push({ correct: normalize(input.value) === normalize(word.english), answer: input.value, at: Date.now() }); queueSave(); render(); $('typingNext')?.focus(); });
      area.append(cue, form); if (!result && !$('reviewView').classList.contains('hidden')) input.focus();
    }
  }
  function loadVoices() {
    voices = window.speechSynthesis?.getVoices().filter(v => /^en(?:-|_|$)/i.test(v.lang)) || [];
    $('voiceSelect').replaceChildren();
    voices.forEach((v, i) => $('voiceSelect').add(new Option(`${v.name} (${v.lang})`, String(i))));
    if (!voices.length) $('voiceSelect').add(new Option('Chưa có giọng tiếng Anh', ''));
    const index = voices.findIndex(v => v.voiceURI === preferredVoice);
    if (index >= 0) $('voiceSelect').value = String(index);
    $('voiceSelect').disabled = !voices.length;
    note('speechStatus', !('speechSynthesis' in window) ? 'Ứng dụng chưa tìm thấy chức năng đọc văn bản.' : voices.length ? 'Bấm nút 🔊 để nghe. Giọng đọc do hệ điều hành trên máy cung cấp.' : 'Chưa tìm thấy giọng tiếng Anh. Hãy cài giọng tiếng Anh trong cài đặt giọng nói của Windows hoặc macOS.');
    document.querySelectorAll('[data-speech]').forEach(b => { b.disabled = b.dataset.allowed !== 'true' || !voices.length; });
  }
  function speak(text) {
    if (state.busy) return;
    if (!voices.length || !window.SpeechSynthesisUtterance) { loadVoices(); toast($('speechStatus').textContent); return; }
    const voice = voices[Number($('voiceSelect').value)] || voices[0];
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text); utterance.voice = voice; utterance.lang = voice.lang; utterance.rate = Number($('speechRate').value);
    utterance.onerror = e => { if (!['interrupted', 'canceled'].includes(e.error)) { note('speechStatus', 'Không phát được âm thanh. Kiểm tra âm lượng, kết nối và giọng đọc rồi thử lại.'); toast('Không phát được âm thanh. Kiểm tra cài đặt giọng đọc.'); } };
    window.speechSynthesis.speak(utterance);
  }
  function saveSpeechPrefs() { preferredVoice = voices[Number($('voiceSelect').value)]?.voiceURI || ''; try { localStorage.setItem(PREFS, JSON.stringify({ voice: preferredVoice, rate: $('speechRate').value })); } catch {} }
  try { const prefs = JSON.parse(localStorage.getItem(PREFS)); preferredVoice = prefs?.voice || ''; if (['0.7', '0.85', '1'].includes(prefs?.rate)) $('speechRate').value = prefs.rate; } catch {}
  $('voiceSelect').addEventListener('change', saveSpeechPrefs); $('speechRate').addEventListener('change', saveSpeechPrefs);
  window.speechSynthesis?.addEventListener('voiceschanged', loadVoices); loadVoices();
  const date = value => value == null ? 'Chưa luyện' : new Date(value).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' });
  function table(headers, rows, empty) {
    if (!rows.length) return el('p', empty, 'help');
    const t = el('table'), head = t.createTHead().insertRow(); headers.forEach(h => head.append(el('th', h))); const body = t.createTBody();
    rows.forEach(cells => { const tr = body.insertRow(); cells.forEach(value => { const td = tr.insertCell(); if (value instanceof Node) td.append(value); else td.textContent = value; }); }); return t;
  }
  function renderStats() {
    if (!state.stats) return;
    const { totals: t, recent } = state.stats, attempts = t.correct + t.wrong;
    $('completedMetric').textContent = t.completed; $('practicedMetric').textContent = t.words_practiced;
    $('accuracyMetric').textContent = attempts ? `${Math.round(t.correct / attempts * 100)}%` : '—'; $('wrongMetric').textContent = t.needs_review;
    $('statsDetail').textContent = `${t.sessions} buổi đã tạo · Ghép cặp / gõ: ${t.correct} lượt đúng, ${t.wrong} lượt sai. Flashcard: ${t.remembered} lượt đã nhớ, ${t.forgotten} lượt chưa nhớ (tính riêng, không cộng vào độ chính xác).`;
    $('weekStats').replaceChildren();
    for (let i = 6; i >= 0; i--) {
      const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - i); const end = new Date(d); end.setDate(d.getDate() + 1);
      const count = recent.filter(r => r.started_at >= d.getTime() && r.started_at < end.getTime()).reduce((sum, r) => sum + r.correct + r.wrong, 0);
      const cell = el('div', i === 0 ? 'Hôm nay' : d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' }), 'day-cell'); cell.append(el('b', count)); $('weekStats').append(cell);
    }
    renderWords();
  }
  function renderWords() {
    const q = $('wordStatsSearch').value.trim().toLowerCase(), filter = $('wordStatsFilter').value;
    const rows = (state.stats?.words || []).filter(w => (!q || `${w.english} ${w.vietnamese}`.toLowerCase().includes(q)) && (filter === 'all' || (filter === 'wrong' ? w.needs_review : w.reviews)));
    if (state.wordOffset >= rows.length) state.wordOffset = Math.max(0, Math.floor((rows.length - 1) / 20) * 20);
    $('wordStatsTable').replaceChildren(table(['Từ / nghĩa', 'List', 'Đúng / sai', 'Nhớ / chưa nhớ', 'Lần gần nhất', 'Trạng thái'], rows.slice(state.wordOffset, state.wordOffset + 20).map(w => {
      const word = el('div'); word.append(el('strong', w.english), el('div', w.vietnamese, 'small-muted'));
      return [word, w.list_name, `${w.correct_count} / ${w.wrong_count}`, `${w.remembered} / ${w.forgotten}`, date(w.last_reviewed), w.needs_review ? 'Cần ôn' : w.reviews ? 'Đã luyện' : 'Chưa luyện'];
    }), 'Không có từ phù hợp.'));
    $('wordStatsPage').textContent = `${rows.length ? state.wordOffset + 1 : 0}–${Math.min(rows.length, state.wordOffset + 20)} / ${rows.length} từ`;
    $('wordStatsPrev').disabled = state.wordOffset === 0; $('wordStatsNext').disabled = state.wordOffset + 20 >= rows.length;
  }
  async function showHistory() {
    const epoch = ++state.historyEpoch;
    note('historyMessage', 'Đang tải kết quả...');
    try {
      await flush();
      const [stats, history] = await Promise.all([api('/api/learning/stats'), api(`/api/learning/history?mode=${$('historyMode').value}&offset=${state.offset}&limit=20`)]);
      if (epoch !== state.historyEpoch) return;
      state.stats = stats; renderStats();
      $('historyTable').replaceChildren(table(['Bắt đầu', 'Chế độ / phạm vi', 'Kết quả', 'Trạng thái', ''], history.items.map(s => {
        const desc = el('div'); desc.append(el('strong', modes[s.mode]), el('div', s.scope_name, 'small-muted'));
        return [date(s.started_at), desc, s.mode === 'flashcard' ? `${s.correct} nhớ · ${s.wrong} chưa nhớ / ${s.total} từ` : `${s.correct} đúng · ${s.wrong} sai / ${s.total} từ`, statuses[s.status], button('Chi tiết', () => showSession(s.id))];
      }), 'Chưa có buổi học trong chế độ này.'));
      $('historyPage').textContent = `${history.total ? state.offset + 1 : 0}–${Math.min(history.total, state.offset + 20)} / ${history.total} buổi`;
      $('historyPrev').disabled = state.offset === 0; $('historyNext').disabled = state.offset + 20 >= history.total;
      note('historyMessage', 'Đã cập nhật kết quả đã lưu.');
    } catch (e) { if (epoch === state.historyEpoch) note('historyMessage', e.message, true); }
  }
  async function showSession(id) {
    try {
      const { item: s, events } = await api(`/api/learning/session/${id}`);
      $('sessionTitle').textContent = `${modes[s.mode]} · ${statuses[s.status]}`;
      $('sessionSummary').textContent = `${s.scope_name} · ${date(s.started_at)} · ${s.total} từ. ${s.mode === 'match' ? 'Mỗi dòng là một từ được chọn; một lần ghép sai có thể liên quan đến hai từ.' : s.mode === 'flashcard' ? 'Kết quả do bạn tự đánh giá.' : 'Đáp án được chấm theo từ đã lưu trong buổi học.'}`;
      $('sessionEvents').replaceChildren(table(['Thời điểm', 'Từ tiếng Anh', 'Nghĩa', 'Bạn đã nhập', 'Kết quả'], events.map(e => [date(e.occurred_at), e.english, e.vietnamese, e.answer || '—', s.mode === 'flashcard' ? (e.correct ? 'Đã nhớ' : 'Chưa nhớ') : e.correct ? 'Đúng' : 'Sai']), 'Buổi này chưa có câu trả lời được ghi nhận.'));
      $('sessionDialog').showModal();
    } catch (e) { note('historyMessage', e.message, true); }
  }
  $('startReviewBtn').addEventListener('click', start); $('retryReviewSave').addEventListener('click', () => drain());
  $('reviewMistakesBtn').addEventListener('click', () => { document.querySelector('[data-view="review"]').click(); $('reviewWrongOnly').checked = true; $('reviewScope').value = 'all'; $('reviewMode').value = 'typing'; start(); });
  $('refreshHistoryBtn').addEventListener('click', showHistory);
  $('historyMode').addEventListener('change', () => { state.offset = 0; showHistory(); });
  $('historyPrev').addEventListener('click', () => { state.offset = Math.max(0, state.offset - 20); showHistory(); });
  $('historyNext').addEventListener('click', () => { state.offset += 20; showHistory(); });
  for (const id of ['wordStatsSearch', 'wordStatsFilter']) $(id).addEventListener(id === 'wordStatsSearch' ? 'input' : 'change', () => { state.wordOffset = 0; renderWords(); });
  $('wordStatsPrev').addEventListener('click', () => { state.wordOffset = Math.max(0, state.wordOffset - 20); renderWords(); });
  $('wordStatsNext').addEventListener('click', () => { state.wordOffset += 20; renderWords(); });
  $('closeSessionBtn').addEventListener('click', () => $('sessionDialog').close());
  document.querySelector('[data-view="history"]').addEventListener('click', showHistory);
  window.addEventListener('learning-updated', () => { state.stats = null; if (!$('historyView').classList.contains('hidden')) { clearTimeout(refreshTimer); refreshTimer = setTimeout(showHistory, 180); } });
  window.addEventListener('vocab-updated', refreshWords);
  window.addEventListener('beforeunload', e => { window.speechSynthesis?.cancel(); if (state.pending !== undefined || state.saving) { e.preventDefault(); e.returnValue = ''; } });
  window.Study = { flush, reload, speak, setBusy(value) { state.busy = value; $('startReviewBtn').disabled = value || !state.ready; } };
  reload().catch(e => { saveLabel('Không kết nối được', true); note('reviewMessage', `${e.message} Hãy thoát rồi mở lại English Match.`, true); });
})();
