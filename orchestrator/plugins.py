"""Registry and dispatch boundary for injected agent plugins."""

from __future__ import annotations

from collections.abc import Iterable

from agents.contracts import ActionContext, AgentPlugin
from capabilities.contracts import ToolCall, ToolReply


class AgentRegistry:
    """Dispatch tool calls to uniquely named plugins without owning their policy."""

    def __init__(self, plugins: Iterable[AgentPlugin] = ()) -> None:
        self._plugins: dict[str, AgentPlugin] = {}
        for plugin in plugins:
            self.register(plugin)

    def register(self, plugin: AgentPlugin) -> None:
        name = getattr(plugin, "name", None)
        if not isinstance(name, str) or not name.strip():
            raise TypeError("Agent plugins must provide a non-empty name.")
        if not callable(getattr(plugin, "execute", None)):
            raise TypeError("Agent plugins must provide an execute() method.")
        normalized_name = name.strip()
        if normalized_name in self._plugins:
            raise ValueError(f"An agent plugin named {normalized_name!r} is registered.")
        self._plugins[normalized_name] = plugin

    async def dispatch(self, call: ToolCall, context: ActionContext) -> ToolReply:
        if not isinstance(call, ToolCall):
            raise TypeError("call must be a ToolCall.")
        if not isinstance(context, ActionContext):
            raise TypeError("context must be an ActionContext.")
        plugin = self._plugins.get(call.name)
        if plugin is None:
            raise LookupError(f"No agent plugin is registered for {call.name!r}.")
        reply = await plugin.execute(call, context)
        if not isinstance(reply, ToolReply):
            raise TypeError("Agent plugins must return a ToolReply.")
        if reply.call_id != call.call_id or reply.name != call.name:
            raise ValueError("Agent plugin reply does not match the dispatched call.")
        return reply
