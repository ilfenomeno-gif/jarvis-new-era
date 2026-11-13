import assert from 'node:assert/strict';
import test from 'node:test';
import {
  PANEL_VISIBILITY_SPECS,
  PanelVisibilityDock,
} from './panelVisibilityDock.js';

test('panel dots restore saved visibility and persist independent toggles', () => {
  const f = fixture({ hidden: ['cctv-panel'] });
  const dock = new PanelVisibilityDock({ documentRef: f.document });
  dock.init();

  assert.equal(f.dock.children.length, PANEL_VISIBILITY_SPECS.length);
  assert.equal(
    f.panels.get('cctv-panel').classList.contains('panel-dot-hidden'),
    true,
  );
  assert.equal(f.buttons.get('cctv-panel').textContent, '○');
  assert.equal(
    f.buttons.get('cctv-panel').getAttribute('aria-pressed'),
    'false',
  );

  let stopped = false;
  f.buttons.get('data-panel').click({
    stopPropagation() {
      stopped = true;
    },
  });
  assert.equal(stopped, true);
  assert.equal(
    f.panels.get('data-panel').classList.contains('panel-dot-hidden'),
    true,
  );
  assert.equal(f.buttons.get('data-panel').textContent, '○');
  assert.deepEqual(
    JSON.parse(f.storage.getItem('godsEyeView.v1.hiddenPanels')),
    ['cctv-panel', 'data-panel'],
  );

  f.buttons.get('data-panel').click({ stopPropagation() {} });
  assert.equal(
    f.panels.get('data-panel').classList.contains('panel-dot-hidden'),
    false,
  );
  assert.equal(
    f.buttons.get('data-panel').getAttribute('aria-pressed'),
    'true',
  );
  assert.deepEqual(
    JSON.parse(f.storage.getItem('godsEyeView.v1.hiddenPanels')),
    ['cctv-panel'],
  );
  dock.destroy();
});

test('restoring a nested panel also restores its hidden parent', () => {
  const f = fixture({
    hidden: [
      'global-context-panel',
      'radio-panel',
      'pp-toggles',
      'param-slider-panel',
    ],
  });
  const dock = new PanelVisibilityDock({ documentRef: f.document });
  dock.init();

  f.buttons.get('radio-panel').click({ stopPropagation() {} });
  assert.equal(
    f.panels.get('global-context-panel').classList.contains('panel-dot-hidden'),
    false,
  );
  assert.equal(
    f.panels.get('radio-panel').classList.contains('panel-dot-hidden'),
    false,
  );
  assert.equal(
    f.panels.get('pp-toggles').classList.contains('panel-dot-hidden'),
    true,
  );

  f.buttons.get('param-slider-panel').click({ stopPropagation() {} });
  assert.equal(
    f.panels.get('pp-toggles').classList.contains('panel-dot-hidden'),
    false,
  );
  dock.destroy();
});

test('invalid saved visibility data is ignored and unavailable panels are skipped', () => {
  const f = fixture({ raw: '{invalid', missing: ['weather-panel'] });
  const dock = new PanelVisibilityDock({ documentRef: f.document });
  dock.init();

  assert.equal(f.buttons.has('weather-panel'), false);
  assert.equal(
    f.panels.get('data-panel').classList.contains('panel-dot-hidden'),
    false,
  );
  assert.doesNotThrow(() => dock.setHidden('unknown-panel', true));
  dock.destroy();
});

function fixture({ hidden = [], raw, missing = [] } = {}) {
  const storage = new FakeStorage();
  if (raw !== undefined) storage.setItem('godsEyeView.v1.hiddenPanels', raw);
  else storage.setItem('godsEyeView.v1.hiddenPanels', JSON.stringify(hidden));

  const dock = new FakeElement('panel-visibility-dock');
  const panels = new Map(
    PANEL_VISIBILITY_SPECS.filter((spec) => !missing.includes(spec.id)).map(
      (spec) => [spec.id, new FakeElement(spec.id)],
    ),
  );
  const document = {
    defaultView: { localStorage: storage },
    getElementById(id) {
      return id === 'panel-visibility-dock' ? dock : panels.get(id) || null;
    },
    createElement() {
      return new FakeElement('');
    },
  };
  return {
    document,
    dock,
    panels,
    storage,
    get buttons() {
      return new Map(
        dock.children.map((button) => [
          button.dataset.panelVisibilityTarget,
          button,
        ]),
      );
    },
  };
}

class FakeElement {
  constructor(id) {
    this.id = id;
    this.children = [];
    this.dataset = {};
    this.textContent = '';
    this.attributes = new Map();
    this.listeners = new Map();
    this.classes = new Set();
    this.classList = {
      add: (value) => this.classes.add(value),
      contains: (value) => this.classes.has(value),
      toggle: (value, force) => {
        const shouldAdd = force ?? !this.classes.has(value);
        if (shouldAdd) this.classes.add(value);
        else this.classes.delete(value);
        return shouldAdd;
      },
    };
  }

  append(child) {
    this.children.push(child);
  }

  replaceChildren(...children) {
    this.children = children;
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  removeEventListener(type, listener) {
    if (this.listeners.get(type) === listener) this.listeners.delete(type);
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  getAttribute(name) {
    return this.attributes.get(name);
  }

  querySelector() {
    return { textContent: this.id.replaceAll('-', ' ') };
  }

  click(event) {
    this.listeners.get('click')?.(event);
  }
}

class FakeStorage {
  values = new Map();

  getItem(key) {
    return this.values.get(key) ?? null;
  }

  setItem(key, value) {
    this.values.set(key, value);
  }
}
