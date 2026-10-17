/* Presentation enhancements only. Native inputs remain the source of truth. */
(() => {
  if (window.naritRefinedUI) return;
  window.naritRefinedUI = true;
  const start = () => {
    document.querySelectorAll('link[rel~="icon"]').forEach(icon => {
      icon.type = 'image/svg+xml'; icon.href = '/static/img/narit-fire-emblem.svg?v=2';
    });
    const selects = new Map();
    let opened = null, active = -1, typeBuffer = '', typeTimer;
    const popup = document.createElement('div');
    popup.className = 'ui-select-popup';
    popup.id = 'ui-select-popup';
    popup.role = 'listbox';
    popup.hidden = true;
    document.body.append(popup);

    function close(restoreFocus = false) {
      if (!opened) return;
      const current = opened;
      current.button.setAttribute('aria-expanded', 'false');
      current.button.removeAttribute('aria-activedescendant');
      popup.hidden = true;
      opened = null;
      typeBuffer = '';
      if (restoreFocus && current.button.isConnected) current.button.focus();
    }

    function sync(record) {
      const { select, button, caption } = record;
      caption.textContent = select.selectedOptions[0]?.label || select.options[0]?.label || 'Select';
      button.disabled = select.matches(':disabled');
      record.wrapper.hidden = select.hidden || select.style.display === 'none';
      const labels = [...(select.labels || [])].map(label => label.textContent.trim()).filter(Boolean);
      button.setAttribute('aria-label', select.getAttribute('aria-label') || select.title || labels.join(' ') || select.name || select.id || 'Select option');
      if (select.getAttribute('aria-labelledby')) button.setAttribute('aria-labelledby', select.getAttribute('aria-labelledby'));
      button.title = select.title || caption.textContent;
    }

    function available(index) {
      const option = opened?.select.options[index];
      return option && !option.hidden && !option.disabled && !option.parentElement.disabled;
    }

    function highlight(index) {
      if (!available(index)) return;
      active = index;
      popup.querySelectorAll('[role=option]').forEach(item => item.classList.toggle('is-highlighted', Number(item.dataset.index) === active));
      const item = popup.querySelector(`[data-index="${active}"]`);
      if (item) {
        opened.button.setAttribute('aria-activedescendant', item.id);
        item.scrollIntoView({ block: 'nearest' });
      }
    }

    function move(direction) {
      if (!opened) return;
      const length = opened.select.options.length;
      for (let step = 1; step <= length; step++) {
        const next = (active + direction * step + length) % length;
        if (available(next)) { highlight(next); return; }
      }
    }

    function choose(index) {
      if (opened?.select.matches(':disabled')) { close(); return; }
      if (!available(index)) return;
      const { select } = opened;
      const changed = select.selectedIndex !== index;
      select.selectedIndex = index;
      sync(opened);
      close(true);
      if (changed) {
        select.dispatchEvent(new Event('input', { bubbles: true }));
        select.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }

    function open(record) {
      if (record.select.matches(':disabled')) return;
      close(); sync(record); opened = record;
      popup.replaceChildren();
      popup.setAttribute('aria-label', record.button.getAttribute('aria-label'));
      let lastGroup = null;
      [...record.select.options].forEach((option, index) => {
        if (option.hidden) return;
        const group = option.parentElement.tagName === 'OPTGROUP' ? option.parentElement : null;
        if (group && group !== lastGroup) {
          const title = document.createElement('div');
          title.className = 'ui-select-group'; title.textContent = group.label;
          popup.append(title);
        }
        lastGroup = group;
        const item = document.createElement('div');
        item.className = 'ui-select-option'; item.role = 'option';
        item.id = `ui-option-${index}`; item.dataset.index = String(index);
        item.setAttribute('aria-selected', String(option.selected));
        item.setAttribute('aria-disabled', String(option.disabled || Boolean(group?.disabled)));
        const label = document.createElement('span'), check = document.createElement('span');
        label.textContent = option.label; check.className = 'ui-select-check';
        check.textContent = option.selected ? '✓' : ''; check.setAttribute('aria-hidden', 'true');
        item.append(label, check); popup.append(item);
      });
      // A top-layer dialog needs the popup in that same top layer.
      (record.select.closest('dialog[open]') || document.body).append(popup);
      const rect = record.button.getBoundingClientRect();
      const below = innerHeight - rect.bottom - 12, above = rect.top - 12;
      const upward = below < 180 && above > below;
      const maxHeight = Math.max(45, Math.min(300, upward ? above : below));
      const width = Math.min(innerWidth - 16, Math.max(rect.width, 190));
      popup.style.width = `${width}px`; popup.style.maxHeight = `${maxHeight}px`;
      popup.style.left = `${Math.max(8, Math.min(rect.left, innerWidth - width - 8))}px`;
      popup.hidden = false;
      popup.style.top = `${upward ? Math.max(8, rect.top - popup.offsetHeight - 6) : rect.bottom + 6}px`;
      record.button.setAttribute('aria-expanded', 'true');
      active = record.select.selectedIndex;
      if (!available(active)) { active = -1; move(1); } else highlight(active);
    }

    function installSelect(select) {
      if (select.multiple || select.size > 1 || selects.has(select)) return;
      const wrapper = document.createElement('span'), button = document.createElement('button'), caption = document.createElement('span');
      wrapper.className = 'ui-select'; button.type = 'button'; button.className = 'ui-select-trigger';
      button.role = 'combobox'; button.setAttribute('aria-haspopup', 'listbox');
      button.setAttribute('aria-controls', popup.id); button.setAttribute('aria-expanded', 'false');
      button.innerHTML = '<svg viewBox="0 0 14 14" aria-hidden="true"><path d="m3 5 4 4 4-4"/></svg>';
      button.prepend(caption);
      const record = { select, wrapper, button, caption, tabIndex: select.tabIndex };
      select.before(wrapper); wrapper.append(select, button);
      select.tabIndex = -1; button.tabIndex = record.tabIndex;
      selects.set(select, record); sync(record);
      select.addEventListener('change', () => sync(record));
      select.addEventListener('focus', () => button.focus());
      select.form?.addEventListener('reset', () => setTimeout(() => sync(record)));
      button.addEventListener('click', event => {
        event.preventDefault(); event.stopPropagation();
        if (opened === record) close(); else open(record);
      });
      button.addEventListener('keydown', event => {
        const key = event.key;
        if (key === 'Tab') { close(); return; }
        if (key === 'Escape') { if (opened) { event.preventDefault(); event.stopPropagation(); close(true); } return; }
        if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].includes(key)) {
          event.preventDefault(); event.stopPropagation();
          if (!opened) { open(record); return; }
          if (key === 'Enter' || key === ' ') { choose(active); return; }
          if (key === 'ArrowDown' || key === 'ArrowUp') move(key === 'ArrowDown' ? 1 : -1);
          else { active = key === 'Home' ? -1 : 0; move(key === 'Home' ? 1 : -1); }
        } else if (key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
          event.preventDefault(); if (!opened) open(record);
          clearTimeout(typeTimer); typeBuffer += key.toLowerCase();
          const index = [...select.options].findIndex((option, index) => available(index) && option.label.toLowerCase().startsWith(typeBuffer));
          if (index >= 0) highlight(index);
          typeTimer = setTimeout(() => typeBuffer = '', 650);
        }
      });
    }
    popup.addEventListener('pointerdown', event => event.preventDefault());
    popup.addEventListener('click', event => {
      event.stopPropagation(); const option = event.target.closest('[role=option]');
      if (option) choose(Number(option.dataset.index));
    });
    popup.addEventListener('pointermove', event => {
      const option = event.target.closest('[role=option]');
      if (option) highlight(Number(option.dataset.index));
    });
    document.addEventListener('pointerdown', event => {
      if (opened && !popup.contains(event.target) && !opened.wrapper.contains(event.target)) close();
    });
    window.addEventListener('resize', () => close());
    window.addEventListener('scroll', event => { if (opened && !popup.contains(event.target)) close(); }, true);

    function installLog() {
      const panel = document.getElementById('event-log');
      if (!panel || panel.querySelector('.system-log-collapse')) return;
      // Mobile already supplies a working accordion that releases its layout.
      if (document.documentElement.classList.contains('mobile-browser')) return;
      const header = panel.querySelector('.system-log-header'), tools = panel.querySelector('.system-log-tools');
      if (!header || !tools) return;
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'system-log-collapse';
      button.id = 'systemLogCollapse'; button.setAttribute('aria-controls', 'systemLogEntries');
      button.innerHTML = '<svg viewBox="0 0 14 14" aria-hidden="true"><path d="m3 9 4-4 4 4"/></svg><span>Collapse</span>';
      tools.append(button);
      let collapsed = false;
      try { collapsed = localStorage.getItem('narit.eventLog.collapsed') === 'true'; } catch (_) {}
      function apply(notify = true) {
        panel.classList.toggle('is-ui-collapsed', collapsed);
        document.body.classList.toggle('is-log-collapsed', collapsed);
        button.setAttribute('aria-expanded', String(!collapsed));
        button.querySelector('span').textContent = collapsed ? 'Expand' : 'Collapse';
        button.setAttribute('aria-label', `${collapsed ? 'Expand' : 'Collapse'} Event Log`);
        // Existing chart and terrain renderers listen for resize.
        if (notify) requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
      }
      function toggle() { collapsed = !collapsed; try { localStorage.setItem('narit.eventLog.collapsed', String(collapsed)); } catch (_) {} apply(); }
      button.addEventListener('click', toggle);
      header.addEventListener('click', event => { if (!event.target.closest('button, select, label, .ui-select')) toggle(); });
      apply(false);
    }

    function enhance(root) {
      if (root.nodeType !== 1 && root !== document) return;
      const candidates = root.matches?.('select') ? [root] : root.querySelectorAll('select');
      candidates.forEach(installSelect);
      const images = root.matches?.('img') ? [root] : root.querySelectorAll('img');
      images.forEach(img => {
        if (img.getAttribute('src')?.includes('narit-smart-wildfire-mark.png')) img.src = '/static/img/narit-fire-emblem.svg?v=2';
      });
    }
    enhance(document); installLog();
    new MutationObserver(mutations => {
      mutations.forEach(mutation => mutation.addedNodes.forEach(node => enhance(node)));
      // Prune removed selects so detached dialogs do not accumulate.
      for (const [select, record] of selects) if (!select.isConnected) { if (opened === record) close(); selects.delete(select); }
    }).observe(document.body, { childList: true, subtree: true });
    // Live telemetry sets select.value and disabled directly, without events.
    setInterval(() => {
      if (document.hidden) return;
      for (const record of selects.values()) {
        const text = record.select.selectedOptions[0]?.label || record.select.options[0]?.label || 'Select';
        if (text !== record.caption.textContent || record.button.disabled !== record.select.matches(':disabled')
          || record.wrapper.hidden !== (record.select.hidden || record.select.style.display === 'none')) sync(record);
      }
      if (opened && opened.button.disabled) close();
    }, 350);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
