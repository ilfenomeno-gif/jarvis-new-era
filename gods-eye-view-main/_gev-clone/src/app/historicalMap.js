import * as Cesium from 'cesium';
import eventsFallback from '../../data/events.json' with { type: 'json' };
import indexFallback from '../../data/historical-index-fallback.json' with { type: 'json' };
import factionsFallback from '../../data/factions.json' with { type: 'json' };

export const HISTORICAL_INDEX_URL =
  'https://raw.githubusercontent.com/aourednik/historical-basemaps/master/index.json';
const HISTORICAL_GEOJSON_ROOT =
  'https://raw.githubusercontent.com/aourednik/historical-basemaps/master/geojson/';
const MAX_GEOJSON_CHARS = 20_000_000;
const SNAPSHOT_DB_NAME = 'gev-historical-snapshots';
const SNAPSHOT_DB_VERSION = 1;
const SNAPSHOT_STORE = 'geojson';
const JULIAN_YEAR_SECONDS = 365.2425 * 24 * 60 * 60;
const SCENARIO_SECONDS_PER_YEAR = 20;

export const HISTORICAL_FACTION_COLORS = Object.freeze({
  axis: '#B22222',
  allies: '#1E90FF',
  neutral: '#808080',
  comintern: '#8B0000',
  nato: '#00008B',
  warsaw_pact: '#DC143C',
});
const HISTORICAL_FACTIONS = new Set(Object.keys(HISTORICAL_FACTION_COLORS));

function validateFactionScenarios(scenarios) {
  for (const [scenarioName, scenario] of Object.entries(scenarios)) {
    if (
      typeof scenario.name !== 'string' ||
      !Number.isSafeInteger(scenario.start_year) ||
      !Number.isSafeInteger(scenario.end_year) ||
      scenario.start_year > scenario.end_year ||
      !scenario.factions_by_year ||
      typeof scenario.factions_by_year !== 'object' ||
      Array.isArray(scenario.factions_by_year)
    ) {
      throw new Error(`Invalid historical scenario: ${scenarioName}`);
    }
    for (const [year, entities] of Object.entries(scenario.factions_by_year)) {
      if (
        !Number.isSafeInteger(Number(year)) ||
        !entities ||
        typeof entities !== 'object' ||
        Array.isArray(entities)
      ) {
        throw new Error(
          `Invalid faction mapping year ${year} in scenario ${scenarioName}`,
        );
      }
      for (const [entity, faction] of Object.entries(entities)) {
        if (!entity.trim() || !HISTORICAL_FACTIONS.has(faction)) {
          throw new Error(
            `Invalid faction mapping for ${entity} in scenario ${scenarioName}`,
          );
        }
      }
    }
  }
}

function checkedJsonResponse(response, url, maxChars = MAX_GEOJSON_CHARS) {
  if (!response?.ok) {
    throw new Error(
      `Historical data request failed (${response?.status ?? 'unknown'}): ${url}`,
    );
  }
  if (response.url) {
    const actual = new URL(response.url);
    if (actual.origin !== 'https://raw.githubusercontent.com') {
      throw new Error(`Unexpected historical data redirect: ${actual.origin}`);
    }
  }
  return response.text().then((text) => {
    if (text.length > maxChars) {
      throw new Error(
        `Historical data response exceeds ${maxChars} characters`,
      );
    }
    try {
      return JSON.parse(text);
    } catch (error) {
      throw new Error(
        `Invalid JSON from historical data source: ${error.message}`,
      );
    }
  });
}

function expectedFilename(year) {
  return `world_${year < 0 ? `bc${Math.abs(year)}` : year}.geojson`;
}

