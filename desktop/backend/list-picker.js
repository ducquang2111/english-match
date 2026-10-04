'use strict';
(() => {
  const instances = new Map();
  const ids = scope => scope === 'all' ? null : String(scope || '').split(',').filter(Boolean);
  const includes = (scope, id) => scope === 'all' || ids(scope).includes(String(id));
  const valid = (scope, lists) => scope === 'all' || (ids(scope).length > 0 && ids(scope).every(id => lists.some(l => String(l.id) === id)));
  const name = (scope, lists) => {
    if (scope === 'all') return 'Tất cả list';
    const selected = lists.filter(l => includes(scope, l.id));
    if (!selected.length) return 'Chưa chọn list';
    const names = selected.map(l => l.name).join(', ');
    return (selected.length > 1 ? `${selected.length} list: ` : '') + (names.length > 160 ? names.slice(0, 157) + '…' : names);
  };
  const element = (tag, text, cls) => { const e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; };
  class Picker {
    constructor(select) {
      this.select = select; this.lists = []; this.scope = 'all';
      this.root = element('details', '', 'list-picker');
      this.summary = element('summary', 'Tất cả list', 'select');
      this.summary.setAttribute('aria-label', select.getAttribute('aria-label') || document.querySelector(`label[for="${select.id}"]`)?.textContent || 'Chọn list');
      this.panel = element('div', '', 'list-picker-panel');
      this.search = element('input', '', 'input'); this.search.type = 'search'; this.search.placeholder = 'Tìm list…'; this.search.setAttribute('aria-label', 'Tìm list');
      const actions = element('div', '', 'row-actions');
      for (const [label, fn] of [['Chọn tất cả', () => { this.all = true; this.draft = new Set(this.lists.map(l => String(l.id))); this.renderOptions(); }], ['Bỏ chọn', () => { this.all = false; this.draft.clear(); this.renderOptions(); }]]) {
        const b = element('button', label, 'text-btn'); b.type = 'button'; b.addEventListener('click', fn); actions.append(b);
      }
      this.options = element('div', '', 'list-picker-options'); this.options.setAttribute('role', 'group'); this.options.setAttribute('aria-label', 'Các list');
      this.status = element('p', '', 'help'); this.status.setAttribute('role', 'status');
      const footer = element('div', '', 'row-actions');
      const apply = element('button', 'Áp dụng', 'btn blue'); apply.type = 'button';
      apply.addEventListener('click', () => {
        if (!this.draft.size) { this.status.textContent = 'Hãy chọn ít nhất một list.'; return; }
        const value = this.all ? 'all' : [...this.draft].sort((a, b) => Number(a) - Number(b)).join(',');
        this.set(value); this.select.dispatchEvent(new Event('change', { bubbles: true }));
        this.set(this.select.value); this.root.open = false; this.summary.focus();
      });
      const cancel = element('button', 'Hủy', 'btn secondary'); cancel.type = 'button'; cancel.addEventListener('click', () => { this.root.open = false; this.summary.focus(); });
      footer.append(apply, cancel); this.panel.append(this.search, actions, this.options, this.status, footer); this.root.append(this.summary, this.panel);
      select.hidden = true; select.after(this.root);
      this.root.addEventListener('toggle', () => {
        if (!this.root.open) return;
        for (const p of instances.values()) if (p !== this) p.root.open = false;
        this.all = this.select.value === 'all';
        this.draft = new Set(this.lists.filter(l => includes(this.select.value, l.id)).map(l => String(l.id)));
        this.search.value = ''; this.renderOptions(); this.search.focus();
      });
      this.search.addEventListener('input', () => this.renderOptions());
      this.root.addEventListener('keydown', e => { if (e.key === 'Escape') { this.root.open = false; this.summary.focus(); e.preventDefault(); } });
      select.addEventListener('change', () => this.set(select.value));
    }
    renderOptions() {
      this.options.replaceChildren();
      const q = this.search.value.trim().toLocaleLowerCase();
      for (const l of this.lists.filter(l => l.name.toLocaleLowerCase().includes(q))) {
        const label = element('label', '', 'list-picker-option'), input = element('input'); input.type = 'checkbox'; input.value = String(l.id); input.checked = this.draft.has(input.value);
        input.addEventListener('change', () => { this.all = false; input.checked ? this.draft.add(input.value) : this.draft.delete(input.value); this.updateCount(); });
        label.append(input, element('span', `${l.name} (${l.word_count} từ)`)); this.options.append(label);
      }
      if (!this.options.children.length) this.options.append(element('p', 'Không tìm thấy list.', 'help'));
      this.updateCount();
    }
    updateCount() { this.status.textContent = this.all ? `Tất cả ${this.lists.length} list (bao gồm list mới thêm sau này).` : `Đã chọn ${this.draft.size} / ${this.lists.length} list.`; }
    set(scope) {
      this.scope = scope;
      this.select.replaceChildren(new Option('Tất cả list', 'all'));
      this.lists.forEach(l => this.select.add(new Option(l.name, String(l.id))));
      if (![...this.select.options].some(o => o.value === scope)) this.select.add(new Option(name(scope, this.lists), scope));
      this.select.value = scope; this.summary.textContent = name(scope, this.lists);
      this.summary.title = this.lists.filter(l => includes(scope, l.id)).map(l => l.name).join(', ');
    }
    update(lists) {
      this.lists = lists;
      const scope = this.select.options.length ? this.select.value : this.scope;
      this.set(scope === 'all' ? 'all' : ids(scope).filter(id => lists.some(l => String(l.id) === id)).join(','));
      this.root.open = false;
    }
  }
  window.ListScope = { ids, includes, valid, name,
    update(id, lists) { if (!instances.has(id)) instances.set(id, new Picker(document.getElementById(id))); instances.get(id).update(lists); },
    set(id, scope) { instances.get(id)?.set(scope); }
  };
  const part = word => (word?.part_of_speech || '').trim().replace(/^\((.*)\)$/u, '$1').trim();
  window.WordDisplay = { part, english: word => word.english + (part(word) ? ` (${part(word)})` : '') };
})();
