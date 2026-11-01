# Historical maps and scenarios

## Evidence labels

- **Verified in code** means the behavior has an implementation and/or an
  automated test in this checkout.
- **Manual verification pending** means the Jarvis desktop workflow has not
  been rerun for this change.
- Historical classifications in the JSON files are hand-authored scenario
  mappings. They are not classifications supplied by the GeoJSON dataset.

## Snapshot index and offline behavior

`src/app/historicalMap.js:94` fetches and validates the index from
[`aourednik/historical-basemaps`](https://github.com/aourednik/historical-basemaps)
and validates the `years` records (`year`, `filename`, `countries`). The
checked-in `data/historical-index-fallback.json` is used if the remote index is
unavailable. `listYears()` returns the accepted year numbers. A requested year
without an exact snapshot selects the closest indexed year and logs
`requested_year` and `selected_year`.

The upstream repository's root license is GPLv3. The bundled index is
third-party data, not MIT-licensed application code; its license text is
included in `data/HISTORICAL_BASEMAPS_LICENSE.txt` and its source is recorded
in [`DATA_SOURCES.md`](../DATA_SOURCES.md). Only the lightweight index is
bundled; the GeoJSON snapshots are fetched remotely and cached in the browser.

Filenames are checked against the upstream convention, including BCE names
such as `world_bc123000.geojson`. The bundled index contains 54 source records;
the live browser smoke accepted all 54. Snapshot GeoJSON is fetched on demand
and cached in browser IndexedDB. If the remote
snapshot cannot be fetched, a previously cached snapshot with the same filename
is used. **The complete GeoJSON archive is not bundled:** offline map rendering
works only for snapshots already cached in that browser profile.

## Factions and scenarios

`data/factions.json` defines the `ww1`, `ww2`, and `cold_war` scenarios and
year-specific entity-to-faction mappings. `applyFactions(scenario, year)`
sets each polygon's material to a Cesium callback material. The callback
chooses the nearest scenario mapping anchor for the current Cesium clock year.
The supported palette is:

| Faction token | Color |
| --- | --- |
| `axis` | `#B22222` |
| `allies` | `#1E90FF` |
| `neutral` | `#808080` |
| `comintern` | `#8B0000` |
| `nato` | `#00008B` |
| `warsaw_pact` | `#DC143C` |

`loadScenario(name, year?)` validates the scenario range, selects the closest
available map snapshot, applies faction colors, loads that scenario's events,
sets the clock to January 1 of the requested/default start year, and enables
Cesium animation. Playback advances one simulated year every 20 seconds and
stops at January 1 after the scenario end year. When the nearest indexed
geometry snapshot changes, the controller loads that snapshot; faction colors
continue to follow the Cesium clock. `stop`, `clear`, and controller teardown
pause or restore the original clock state (`src/app/historicalMap.js:290`,
`:730`, `:777`, `:806`). The snapshot year and requested scenario year are
distinct: missing geometry years are not generated or interpolated.

The WWI configuration reuses the `axis` color token to represent the Central
Powers; it does not identify those states with the WWII Axis. The year anchors
are coarse annual labels and do not model changes within a year. For example,
the 1941 WWII mapping is one year-wide classification even though alliance
status changed during that year. Unknown or unmatched GeoJSON entity names are
shown in gray and counted as unmatched. **These mappings are not a historical
control database.**

> Da verificare: exact name matching and classification for every entity in
> each available snapshot. The source index and GeoJSON do not themselves
> verify the scenario assignments.

## Dated events

`data/events.json` provides sample battle, treaty, crisis, and other event
records. `loadEvents(scenario, year?)` replaces the prior event layer with
matching scenario events. A `TimeIntervalCollectionProperty` controls point
visibility for the event's UTC calendar day; battle, treaty, crisis, and
general event points use distinct colors
(`src/app/historicalMap.js:352`, `:428`).

> Da verificare: event completeness, date/coordinate precision, and historical
> interpretation before treating this sample layer as a sourced chronology.

## Embedded control protocol

When GEV is embedded, the historical controller accepts:

| Request `type` | Required fields | Response `type` |
| --- | --- | --- |
| `gev:historical-scenario` | `name`, optional `year` | `gev:historical-scenario-applied` |
| `gev:historical-factions` | `scenario`, `year` | `gev:historical-factions-applied` |
| `gev:historical-events` | `scenario`, optional `year` | `gev:historical-events-applied` |
| `gev:historical-years` | none | `gev:historical-years-applied` |

Replies carry the request `id`, `ok`, and either `result` or `error`. Incoming
requests are serialized in arrival order (`src/app/historicalMap.js:468`).
Automated coverage is in `src/app/historicalMap.test.mjs`.

## Tests

Run from the GEV checkout:

```powershell
.\.node\node.exe --test src\app\historicalMap.test.mjs
```

The focused suite checks index parsing (including BCE), year listing, nearest
snapshot selection, offline index/cache fallback, explicit remote failures,
faction color changes as the clock advances, scenario startup, and date-bounded
events.

## Browser smoke test — verified

GEV was run from the local Vite server at `http://127.0.0.1:4173/` in
`?embed=1` mode. The browser requests returned successfully:

- `gev:historical-years`: 54 years, from `-123000` through `2010`.
- `gev:historical-scenario` for `ww2`, 1941: returned requested year 1941,
  selected GeoJSON snapshot 1938, and 531 named entities. The response counted
  87 `axis`, 120 `allies`, 18 `neutral`, and 306 unmatched entities.
- `gev:historical-factions` for 1943 and `gev:historical-events` for 1944:
  both returned success; the latter selected one event.
- Live Cesium material values for Italy changed from `rgb(178,34,34)` in 1941
  to `rgb(30,144,255)` in 1943. The 1944 Normandy event's show property was
  `true` on June 6 and `false` on June 7.
- Advancing the live scenario clock to 1942 and raising a Cesium tick switched
  the loaded boundary snapshot from 1938 to 1945. `clear` restored the prior
  clock year, multiplier, and animation state. Automated coverage also checks
  scenario end handling and clock restoration.

This confirms browser-side controller behavior and message handling. It does
not verify historical correctness of the faction labels or voice recognition.

## Verification still pending

- Test the four response paths inside Jarvis's QWebEngine window; the Python
  bridge is covered by plugin tests, but this desktop round trip was not run.
- Test voice recognition and voice-issued scenario requests.
- Test persistent IndexedDB behavior across browser restarts and network loss;
  the automated fallback test uses a controlled cache fake.
- > Da verificare: the upstream dataset's historical accuracy and licensing
  terms before bundling or mirroring any GeoJSON boundary snapshots. The
  bundled index license does not by itself establish rights for those files.