export function parseHistoricalIndex(index) {
  if (!Array.isArray(index?.years)) {
    throw new Error('Historical data index does not contain a years array');
  }
  const years = index.years
    .filter(
      (entry) =>
        Number.isSafeInteger(entry?.year) &&
        typeof entry.filename === 'string' &&
        entry.filename === expectedFilename(entry.year) &&
        Array.isArray(entry.countries),
    )
    .map(({ year, filename, countries }) => ({
      year,
      filename,
      countries: countries.filter(
        (country) => typeof country === 'string' && country.trim().length > 0,
      ),
    }))
    .sort((a, b) => a.year - b.year);
  if (!years.length)
    throw new Error('Historical data index contains no usable years');
  return years;
}

export function nearestHistoricalYear(year, years) {
  if (!Number.isSafeInteger(year)) {
    throw new TypeError('Historical year must be an integer');
  }
  if (!Array.isArray(years) || !years.length) {
    throw new TypeError('Historical years must be a non-empty array');
  }
  return years.reduce((nearest, candidate) =>
    Math.abs(candidate.year - year) < Math.abs(nearest.year - year)
      ? candidate
      : nearest,
  );
}

function createIndexedDbSnapshotCache(indexedDb) {
  let databasePromise;
  const openDatabase = () => {
    if (!indexedDb) return Promise.resolve(null);
    databasePromise ??= new Promise((resolve, reject) => {
      const request = indexedDb.open(SNAPSHOT_DB_NAME, SNAPSHOT_DB_VERSION);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(SNAPSHOT_STORE)) {
          request.result.createObjectStore(SNAPSHOT_STORE);
        }
      };
      request.onsuccess = () => {
        request.result.onversionchange = () => request.result.close();
        resolve(request.result);
      };
      request.onerror = () =>
        reject(request.error ?? new Error('Unable to open historical cache'));
      request.onblocked = () =>
        reject(new Error('Historical cache upgrade is blocked'));
    });
    return databasePromise;
  };

  const requestValue = async (mode, issueRequest) => {
    const database = await openDatabase();
    if (!database) return null;
    return new Promise((resolve, reject) => {
      const transaction = database.transaction(SNAPSHOT_STORE, mode);
      const request = issueRequest(transaction.objectStore(SNAPSHOT_STORE));
      request.onsuccess = () => resolve(request.result ?? null);
      request.onerror = () =>
        reject(request.error ?? new Error('Historical cache request failed'));
      transaction.onabort = () =>
        reject(
          transaction.error ??
            new Error('Historical cache transaction aborted'),
        );
    });
  };

  return Object.freeze({
    get: (key) => requestValue('readonly', (store) => store.get(key)),
    set: (key, value) =>
      requestValue('readwrite', (store) => store.put(value, key)),
  });
}

function entityProperties(entity, time) {
  return entity.properties?.getValue?.(time) ?? {};
}

function entityName(entity, time) {
  const values = entityProperties(entity, time);
  return String(
    values.NAME ??
      values.SUBJECTO ??
      values.PARTOF ??
      entity.id ??
      'unknown political entity',
  );
}

function stableEntityColor(name, engine) {
  let hash = 0;
  for (const character of name)
    hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return engine.Color.fromHsl((hash % 360) / 360, 0.58, 0.48, 0.32);
}

function styleEntities(dataSource, year, engine) {
  const time = dateAtUtc(year, 1, 1, engine);
  let count = 0;
  for (const entity of dataSource.entities.values) {
    if (!entity.polygon) continue;
    entity.polygon.material = stableEntityColor(
      entityName(entity, time),
      engine,
    );
    entity.polygon.outline = false;
    count += 1;
  }
  dataSource.name = `Historical borders ${year}`;
  return count;
}

function normalizedName(value) {
  return String(value ?? '')
    .normalize('NFKC')
    .trim()
    .replace(/\s+/g, ' ')
    .toLowerCase();
}

function closestFactionYear(year, factionsByYear) {
  const available = Object.keys(factionsByYear)
    .map(Number)
    .filter(Number.isSafeInteger)
    .sort((a, b) => a - b);
  if (!available.length) {
    throw new Error('Historical scenario has no faction-year mappings');
  }
  return available.reduce((nearest, candidate) =>
    Math.abs(candidate - year) < Math.abs(nearest - year) ? candidate : nearest,
  );
}

