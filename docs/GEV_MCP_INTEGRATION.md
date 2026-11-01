# GEV MCP integration in Jarvis

## Scope and verified source

Jarvis starts the MCP stdio server shipped in the sibling GEV checkout:
`server/mcp/stdio.js`. The server is started with the same portable
`_gev-clone/.node/node.exe` used for Vite and reads from the local GEV API on
`http://127.0.0.1:4173/`. Jarvis does not modify the GEV repository.

The server's `tools/list` response is the source of truth for functions
exposed to Gemini. In the checked-out version, it lists 30 MCP tools; the
plugin publishes each as a separate namespaced function named
`gev_mcp_<mcp-tool-name>`. Tool input JSON Schemas are converted to Gemini
`FunctionDeclaration` schema types, then MCP `tools/call` responses are
returned to Jarvis. The existing `gev` function remains for the UI-specific
`open`, `track`, `layer`, `reset`, and `annotate` actions.

## MCP tools exposed by the checked-out GEV server

The verified `tools/list` catalog contained:

| Category | Names |
|---|---|
| Hazards and environment | `get_earthquakes`, `get_active_fires`, `get_cyclones`, `get_fire_perimeters`, `get_terrain_height`, `find_military_installations`, `get_map_features` |
| Aviation | `aircraft_in_area`, `find_aircraft`, `get_aircraft_track`, `get_aircraft_info` |
| Maritime | `vessels_in_area`, `find_vessel`, `get_vessel_track` |
| Space | `get_recent_launches`, `next_satellite_pass`, `satellites_overhead` |
| Cameras and roads | `find_cctv_cameras`, `get_cctv_snapshot`, `find_alpr_cameras`, `get_traffic_flow` |
| Infrastructure and imagery | `find_submarine_cables`, `find_infrastructure`, `get_recent_imagery` |
| Composite reports | `get_bhote_koshi_flood`, `situation_brief`, `military_awareness` |
| Globe actions / panel | `show_in_gods_eye_view`, `panel_request` |
| Other exposed data | `get_weather_map` |

The list is verified from a live `tools/list` response; it is not a promise
that every data source is reachable at runtime. GEV's tool descriptions and
input schemas are the live descriptions sent to Gemini.

## Explicit limitations

GEV's `src/tools/surfaces.js` excludes `search_places`, `places_nearby`,
`plan_route`, `get_weather`, `get_wind`, `get_regional_brief`,
`find_radio_stations`, `get_bike_share`, and `get_transit_vehicles` from its
MCP surface. This integration respects that upstream boundary and does not
advertise those functions. The transcript's proposed camera tour recording
and standalone cockpit controls are also not independent tools in the
verified MCP catalog.

Vessel data queries are available through MCP, but GEV's view schema only
allows following `aircraft`, `military_aircraft`, and `satellite`; the direct
Jarvis `track` action therefore accepts `flight` and `satellite`, not
`vessel`.

The MCP stdio server is a separate local Node process. It is stopped before
Vite and is assigned to the same Windows kill-on-job-close Job Object so an
abrupt Jarvis exit also cleans it up. MCP requests have a 60-second timeout.
Large structured results are capped at 12,000 characters before they are
returned through Gemini's text response channel.

## Verification performed

- Focused pytest suite: MCP JSON-RPC lifecycle and calls, schema conversion,
  tool result errors, dynamic plugin declaration/routing, name collision
  handling, and removal of vessel follow from the plugin enum.
- Live local check: initialized the GEV stdio MCP server, received 30 tools,
  converted all schemas, and constructed each with
  `google.genai.types.FunctionDeclaration` without schema errors.
- These checks verify local transport, discovery, and declaration
  compatibility. Individual data providers still depend on their sources
  and any provider/API configuration.

## Source references

- Jarvis MCP transport and schema adapter:
  [`../plugins/_gev_mcp_client.py`](../plugins/_gev_mcp_client.py)
- GEV plugin lifecycle and MCP routing:
  [`../plugins/gev_plugin.py`](../plugins/gev_plugin.py)
- Dynamic plugin tool registration and routing:
  [`../core/plugin_loader.py`](../core/plugin_loader.py)
- GEV MCP stdio entry point:
  `../../../gods-eye-view-main/_gev-clone/server/mcp/stdio.js`
- GEV MCP surface policy:
  `../../../gods-eye-view-main/_gev-clone/src/tools/surfaces.js`
