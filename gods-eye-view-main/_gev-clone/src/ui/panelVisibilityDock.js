const PANEL_VISIBILITY_STORAGE_KEY = 'godsEyeView.v1.hiddenPanels';

export const PANEL_VISIBILITY_SPECS = Object.freeze([
  { id: 'control-panel', label: 'Navigation controls' },
  { id: 'location-bar', label: 'Location' },
  { id: 'data-panel', label: 'Data Layers' },
  { id: 'cctv-panel', label: 'CCTV' },
  { id: 'scene-panel', label: 'Scenes' },
  { id: 'pp-toggles', label: 'Display' },
  { id: 'param-slider-panel', label: 'Display parameters' },
  { id: 'global-context-panel', label: 'Context' },
  { id: 'radio-panel', label: 'Radio' },
  { id: 'weather-panel', label: 'Weather' },
  { id: 'recent-imagery-panel', label: 'Recent imagery' },
]);

const PANEL_VISIBILITY_PARENTS = Object.freeze({
  'param-slider-panel': 'pp-toggles',
  'radio-panel': 'global-context-panel',
});

export class PanelVisibilityDock {
  constructor({ documentRef, onChange = () => {} }) {
    this.document = documentRef;
    this.onChange = onChange;
    this.hiddenPanelIds = new Set();
    this.buttons = new Map();
    this.removers = [];
    this.storage = null;
    try {
      this.storage = documentRef.defaultView?.localStorage || null;
    } catch {
      // Storage can be unavailable in restricted browser contexts.
    }
  }

  init() {
    const dock = this.document.getElementById('panel-visibility-dock');
    if (!dock) return;
    dock.replaceChildren();

    try {
      const saved = JSON.parse(
        this.storage?.getItem(PANEL_VISIBILITY_STORAGE_KEY) || '[]',
      );
      if (Array.isArray(saved)) {
        this.hiddenPanelIds = new Set(
          saved.filter((id) =>
            PANEL_VISIBILITY_SPECS.some((spec) => spec.id === id),
          ),
        );
      }
    } catch {
      this.hiddenPanelIds.clear();
    }

    for (const spec of PANEL_VISIBILITY_SPECS) {
      const panel = this.document.getElementById(spec.id);
      if (!panel) continue;

      const button = this.document.createElement('button');
      button.type = 'button';
      button.className = 'panel-visibility-dot';
      button.dataset.panelVisibilityTarget = spec.id;
      const onClick = (event) => {
        event.stopPropagation();
        this.setHidden(spec.id, !this.hiddenPanelIds.has(spec.id));
      };
      button.addEventListener('click', onClick);
      this.removers.push(() => button.removeEventListener('click', onClick));
      dock.append(button);
      this.buttons.set(spec.id, button);
      this._syncPanel(spec.id);
    }
  }

  setHidden(panelId, hidden, { persist = true } = {}) {
    const panel = this.document.getElementById(panelId);
    if (!panel || !this.buttons.has(panelId)) return false;

    if (!hidden) {
      const parentId = PANEL_VISIBILITY_PARENTS[panelId];
      if (parentId && this.hiddenPanelIds.has(parentId))
        this.setHidden(parentId, false, { persist: false });
    }

    if (hidden) this.hiddenPanelIds.add(panelId);
    else this.hiddenPanelIds.delete(panelId);
    panel.classList.toggle('panel-dot-hidden', hidden);
    this._syncPanel(panelId);
    if (persist) this._persist();
    this.onChange(panel);
    return true;
  }

  _syncPanel(panelId) {
    const panel = this.document.getElementById(panelId);
    const button = this.buttons.get(panelId);
    if (!panel || !button) return;
    const visible = !this.hiddenPanelIds.has(panelId);
    panel.classList.toggle('panel-dot-hidden', !visible);
    button.textContent = visible ? '●' : '○';
    button.title = `${visible ? 'Hide' : 'Show'} ${this._label(panelId)} panel`;
    button.setAttribute('aria-label', button.title);
    button.setAttribute('aria-pressed', String(visible));
  }

  _label(panelId) {
    const panel = this.document.getElementById(panelId);
    return (
      panel
        ?.querySelector(
          '.panel-title, .pp-header-label, .location-toolbar-label',
        )
        ?.textContent?.trim() ||
      PANEL_VISIBILITY_SPECS.find((spec) => spec.id === panelId)?.label ||
      'Unknown'
    );
  }

  _persist() {
    try {
      this.storage?.setItem(
        PANEL_VISIBILITY_STORAGE_KEY,
        JSON.stringify([...this.hiddenPanelIds]),
      );
    } catch {
      // Keep the in-session controls usable when storage is unavailable.
    }
  }

  destroy() {
    for (const remove of this.removers) remove();
    this.removers = [];
    this.buttons.clear();
  }
}