function applyFactionsToDataSource(
  dataSource,
  scenarioName,
  year,
  scenarios,
  engine,
) {
  const scenario = scenarios[scenarioName];
  if (!scenario)
    throw new RangeError(`Unknown historical scenario: ${scenarioName}`);
  if (!Number.isSafeInteger(year)) {
    throw new TypeError('Historical faction year must be an integer');
  }
  const selectedYear = closestFactionYear(year, scenario.factions_by_year);
  const factionsByYear = Object.fromEntries(
    Object.entries(scenario.factions_by_year).map(([anchorYear, entries]) => [
      Number(anchorYear),
      new Map(
        Object.entries(entries).map(([name, faction]) => [
          normalizedName(name),
          faction,
        ]),
      ),
    ]),
  );
  const time = dateAtUtc(year, 1, 1, engine);
  const factionMapFor = (atTime) => {
    const date = engine.JulianDate.toDate(atTime ?? time);
    const currentYear = date.getUTCFullYear();
    const anchorYear = closestFactionYear(
      currentYear,
      scenario.factions_by_year,
    );
    return factionsByYear[anchorYear];
  };
  const factionFor = (entity, atTime) => {
    const values = entityProperties(entity, atTime);
    return [values.NAME, values.SUBJECTO, values.PARTOF, entity.id]
      .map(normalizedName)
      .map((name) => factionMapFor(atTime).get(name))
      .find(Boolean);
  };
  const counts = Object.fromEntries(
    Object.keys(HISTORICAL_FACTION_COLORS).map((faction) => [faction, 0]),
  );
  let unmatched = 0;
  for (const entity of dataSource.entities.values) {
    if (!entity.polygon) continue;
    const faction = factionFor(entity, time);
    if (faction) counts[faction] += 1;
    else unmatched += 1;
    entity.polygon.material = new engine.ColorMaterialProperty(
      new engine.CallbackProperty((atTime) => {
        const currentFaction = factionFor(entity, atTime);
        return engine.Color.fromCssColorString(
          currentFaction
            ? HISTORICAL_FACTION_COLORS[currentFaction]
            : HISTORICAL_FACTION_COLORS.neutral,
        );
      }, false),
    );
  }
  return {
    ok: true,
    scenario: scenarioName,
    requestedYear: year,
    selectedFactionYear: selectedYear,
    counts,
    unmatched,
  };
}

function dateAtUtc(year, month = 1, day = 1, engine = Cesium) {
  if (
    !Number.isSafeInteger(year) ||
    !Number.isInteger(month) ||
    !Number.isInteger(day)
  ) {
    throw new TypeError(
      'Historical event date must use integer year, month, day',
    );
  }
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(0, 0, 0, 0);
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    throw new RangeError(`Invalid historical date: ${year}-${month}-${day}`);
  }
  return engine.JulianDate.fromDate(date);
}

function validateScenario(scenarios, name, year) {
  if (typeof name !== 'string' || !Object.hasOwn(scenarios, name)) {
    throw new RangeError(`Unknown historical scenario: ${name}`);
  }
  const scenario = scenarios[name];
  const selectedYear = year ?? scenario.start_year;
  if (
    !Number.isSafeInteger(selectedYear) ||
    selectedYear < scenario.start_year ||
    selectedYear > scenario.end_year
  ) {
    throw new RangeError(
      `Year must be between ${scenario.start_year} and ${scenario.end_year} for ${name}`,
    );
  }
  return { scenario, year: selectedYear };
}

