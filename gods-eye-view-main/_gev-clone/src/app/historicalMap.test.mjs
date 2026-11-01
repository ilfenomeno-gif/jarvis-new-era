import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createHistoricalMap,
  nearestHistoricalYear,
  parseHistoricalIndex,
} from './historicalMap.js';

const index = {
  years: [
    { year: 1930, filename: 'world_1930.geojson', countries: ['Luxembourg'] },
    { year: 1938, filename: 'world_1938.geojson', countries: ['Luxembourg'] },
    { year: 1945, filename: 'world_1945.geojson', countries: ['Luxembourg'] },
  ],
};
const featureCollection = {
  type: 'FeatureCollection',
  features: [
    { type: 'Feature', properties: { NAME: 'Luxembourg' }, geometry: {} },
    {
      type: 'Feature',
      properties: { NAME: null, SUBJECTO: null },
      geometry: {},
    },
  ],
};

function fixture(responses = [index, featureCollection], options = {}) {
  const calls = [];
  const sources = [];
  const removed = [];
  const timers = [];
  const loadedGeojson = [];
  const cache = new Map();
  const fetchImpl = async (url, options) => {
    calls.push([url, options]);
    const body = responses.shift();
    if (body instanceof Error) throw body;
    return {
      ok: body?.ok !== false,
      status: body?.status ?? 200,
      url,
      text: async () => JSON.stringify(body?.body ?? body),
    };
  };
  const color = {
    withAlpha(alpha) {
      return { alpha };
    },
  };
  class CallbackProperty {
    constructor(callback, isConstant) {
      this.callback = callback;
      this.isConstant = isConstant;
    }

    getValue(time) {
      return this.callback(time);
    }
  }
  class CustomDataSource {
    constructor(name) {
      this.name = name;
      sources.push(this);
      this.entities = {
        values: [],
        add: (entity) => {
          this.entities.values.push(entity);
          return entity;
        },
      };
    }
  }
  const CesiumEngine = {
    Color: {
      WHITE: color,
      fromCssColorString(css) {
        return { css };
      },
      fromHsl(hue, saturation, lightness, alpha) {
        return {
          hue,
          saturation,
          lightness,
          alpha,
          withAlpha: (value) => ({ hue, alpha: value }),
        };
      },
    },
    JulianDate: {
      now: () => new Date('1939-01-01T00:00:00Z'),
      toDate: (date) => date,
      fromDate: (date) => date,
      clone: (date) => new Date(date),
    },
    ClockRange: { CLAMPED: 1 },
    ColorMaterialProperty: class {
      constructor(colorProperty) {
        this.color = colorProperty;
      }
    },
    CallbackProperty,
    CustomDataSource,
    PointGraphics: class {
      constructor(options) {
        Object.assign(this, options);
      }
    },
    Cartesian3: {
      fromDegrees: (longitude, latitude) => ({ longitude, latitude }),
    },
    TimeInterval: class {
      constructor(options) {
        Object.assign(this, options);
      }
    },
    TimeIntervalCollectionProperty: class {
      constructor() {
        this.intervals = {
          values: [],
          addInterval: (interval) => this.intervals.values.push(interval),
        };
      }

      getValue(time) {
        return this.intervals.values.some(
          (interval) =>
            time >= interval.start && time < interval.stop && interval.data,
        );
      }
    },
    GeoJsonDataSource: {
      async load(geojson) {
        loadedGeojson.push(geojson);
        const source = {
          entities: {
            values: geojson.features.map((feature, index) => ({
              id: feature.properties?.NAME ?? `entity-${index}`,
              polygon: {},
              properties: { getValue: () => feature.properties ?? {} },
            })),
          },
        };
        sources.push(source);
        return source;
      },
    },
  };
  const clockListeners = new Set();
  const clock = {
    currentTime: new Date('1939-01-01T00:00:00Z'),
    stopTime: new Date('1940-01-01T00:00:00Z'),
    multiplier: 1,
    clockRange: 0,
    shouldAnimate: false,
    onTick: {
      addEventListener(listener) {
        clockListeners.add(listener);
        return () => clockListeners.delete(listener);
      },
    },
  };
  const viewer = {
    clock,
    dataSources: {
      async add(source) {
        source.added = true;
      },
      remove(source) {
        removed.push(source);
        return true;
      },
    },
  };
  const historicalMap = createHistoricalMap({
    viewer,
    fetchImpl,
    CesiumEngine,
    ...options,
    snapshotCache: options.snapshotCache ?? {
      async get(key) {
        return cache.get(key) ?? null;
      },
      async set(key, value) {
        cache.set(key, value);
      },
    },
    setIntervalImpl(callback, delay) {
      const timer = { callback, delay };
      timers.push(timer);
      return timer;
    },
    clearIntervalImpl(timer) {
      timer.cleared = true;
    },
  });
  return {
    cache,
    calls,
    historicalMap,
    loadedGeojson,
    removed,
    sources,
    timers,
    async tickClock(year) {
      clock.currentTime = new Date(`${year}-01-01T00:00:00Z`);
      await Promise.all([...clockListeners].map((listener) => listener(clock)));
    },
    viewer,
  };
}

