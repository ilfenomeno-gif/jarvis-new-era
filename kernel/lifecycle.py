"""Deterministic startup and reverse-order shutdown for kernel components."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class Component(Protocol):
    async def start(self) -> None: ...
    async def close(self) -> None: ...


class KernelState(StrEnum):
    NEW = "new"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"
    CLOSED = "closed"


class LifecycleError(RuntimeError):
    pass


class Kernel:
    """Starts components in order and closes them in reverse order."""

    def __init__(self, components: tuple[Component, ...] = ()) -> None:
        self._components = tuple(components)
        self._started: list[Component] = []
        self.state = KernelState.NEW

    async def start(self) -> None:
        if self.state is not KernelState.NEW:
            raise LifecycleError(f"Cannot start kernel while it is {self.state.value}.")
        self.state = KernelState.STARTING
        try:
            for component in self._components:
                self._started.append(component)
                await component.start()
        except BaseException as startup_error:
            cleanup_errors = await self._close_started()
            self.state = KernelState.FAILED
            if cleanup_errors:
                raise BaseExceptionGroup(
                    "Kernel startup failed and cleanup reported errors.",
                    [startup_error, *cleanup_errors],
                ) from startup_error
            raise
        self.state = KernelState.RUNNING

    async def close(self) -> None:
        if self.state is KernelState.CLOSED:
            return
        if self.state is KernelState.STARTING:
            raise LifecycleError("Cannot close the kernel while startup is in progress.")
        errors = await self._close_started()
        self.state = KernelState.CLOSED
        if errors:
            raise BaseExceptionGroup("Kernel shutdown reported errors.", errors)

    async def _close_started(self) -> list[BaseException]:
        errors: list[BaseException] = []
        while self._started:
            component = self._started.pop()
            try:
                await component.close()
            except BaseException as exc:
                errors.append(exc)
        return errors