function createEventDataSource(scenarioName, events, year, engine) {
  const source = new engine.CustomDataSource('historical-events');
  const minimum = dateAtUtc(-270000, 1, 1, engine);
  const maximum = dateAtUtc(270000, 1, 1, engine);
  const selected = events.filter(
    (event) =>
      event.scenario === scenarioName &&
      (year === undefined || event.year === year),
  );
  for (const event of selected) {
    const start = dateAtUtc(event.year, event.month, event.day, engine);
    const nextDay = new Date(0);
    nextDay.setUTCFullYear(event.year, event.month - 1, event.day + 1);
    nextDay.setUTCHours(0, 0, 0, 0);
    const stop = engine.JulianDate.fromDate(nextDay);
    const visible = new engine.TimeIntervalCollectionProperty();
    visible.intervals.addInterval(
      new engine.TimeInterval({
        start: minimum,
        stop: start,
        isStartIncluded: true,
        isStopIncluded: false,
        data: false,
      }),
    );
    visible.intervals.addInterval(
      new engine.TimeInterval({
        start,
        stop,
        isStartIncluded: true,
        isStopIncluded: false,
        data: true,
      }),
    );
    visible.intervals.addInterval(
      new engine.TimeInterval({
        start: stop,
        stop: maximum,
        isStartIncluded: true,
        isStopIncluded: true,
        data: false,
      }),
    );
    source.entities.add({
      id: `historical-event:${event.id}`,
      name: event.name,
      description: `${event.year}-${String(event.month).padStart(2, '0')}-${String(event.day).padStart(2, '0')} · ${event.type}`,
      position: engine.Cartesian3.fromDegrees(event.lon, event.lat),
      point: new engine.PointGraphics({
        pixelSize: event.type === 'battle' ? 11 : 9,
        color:
          event.type === 'battle'
            ? engine.Color.fromCssColorString('#FF5A36')
            : event.type === 'treaty'
              ? engine.Color.fromCssColorString('#FFD166')
              : event.type === 'crisis'
                ? engine.Color.fromCssColorString('#A855F7')
                : engine.Color.fromCssColorString('#50C7C7'),
        outlineColor: engine.Color.BLACK,
        outlineWidth: 1,
        show: visible,
      }),
      properties: {
        scenario: scenarioName,
        year: event.year,
        month: event.month,
        day: event.day,
        type: event.type,
        belligerents: event.belligerents,
      },
    });
  }
  source.name = 'historical-events';
  return { source, count: selected.length };
}

function validateEvents(data) {
  if (!Array.isArray(data?.events)) {
    throw new Error('Historical events data does not contain an events array');
  }
  const ids = new Set();
  for (const event of data.events) {
    if (
      !event ||
      typeof event.id !== 'string' ||
      !event.id ||
      ids.has(event.id) ||
      typeof event.name !== 'string' ||
      !Number.isSafeInteger(event.year) ||
      !Number.isInteger(event.month) ||
      event.month < 1 ||
      event.month > 12 ||
      !Number.isInteger(event.day) ||
      event.day < 1 ||
      event.day > 31 ||
      !Number.isFinite(event.lat) ||
      event.lat < -90 ||
      event.lat > 90 ||
      !Number.isFinite(event.lon) ||
      event.lon < -180 ||
      event.lon > 180 ||
      !['battle', 'treaty', 'crisis', 'event'].includes(event.type) ||
      !Array.isArray(event.belligerents) ||
      event.belligerents.some((faction) => !HISTORICAL_FACTIONS.has(faction)) ||
      typeof event.scenario !== 'string'
    ) {
      throw new Error(
        `Invalid historical event record: ${event?.id ?? 'unknown'}`,
      );
    }
    dateAtUtc(event.year, event.month, event.day);
    ids.add(event.id);
  }
  return data.events;
}

