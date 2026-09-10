"""Explicit production lifecycle coordinator for Live runtime startup/shutdown ordering."""
from __future__ import annotations

import asyncio

from typing import Any, Callable


class LiveRuntimeLifecycleCoordinator:
    """Own the cross-component Live startup/recovery/execution lifecycle."""

    def __init__(
        self,
        *,
        controller: Any,
        bootstrap: Any,
        release_execution_transport_ownership: Callable[[], None] | None = None,
    ) -> None:
        if controller is None:
            raise ValueError("LIVE_RUNTIME_CONTROLLER_REQUIRED")
        if bootstrap is None:
            raise ValueError("LIVE_RUNTIME_BOOTSTRAP_REQUIRED")
        self._controller = controller
        self._bootstrap = bootstrap
        self._release_execution_transport_ownership = release_execution_transport_ownership
        self._controller_identity = id(controller)
        self._bootstrap_identity = id(bootstrap)
        self._started = False
        self._stopping = False
        self._active_receives = 0
        self._receive_tasks: set[asyncio.Task[Any]] = set()
        self._receives_drained = asyncio.Event()
        self._receives_drained.set()
        self._policy: Any | None = None
        self._technical_state: str | None = None

    def _assert_dependency_identity(self) -> None:
        if id(self._controller) != self._controller_identity:
            raise RuntimeError("LIVE_RUNTIME_CONTROLLER_IDENTITY_CHANGED")
        if id(self._bootstrap) != self._bootstrap_identity:
            raise RuntimeError("LIVE_RUNTIME_BOOTSTRAP_IDENTITY_CHANGED")

    def _release_transport_ownership(self) -> None:
        if self._release_execution_transport_ownership is not None:
            self._release_execution_transport_ownership()
            self._release_execution_transport_ownership = None

    def _restart_admitted(self) -> bool:
        """Only a fully stopped lifecycle may reuse this coordinator."""
        return (
            not self._started
            and not self._stopping
            and self._technical_state is None
        )

    async def start(self, config: Any, policy: Any, *, hts_id: str, recovery_query: Any) -> Any:
        self._assert_dependency_identity()
        if not self._restart_admitted():
            raise RuntimeError("LIVE_RUNTIME_RESTART_NOT_ADMITTED")

        execution_start_attempted = False
        try:
            self._controller.start(config, policy)
            recovered = self._bootstrap.startup_reconcile(recovery_query)
            execution_start_attempted = True
            await self._bootstrap.start_execution(hts_id)
        except asyncio.CancelledError as startup_cancelled:
            if execution_start_attempted:
                try:
                    await self._bootstrap.close_execution()
                except asyncio.CancelledError:
                    self._started = False
                    self._stopping = True
                    self._technical_state = "STARTUP_CLEANUP_CANCELLED"
                    raise
                except Exception:
                    pass

            try:
                self._safe_controller_stop()
            except Exception as controller_stop_error:
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_CONTROLLER_FAILED"
                controller_stop_error.__cause__ = startup_cancelled
                raise

            try:
                self._release_transport_ownership()
            except Exception as ownership_release_error:
                self._started = False
                self._stopping = True
                self._technical_state = "TRANSPORT_OWNERSHIP_RELEASE_FAILED"
                ownership_release_error.__cause__ = startup_cancelled
                raise
            raise
        except Exception as startup_error:
            if execution_start_attempted:
                try:
                    await self._bootstrap.close_execution()
                except asyncio.CancelledError:
                    self._started = False
                    self._stopping = True
                    self._technical_state = "STARTUP_CLEANUP_CANCELLED"
                    raise
                except Exception:
                    pass

            try:
                self._safe_controller_stop()
            except Exception as controller_stop_error:
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_CONTROLLER_FAILED"
                controller_stop_error.__cause__ = startup_error
                raise

            try:
                self._release_transport_ownership()
            except Exception as ownership_release_error:
                self._started = False
                self._stopping = True
                self._technical_state = "TRANSPORT_OWNERSHIP_RELEASE_FAILED"
                ownership_release_error.__cause__ = startup_error
                raise
            raise

        self._started = True
        self._stopping = False
        self._policy = policy
        self._technical_state = None
        return recovered

    async def receive_execution_once(self) -> Any:
        self._assert_dependency_identity()
        if not self._started or self._stopping:
            raise RuntimeError("LIVE_RUNTIME_NOT_STARTED")
        task = asyncio.current_task()
        self._active_receives += 1
        self._receives_drained.clear()
        if task is not None:
            self._receive_tasks.add(task)
        try:
            return await self._bootstrap.receive_execution_once()
        finally:
            if task is not None:
                self._receive_tasks.discard(task)
            self._active_receives -= 1
            if self._active_receives == 0:
                self._receives_drained.set()

    async def _wait_receives_drained(self, timeout_seconds: float) -> None:
        await asyncio.wait_for(
            self._receives_drained.wait(),
            timeout=timeout_seconds,
        )

    async def _cancel_inflight_receives(self) -> None:
        """Use transport-provided cancellation first, otherwise cancel admitted tasks."""
        cancel = getattr(self._bootstrap, "cancel_execution_receives", None)
        if callable(cancel):
            result = cancel()
            if hasattr(result, "__await__"):
                await result
            return

        current = asyncio.current_task()
        for task in tuple(self._receive_tasks):
            if task is not current and not task.done():
                task.cancel()

    @property
    def runtime_controller(self) -> Any:
        """Authoritative controller owned by this production lifecycle graph."""
        self._assert_dependency_identity()
        return self._controller

    @property
    def technical_state(self) -> str | None:
        """Control-plane lifecycle state; independent from Domain order/position state."""
        self._assert_dependency_identity()
        return self._technical_state

    async def stop(self) -> None:
        self._assert_dependency_identity()
        if not self._started:
            if self._technical_state is not None:
                raise RuntimeError("LIVE_RUNTIME_RESTART_NOT_ADMITTED")
            try:
                self._safe_controller_stop()
            except Exception as controller_stop_error:
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_CONTROLLER_FAILED"
                raise controller_stop_error
            try:
                self._release_transport_ownership()
            except Exception:
                self._started = False
                self._stopping = True
                self._technical_state = "TRANSPORT_OWNERSHIP_RELEASE_FAILED"
                raise
            return

        graceful_timeout = float(
            getattr(self._policy, "graceful_shutdown_timeout_seconds", 10.0)
        )
        cancellation_timeout = float(
            getattr(self._policy, "cancellation_drain_timeout_seconds", 5.0)
        )
        if graceful_timeout < 0 or cancellation_timeout < 0:
            raise ValueError("LIVE_RUNTIME_INVALID_SHUTDOWN_TIMEOUT")

        self._stopping = True
        close_error: Exception | None = None
        timeout_error: Exception | None = None

        shutdown_cancelled: asyncio.CancelledError | None = None
        try:
            try:
                await self._bootstrap.close_execution()
            except asyncio.CancelledError as exc:
                shutdown_cancelled = exc
            except Exception as exc:
                close_error = exc

            if shutdown_cancelled is None:
                try:
                    await self._wait_receives_drained(graceful_timeout)
                except asyncio.CancelledError as exc:
                    shutdown_cancelled = exc
                except asyncio.TimeoutError:
                    try:
                        await self._cancel_inflight_receives()
                    except asyncio.CancelledError as exc:
                        shutdown_cancelled = exc
                    except Exception as exc:
                        timeout_error = RuntimeError(
                            "LIVE_RUNTIME_SHUTDOWN_CANCELLATION_FAILED"
                        )
                        timeout_error.__cause__ = exc
                    if timeout_error is None and shutdown_cancelled is None:
                        try:
                            await self._wait_receives_drained(cancellation_timeout)
                        except asyncio.CancelledError as exc:
                            shutdown_cancelled = exc
                        except asyncio.TimeoutError:
                            timeout_error = RuntimeError(
                                "LIVE_RUNTIME_SHUTDOWN_DRAIN_TIMEOUT"
                            )
        finally:
            if shutdown_cancelled is not None:
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_SHUTDOWN_CANCELLED"
            elif timeout_error is None:
                self._started = False
                try:
                    self._controller.stop()
                except Exception as exc:
                    self._stopping = True
                    self._technical_state = "STOP_CONTROLLER_FAILED"
                    if close_error is not None:
                        exc.__cause__ = close_error
                    raise
                else:
                    if close_error is not None:
                        self._stopping = True
                        self._technical_state = "STOP_EXECUTION_CLOSE_FAILED"
                    else:
                        try:
                            self._release_transport_ownership()
                        except Exception:
                            self._stopping = True
                            self._technical_state = "TRANSPORT_OWNERSHIP_RELEASE_FAILED"
                            raise
                        else:
                            self._stopping = False
                            self._technical_state = None
            else:
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_TIMEOUT"

        if shutdown_cancelled is not None:
            raise shutdown_cancelled
        if timeout_error is not None:
            raise timeout_error
        if close_error is not None:
            raise close_error

    def _safe_controller_stop(self) -> None:
        self._controller.stop()