test('nearest snapshot is selected deterministically from verified available years', () => {
  assert.deepEqual(nearestHistoricalYear(1939, index.years), {
    year: 1938,
    filename: 'world_1938.geojson',
    countries: ['Luxembourg'],
  });
  assert.deepEqual(nearestHistoricalYear(1941, index.years), {
    year: 1938,
    filename: 'world_1938.geojson',
    countries: ['Luxembourg'],
  });
});

test('index accepts every valid year and the upstream BCE filename convention', () => {
  const years = parseHistoricalIndex({
    years: [
      { year: -123000, filename: 'world_bc123000.geojson', countries: ['A'] },
      { year: 1941, filename: 'world_1941.geojson', countries: ['B'] },
      { year: 1942, filename: 'world_1942.geojson' },
    ],
  });
  assert.deepEqual(
    years.map(({ year }) => year),
    [-123000, 1941],
  );
});

test('listYears returns every accepted year in sorted order', async () => {
  const { historicalMap } = fixture();
  assert.deepEqual(await historicalMap.listYears(), [1930, 1938, 1945]);
  historicalMap.destroy();
});

test('embedded year-list messages return correlated postMessage responses', async () => {
  const windowRef = new EventTarget();
  const replies = [];
  windowRef.parent = windowRef;
  windowRef.GEV_EMBED_INLINE = true;
  windowRef.postMessage = (message, targetOrigin) =>
    replies.push({ message, targetOrigin });
  const { historicalMap } = fixture([index], { windowRef });
  const request = new Event('message');
  Object.defineProperties(request, {
    source: { value: windowRef },
    origin: { value: 'null' },
    data: {
      value: { type: 'gev:historical-years', id: 'jarvis-test-1' },
    },
  });
  windowRef.dispatchEvent(request);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(replies.length, 1);
  assert.equal(replies[0].targetOrigin, '*');
  assert.deepEqual(replies[0].message, {
    type: 'gev:historical-years-applied',
    id: 'jarvis-test-1',
    ok: true,
    result: [1930, 1938, 1945],
  });
  historicalMap.destroy();
});

test('offline index uses the bundled fallback and cached GeoJSON', async () => {
  const localIndex = { years: index.years };
  const { historicalMap, loadedGeojson } = fixture(
    [new Error('network unavailable'), new Error('network unavailable')],
    {
      indexFallback: localIndex,
      snapshotCache: {
        async get() {
          return featureCollection;
        },
        async set() {
          throw new Error('cache write should not be needed');
        },
      },
    },
  );
  assert.deepEqual(await historicalMap.listYears(), [1930, 1938, 1945]);
  const result = await historicalMap.execute({ command: 'show', year: 1939 });
  assert.equal(result.year, 1938);
  assert.equal(loadedGeojson.length, 1);
  historicalMap.destroy();
});

test('show loads and styles the nearest real snapshot', async () => {
  const { calls, historicalMap, loadedGeojson, sources } = fixture();
  const result = await historicalMap.execute({ command: 'show', year: 1939 });
  assert.equal(result.year, 1938);
  assert.equal(result.filename, 'world_1938.geojson');
  assert.equal(result.entityCount, 1);
  assert.equal(loadedGeojson[0].features.length, 1);
  assert.equal(calls[1][0].endsWith('/world_1938.geojson'), true);
  assert.equal(sources[0].added, true);
  assert.equal(sources[0].entities.values[0].polygon.outline, false);
  historicalMap.destroy();
});

test('failed replacement keeps the currently visible historical data source', async () => {
  const { historicalMap, removed, sources } = fixture(
    [index, featureCollection, { ok: false, status: 503, body: {} }],
    {
      snapshotCache: {
        async get() {
          return null;
        },
        async set() {},
      },
    },
  );
  await historicalMap.execute({ command: 'show', year: 1938 });
  await assert.rejects(
    historicalMap.execute({ command: 'show', year: 1945 }),
    (error) => {
      assert.match(error.message, /unavailable remotely and in local cache/);
      assert.match(error.cause.message, /request failed \(503\)/);
      return true;
    },
  );
  assert.deepEqual(removed, []);
  assert.equal(sources.length, 1);
  historicalMap.destroy();
  assert.deepEqual(removed, [sources[0]]);
});

test('WWII playback reports discrete snapshots rather than continuous yearly data', async () => {
  const { historicalMap, removed, sources, timers } = fixture([
    index,
    featureCollection,
    featureCollection,
  ]);
  const result = await historicalMap.execute({
    command: 'animate',
    start_year: 1939,
    end_year: 1945,
    speed: 1,
  });
  assert.deepEqual(result.snapshots, [1938, 1945]);
  assert.equal(result.currentYear, 1938);
  assert.equal(result.playing, true);
  assert.equal(timers[0].delay, 1000);
  await timers[0].callback();
  assert.equal(sources.length, 2);
  assert.deepEqual(removed, [sources[0]]);
  await historicalMap.execute({ command: 'stop' });
  assert.equal(timers[0].cleared, true);
  historicalMap.destroy();
});