function installControlMessages({
  windowRef,
  location,
  listYears,
  loadScenario,
  applyFactions,
  loadEvents,
}) {
  if (!windowRef?.addEventListener || !windowRef?.parent) return () => {};
  const embeddedInline = windowRef.GEV_EMBED_INLINE === true;
  const embedded =
    embeddedInline ||
    new URLSearchParams(String(location?.search ?? '')).get('embed') === '1';
  if (!embedded) return () => {};

  const peer = embeddedInline ? windowRef : windowRef.parent;
  let queue = Promise.resolve();
  const onMessage = (event) => {
    const type = event.data?.type;
    const operations = {
      'gev:historical-scenario': () =>
        loadScenario(event.data.name, event.data.year),
      'gev:historical-factions': () =>
        applyFactions(event.data.scenario, event.data.year),
      'gev:historical-events': () =>
        loadEvents(event.data.scenario, event.data.year),
      'gev:historical-years': () => listYears(),
    };
    if (event.source !== peer || !Object.hasOwn(operations, type)) return;
    const operation = operations[type];
    const id = event.data.id ?? null;
    const targetOrigin =
      embeddedInline || !event.origin || event.origin === 'null'
        ? '*'
        : event.origin;
    queue = queue.then(async () => {
      try {
        const result = await operation();
        peer.postMessage(
          { type: `${type}-applied`, id, ok: true, result },
          targetOrigin,
        );
      } catch (error) {
        peer.postMessage(
          {
            type: `${type}-applied`,
            id,
            ok: false,
            error: error instanceof Error ? error.message : String(error),
          },
          targetOrigin,
        );
      }
    });
  };
  windowRef.addEventListener('message', onMessage);
  return () => windowRef.removeEventListener('message', onMessage);
}

/**
 * Load historical boundary snapshots, scenario overlays, and date-bounded
 * events. Remote snapshot failures use the local index and IndexedDB cache.
 */