test('invalid commands and out-of-range playback speed are explicit errors', async () => {
  const { historicalMap } = fixture();
  await assert.rejects(
    historicalMap.execute({ command: 'show', year: '1938' }),
    /year must be an integer/,
  );
  await assert.rejects(
    historicalMap.execute({
      command: 'animate',
      start_year: 1938,
      end_year: 1945,
      speed: 0.1,
    }),
    /speed must be between/,
  );
  await assert.rejects(
    historicalMap.execute({ command: 'unknown' }),
    /Unsupported historical map command/,
  );
  historicalMap.destroy();
});

test('playback reports fetch errors and stops rather than rejecting from a timer', async () => {
  const errors = [];
  const { historicalMap, timers, sources } = fixture(
    [index, featureCollection, { ok: false, status: 503, body: {} }],
    {
      onPlaybackError: (error) => errors.push(error),
      snapshotCache: {
        async get() {
          return null;
        },
        async set() {},
      },
    },
  );
  await historicalMap.execute({
    command: 'animate',
    start_year: 1939,
    end_year: 1945,
    speed: 1,
  });
  await timers[0].callback();
  assert.match(errors[0].cause.message, /request failed \(503\)/);
  assert.equal(timers[0].cleared, true);
  assert.equal(sources.length, 1);
  historicalMap.destroy();
});

test('faction materials follow scenario year anchors as the Cesium clock advances', async () => {
  const { historicalMap, sources, viewer } = fixture(
    [index, featureCollection],
    {
      factions: {
        scenarios: {
          ww2: {
            name: 'WWII',
            start_year: 1939,
            end_year: 1945,
            factions_by_year: {
              1939: { Luxembourg: 'axis' },
              1945: { Luxembourg: 'allies' },
            },
          },
        },
      },
    },
  );
  await historicalMap.execute({ command: 'show', year: 1939 });
  const result = historicalMap.applyFactions('ww2', 1939);
  assert.equal(result.counts.axis, 1);
  const material = sources[0].entities.values[0].polygon.material;
  assert.equal(material.color.isConstant, false);
  assert.equal(
    material.color.getValue(viewer.clock.currentTime).css,
    '#B22222',
  );
  viewer.clock.currentTime = new Date('1945-01-01T00:00:00Z');
  assert.equal(
    material.color.getValue(viewer.clock.currentTime).css,
    '#1E90FF',
  );
  historicalMap.destroy();
});

test('scenario load applies factions, loads timed events, and starts the clock', async () => {
  const { historicalMap, sources, tickClock, viewer } = fixture(
    [index, featureCollection, featureCollection],
    {
      factions: {
        scenarios: {
          ww2: {
            name: 'WWII',
            start_year: 1939,
            end_year: 1945,
            factions_by_year: { 1939: { Luxembourg: 'axis' } },
          },
        },
      },
      events: {
        events: [
          {
            id: 'test-event',
            name: 'Test event',
            year: 1941,
            month: 12,
            day: 31,
            lat: 49,
            lon: 2,
            type: 'battle',
            belligerents: ['allies', 'axis'],
            scenario: 'ww2',
          },
        ],
      },
    },
  );
  const result = await historicalMap.loadScenario('ww2', 1941);
  assert.equal(result.year, 1941);
  assert.equal(result.map.year, 1938);
  assert.equal(result.factions.counts.axis, 1);
  assert.equal(result.events.count, 1);
  assert.equal(viewer.clock.currentTime.getUTCFullYear(), 1941);
  assert.equal(viewer.clock.stopTime.getUTCFullYear(), 1946);
  assert.equal(viewer.clock.multiplier, (365.2425 * 24 * 60 * 60) / 20);
  assert.equal(viewer.clock.shouldAnimate, true);
  const eventSource = sources.find(
    (source) => source.name === 'historical-events',
  );
  const event = eventSource.entities.values[0];
  assert.equal(
    event.point.show.getValue(new Date('1941-12-31T12:00:00Z')),
    true,
  );
  assert.equal(
    event.point.show.getValue(new Date('1942-01-01T00:00:00Z')),
    false,
  );
  await tickClock(1942);
  assert.equal(sources[0].name, 'Historical borders 1938');
  assert.equal(sources[2].name, 'Historical borders 1945');
  await tickClock(1946);
  assert.equal(viewer.clock.shouldAnimate, false);
  await historicalMap.execute({ command: 'stop' });
  assert.equal(viewer.clock.shouldAnimate, false);
  await historicalMap.execute({ command: 'clear' });
  assert.equal(viewer.clock.currentTime.getUTCFullYear(), 1939);
  assert.equal(viewer.clock.multiplier, 1);
  assert.equal(viewer.clock.clockRange, 0);
  assert.equal(viewer.clock.stopTime.getUTCFullYear(), 1940);
  historicalMap.destroy();
});