export function createHistoricalMap({
  viewer,
  fetchImpl = globalThis.fetch,
  CesiumEngine = Cesium,
  setIntervalImpl = globalThis.setInterval,
  clearIntervalImpl = globalThis.clearInterval,
  indexedDb = globalThis.indexedDB,
  snapshotCache = createIndexedDbSnapshotCache(indexedDb),
  indexFallback: localIndex = indexFallback,
  factions = factionsFallback,
  events: localEvents = eventsFallback,
  windowRef = globalThis.window,
  location = globalThis.location,
  onPlaybackError = (error) =>
    console.error('GEV historical playback failed:', error),
} = {}) {
  if (!viewer?.dataSources || typeof fetchImpl !== 'function') {
    throw new TypeError(
      'Historical map requires a Cesium viewer and fetch implementation',
    );
  }
  const scenarios = factions?.scenarios;
  if (!scenarios || typeof scenarios !== 'object') {
    throw new TypeError('Historical faction data has no scenarios object');
  }
  validateFactionScenarios(scenarios);
  const events = validateEvents(localEvents);

  let indexPromise;
  let activeDataSource = null;
  let activeEventDataSource = null;
  let activeScenarioName = null;
  let generation = 0;
  let requestController = null;
  let playbackTimer = null;
  let playbackBusy = false;
  let destroyed = false;
  let scenarioClockState = null;
  let removeScenarioTick = null;
  let lastClockSnapshotYear = null;

  async function loadIndex() {
    indexPromise ??= (async () => {
      try {
        const response = await fetchImpl(HISTORICAL_INDEX_URL);
        return parseHistoricalIndex(
          await checkedJsonResponse(response, HISTORICAL_INDEX_URL),
        );
      } catch (error) {
        console.error(
          'GEV historical index request failed; using bundled index fallback:',
          error,
        );
        return parseHistoricalIndex(localIndex);
      }
    })().catch((error) => {
      indexPromise = null;
      throw error;
    });
    return indexPromise;
  }

  async function listYears() {
    const years = await loadIndex();
    return years.map((entry) => entry.year);
  }

  function stopPlayback() {
    if (playbackTimer !== null) {
      clearIntervalImpl(playbackTimer);
      playbackTimer = null;
    }
    playbackBusy = false;
  }

  async function loadGeoJson(selected, signal) {
    const url = `${HISTORICAL_GEOJSON_ROOT}${selected.filename}`;
    try {
      const response = await fetchImpl(url, { signal });
      const geojson = await checkedJsonResponse(response, url);
      if (
        geojson?.type !== 'FeatureCollection' ||
        !Array.isArray(geojson.features)
      ) {
        throw new Error(
          `Historical GeoJSON for ${selected.year} is not a FeatureCollection`,
        );
      }
      try {
        await snapshotCache?.set?.(selected.filename, geojson);
      } catch (error) {
        console.warn('GEV historical local cache write failed:', error);
      }
      return geojson;
    } catch (remoteError) {
      if (signal?.aborted) throw remoteError;
      console.error(
        `GEV historical snapshot request failed for ${selected.year}:`,
        remoteError,
      );
      try {
        const cached = await snapshotCache?.get?.(selected.filename);
        if (
          cached?.type === 'FeatureCollection' &&
          Array.isArray(cached.features)
        ) {
          console.warn(
            `GEV historical snapshot ${selected.year} loaded from local cache`,
          );
          return cached;
        }
      } catch (cacheError) {
        console.error(
          `GEV historical local cache read failed for ${selected.year}:`,
          cacheError,
        );
      }
      throw new Error(
        `Historical snapshot ${selected.year} unavailable remotely and in local cache`,
        { cause: remoteError },
      );
    }
  }

  async function showYear(
    requestedYear,
    { preservePlayback = false, scenarioYear = requestedYear } = {},
  ) {
    if (destroyed) throw new Error('Historical map has been destroyed');
    if (!Number.isSafeInteger(requestedYear)) {
      throw new TypeError('year must be an integer');
    }
    if (!preservePlayback) stopPlayback();
    const requestGeneration = ++generation;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    const years = await loadIndex();
    if (destroyed || requestGeneration !== generation) {
      return { ok: false, superseded: true };
    }
    const selected = nearestHistoricalYear(requestedYear, years);
    console.info('[HistoricalMap] snapshot selection', {
      requested_year: requestedYear,
      selected_year: selected.year,
    });
    const geojson = await loadGeoJson(selected, controller.signal);
    const namedFeatures = geojson.features.filter((feature) => {
      const properties = feature?.properties;
      return [properties?.NAME, properties?.SUBJECTO].some(
        (name) => typeof name === 'string' && name.trim().length > 0,
      );
    });
    if (!namedFeatures.length) {
      throw new Error(
        `Historical GeoJSON for ${selected.year} has no named entities`,
      );
    }
    if (destroyed || requestGeneration !== generation) {
      return { ok: false, superseded: true };
    }

    const next = await CesiumEngine.GeoJsonDataSource.load(
      { ...geojson, features: namedFeatures },
      {
        clampToGround: true,
        strokeWidth: 0,
        fill: CesiumEngine.Color.WHITE.withAlpha(0.32),
      },
    );
    const entityCount = styleEntities(next, selected.year, CesiumEngine);
    const factionResult = activeScenarioName
      ? applyFactionsToDataSource(
          next,
          activeScenarioName,
          scenarioYear,
          scenarios,
          CesiumEngine,
        )
      : null;
    await viewer.dataSources.add(next);
    if (destroyed || requestGeneration !== generation) {
      viewer.dataSources.remove(next, true);
      return { ok: false, superseded: true };
    }
    const previous = activeDataSource;
    activeDataSource = next;
    if (previous) viewer.dataSources.remove(previous, true);
    return {
      ok: true,
      requestedYear,
      year: selected.year,
      filename: selected.filename,
      entityCount,
      factionResult,
      availableYears: years.map((entry) => entry.year),
    };
  }

  function applyFactions(scenarioName, year) {
    if (!activeDataSource) {
      throw new Error('Load a historical snapshot before applying factions');
    }
    validateScenario(scenarios, scenarioName, year);
    if (viewer.clock) {
      viewer.clock.currentTime = dateAtUtc(year, 1, 1, CesiumEngine);
    }
    const result = applyFactionsToDataSource(
      activeDataSource,
      scenarioName,
      year,
      scenarios,
      CesiumEngine,
    );
    activeScenarioName = scenarioName;
    return result;
  }

  async function loadEvents(scenarioName, year) {
    const { year: selectedYear } = validateScenario(
      scenarios,
      scenarioName,
      year,
    );
    if (year !== undefined && !Number.isSafeInteger(year)) {
      throw new TypeError('Historical event year must be an integer');
    }
    const { source, count } = createEventDataSource(
      scenarioName,
      events,
      year,
      CesiumEngine,
    );
    await viewer.dataSources.add(source);
    const previous = activeEventDataSource;
    activeEventDataSource = source;
    if (previous) viewer.dataSources.remove(previous, true);
    return {
      ok: true,
      scenario: scenarioName,
      year: year ?? null,
      defaultScenarioYear: selectedYear,
      count,
    };
  }

  async function syncScenarioSnapshot(clock) {
    if (!activeScenarioName || destroyed) return;
    try {
      const currentYear = CesiumEngine.JulianDate.toDate(
        clock.currentTime,
      ).getUTCFullYear();
      const scenario = scenarios[activeScenarioName];
      if (currentYear > scenario.end_year) {
        clock.shouldAnimate = false;
        return;
      }
      if (
        currentYear < scenario.start_year ||
        currentYear > scenario.end_year
      ) {
        return;
      }
      const selected = nearestHistoricalYear(currentYear, await loadIndex());
      if (selected.year === lastClockSnapshotYear) return;
      lastClockSnapshotYear = selected.year;
      await showYear(currentYear, {
        preservePlayback: true,
        scenarioYear: currentYear,
      });
    } catch (error) {
      onPlaybackError(error);
    }
  }

  async function loadScenario(name, year) {
    const { scenario, year: selectedYear } = validateScenario(
      scenarios,
      name,
      year,
    );
    const previousScenario = activeScenarioName;
    if (!scenarioClockState && viewer.clock) {
      scenarioClockState = {
        currentTime: CesiumEngine.JulianDate.clone(viewer.clock.currentTime),
        multiplier: viewer.clock.multiplier,
        clockRange: viewer.clock.clockRange,
        stopTime: CesiumEngine.JulianDate.clone(viewer.clock.stopTime),
        shouldAnimate: viewer.clock.shouldAnimate,
      };
    }
    activeScenarioName = name;
    try {
      const map = await showYear(selectedYear, {
        scenarioYear: selectedYear,
      });
      if (!map.ok) throw new Error('Historical scenario load was superseded');
      const factionsResult = applyFactions(name, selectedYear);
      const eventsResult = await loadEvents(name);
      if (viewer.clock) {
        viewer.clock.currentTime = dateAtUtc(selectedYear, 1, 1, CesiumEngine);
        viewer.clock.stopTime = dateAtUtc(
          scenario.end_year + 1,
          1,
          1,
          CesiumEngine,
        );
        viewer.clock.clockRange = CesiumEngine.ClockRange.CLAMPED;
        viewer.clock.multiplier =
          JULIAN_YEAR_SECONDS / SCENARIO_SECONDS_PER_YEAR;
        viewer.clock.shouldAnimate = true;
        lastClockSnapshotYear = map.year;
        if (!removeScenarioTick && viewer.clock.onTick) {
          const remove =
            viewer.clock.onTick.addEventListener(syncScenarioSnapshot);
          removeScenarioTick =
            typeof remove === 'function'
              ? remove
              : () =>
                  viewer.clock.onTick.removeEventListener(syncScenarioSnapshot);
        }
      }
      return {
        ok: true,
        name,
        label: scenario.name,
        year: selectedYear,
        map,
        factions: factionsResult,
        events: eventsResult,
        shouldAnimate: viewer.clock?.shouldAnimate ?? false,
      };
    } catch (error) {
      activeScenarioName = previousScenario;
      if (!previousScenario) restoreScenarioClock();
      throw error;
    }
  }

  function restoreScenarioClock() {
    if (removeScenarioTick) {
      removeScenarioTick();
      removeScenarioTick = null;
    }
    if (scenarioClockState && viewer.clock) {
      viewer.clock.currentTime = scenarioClockState.currentTime;
      viewer.clock.multiplier = scenarioClockState.multiplier;
      viewer.clock.clockRange = scenarioClockState.clockRange;
      viewer.clock.stopTime = scenarioClockState.stopTime;
      viewer.clock.shouldAnimate = scenarioClockState.shouldAnimate;
    }
    scenarioClockState = null;
    lastClockSnapshotYear = null;
  }

  async function animate(startYear, endYear, speed = 3) {
    if (!Number.isSafeInteger(startYear) || !Number.isSafeInteger(endYear)) {
      throw new TypeError('start_year and end_year must be integers');
    }
    if (startYear > endYear)
      throw new RangeError('start_year must not exceed end_year');
    if (!Number.isFinite(speed) || speed < 0.5 || speed > 30) {
      throw new RangeError(
        'speed must be between 0.5 and 30 seconds per snapshot',
      );
    }
    stopPlayback();
    const years = await loadIndex();
    const first = nearestHistoricalYear(startYear, years);
    const snapshots = years.filter(
      (entry) => entry.year >= first.year && entry.year <= endYear,
    );
    if (!snapshots.length) {
      throw new RangeError(
        `No historical snapshots are available through ${endYear}`,
      );
    }
    let index = 0;
    const initial = await showYear(snapshots[index].year);
    if (!initial.ok)
      throw new Error('Historical playback was superseded before it started');
    const advance = async () => {
      if (playbackBusy || destroyed || !playbackTimer) return;
      playbackBusy = true;
      try {
        index = (index + 1) % snapshots.length;
        await showYear(snapshots[index].year, {
          preservePlayback: true,
          scenarioYear: snapshots[index].year,
        });
      } catch (error) {
        stopPlayback();
        onPlaybackError(error);
      } finally {
        playbackBusy = false;
      }
    };
    if (snapshots.length > 1) {
      playbackTimer = setIntervalImpl(() => advance(), speed * 1000);
    }
    return {
      ok: true,
      startYear,
      endYear,
      speed,
      snapshots: snapshots.map((entry) => entry.year),
      currentYear: initial.year,
      playing: snapshots.length > 1,
    };
  }

  async function execute(message) {
    if (!message || typeof message !== 'object' || Array.isArray(message)) {
      throw new TypeError('Historical map command must be an object');
    }
    switch (message.command) {
      case 'show':
        return showYear(message.year);
      case 'animate':
        return animate(
          message.start_year,
          message.end_year,
          message.speed ?? 3,
        );
      case 'stop':
        stopPlayback();
        if (scenarioClockState && viewer.clock) {
          viewer.clock.shouldAnimate = false;
        }
        return { ok: true, playing: false };
      case 'clear':
        stopPlayback();
        generation += 1;
        requestController?.abort();
        requestController = null;
        if (activeDataSource) viewer.dataSources.remove(activeDataSource, true);
        if (activeEventDataSource)
          viewer.dataSources.remove(activeEventDataSource, true);
        activeDataSource = null;
        activeEventDataSource = null;
        activeScenarioName = null;
        restoreScenarioClock();
        return { ok: true, cleared: true };
      default:
        throw new TypeError(
          `Unsupported historical map command: ${message.command}`,
        );
    }
  }

  const removeControlMessages = installControlMessages({
    windowRef,
    location,
    listYears,
    loadScenario,
    applyFactions,
    loadEvents,
  });

  function destroy() {
    if (destroyed) return;
    destroyed = true;
    stopPlayback();
    generation += 1;
    requestController?.abort();
    requestController = null;
    removeControlMessages();
    if (activeDataSource) viewer.dataSources.remove(activeDataSource, true);
    if (activeEventDataSource)
      viewer.dataSources.remove(activeEventDataSource, true);
    activeDataSource = null;
    activeEventDataSource = null;
    activeScenarioName = null;
    restoreScenarioClock();
  }

  return Object.freeze({
    applyFactions,
    destroy,
    execute,
    listYears,
    loadEvents,
    loadScenario,
  });
}
