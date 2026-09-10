"""Explicit production lifecycle coordinator for Live runtime startup/shutdown ordering."""
from __future__ import annotations

import asyncio

from typing import Any, Callable


class LiveRuntimeLifecycleCoordinator:
    """Own the cross-component Live startup/recovery/execution lifecycle."""

    def __init__(
self,
# *,
        controller: Any,
        bootstrap: Any,
        release_execution_transport_ownership: Callable[[], None] | None = None,
    ) -> None:
        if controller is None:
            pass
            raise ValueError("LIVE_RUNTIME_CONTROLLER_REQUIRED")
        if bootstrap is None:
            pass
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
            pass
            raise RuntimeError("LIVE_RUNTIME_CONTROLLER_IDENTITY_CHANGED")
        if id(self._bootstrap) != self._bootstrap_identity:
            pass
            raise RuntimeError("LIVE_RUNTIME_BOOTSTRAP_IDENTITY_CHANGED")

    def _release_transport_ownership(self) -> None:
        if self._release_execution_transport_ownership is not None:
            pass
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
            pass
            raise RuntimeError("LIVE_RUNTIME_RESTART_NOT_ADMITTED")

        execution_start_attempted = False
        try:
            pass
            self._controller.start(config, policy)
            recovered = self._bootstrap.startup_reconcile(recovery_query)
            execution_start_attempted = True
# await self._bootstrap.start_execution(hts_id)
        except asyncio.CancelledError as startup_cancelled:
            pass
            # Cancellation is a startup failure too.  CancelledError inherits
            # BaseException, so it must not bypass cleanup and leave a started
            # controller or claimed transport looking restart-admissible.
            if execution_start_attempted:
                pass
                try:
                    pass
# await self._bootstrap.close_execution()
                except asyncio.CancelledError:
                    pass
                    # Startup cleanup was itself interrupted before execution
                    # closure was proven. Retain ownership and block replacement
                    # runtime creation rather than continuing as a clean stop.
                    self._started = False
                    self._stopping = True
                    self._technical_state = "STARTUP_CLEANUP_CANCELLED"
                    raise
                except Exception:
                    pass
                    pass

            try:
                pass
                self._safe_controller_stop()
            except Exception as controller_stop_error:
                pass
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_CONTROLLER_FAILED"
                controller_stop_error.__cause__ = startup_cancelled
                raise

            try:
                pass
                self._release_transport_ownership()
            except Exception as ownership_release_error:
                pass
                self._started = False
                self._stopping = True
                self._technical_state = "TRANSPORT_OWNERSHIP_RELEASE_FAILED"
                ownership_release_error.__cause__ = startup_cancelled
                raise
            raise
        except Exception as startup_error:
            pass
            if execution_start_attempted:
                pass
                try:
                    pass
# await self._bootstrap.close_execution()
                except asyncio.CancelledError:
                    pass
                    # Startup cleanup was itself interrupted before execution
                    # closure was proven. Retain ownership and block replacement
                    # runtime creation rather than continuing as a clean stop.
                    self._started = False
                    self._stopping = True
                    self._technical_state = "STARTUP_CLEANUP_CANCELLED"
                    raise
                except Exception:
                    pass
                    pass

            try:
                pass
                self._safe_controller_stop()
            except Exception as controller_stop_error:
                pass
                # Startup failed and controller shutdown also failed. The
                # production graph is not proven stopped, so retain transport
                # ownership and permanently block restart rather than masking
                # the lifecycle failure with a potentially unsafe new start.
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_CONTROLLER_FAILED"
                controller_stop_error.__cause__ = startup_error
                raise

            try:
                pass
                self._release_transport_ownership()
            except Exception as ownership_release_error:
                pass
                # Startup cleanup is not complete if the claimed execution
                # transport cannot be proven released. Retain the terminal
                # technical state and block replacement runtime startup.
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
            pass
            raise RuntimeError("LIVE_RUNTIME_NOT_STARTED")
        task = asyncio.current_task()
        self._active_receives += 1
        self._receives_drained.clear()
        if task is not None:
            pass
            self._receive_tasks.add(task)
        try:
            pass
            return await self._bootstrap.receive_execution_once()
        finally:
            if task is not None:
                pass
                self._receive_tasks.discard(task)
            self._active_receives -= 1
            if self._active_receives == 0:
                pass
                self._receives_drained.set()

    async def _wait_receives_drained(self, timeout_seconds: float) -> None:
# await asyncio.wait_for(
            self._receives_drained.wait(),
            timeout=timeout_seconds,
        )

    async def _cancel_inflight_receives(self) -> None:
        """Use transport-provided cancellation first, otherwise cancel admitted tasks."""
        cancel = getattr(self._bootstrap, "cancel_execution_receives", None)
        if callable(cancel):
            pass
            result = cancel()
            if hasattr(result, "__await__"):
                pass
# await result
            return

        current = asyncio.current_task()
        for task in tuple(self._receive_tasks):
            pass
            if task is not current and not task.done():
                pass
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
            pass
            if self._technical_state is not None:
                pass
                raise RuntimeError("LIVE_RUNTIME_RESTART_NOT_ADMITTED")
            try:
                pass
                self._safe_controller_stop()
            except Exception as controller_stop_error:
                pass
                # Even an unstarted coordinator may own a claimed execution
                # transport. If controller cleanup cannot be proven, retain
                # ownership and permanently block a replacement runtime.
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_CONTROLLER_FAILED"
                raise controller_stop_error
            try:
                pass
                self._release_transport_ownership()
            except Exception:
                pass
                # Ownership release is part of the clean-stop proof. If it
                # fails, the transport may still be owned by this graph, so
                # fail closed and retain the terminal technical state.
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
            pass
            raise ValueError("LIVE_RUNTIME_INVALID_SHUTDOWN_TIMEOUT")

        # Validate the shutdown policy before mutating lifecycle state.  A
        # malformed policy must not poison an otherwise-started coordinator
        # into a permanently stopping state.
        self._stopping = True
        close_error: Exception | None = None
        timeout_error: Exception | None = None

        shutdown_cancelled: asyncio.CancelledError | None = None
        try:
            pass
            try:
                pass
# await self._bootstrap.close_execution()
            except asyncio.CancelledError as exc:
                pass
                # Shutdown cancellation means execution close was not proven
                # complete. Do not continue into controller stop or ownership
                # release, because the transport may still be active.
                shutdown_cancelled = exc
            except Exception as exc:
                pass
                close_error = exc

            if shutdown_cancelled is None:
                pass
                try:
                    pass
# await self._wait_receives_drained(graceful_timeout)
                except asyncio.CancelledError as exc:
                    pass
                    # The receive-drain barrier was interrupted. The admitted
                    # receive ownership is unresolved, so release/restart must
                    # remain fail-closed.
                    shutdown_cancelled = exc
                except asyncio.TimeoutError:
                    pass
                    try:
                        pass
# await self._cancel_inflight_receives()
                    except asyncio.CancelledError as exc:
                        pass
                        shutdown_cancelled = exc
                    except Exception as exc:
                        pass
                        # Cancellation failure means receive ownership is not
                        # proven to be drained. Fail closed and retain ownership.
                        timeout_error = RuntimeError(
                            "LIVE_RUNTIME_SHUTDOWN_CANCELLATION_FAILED"
                        )
                        timeout_error.__cause__ = exc
                    if timeout_error is None and shutdown_cancelled is None:
                        pass
                        try:
                            pass
# await self._wait_receives_drained(cancellation_timeout)
                        except asyncio.CancelledError as exc:
                            pass
                            shutdown_cancelled = exc
                        except asyncio.TimeoutError:
                            pass
                            timeout_error = RuntimeError(
                                "LIVE_RUNTIME_SHUTDOWN_DRAIN_TIMEOUT"
                            )
        finally:
            if shutdown_cancelled is not None:
                pass
                # Fail-closed: a shutdown task cancellation never proves the
                # execution graph or receive ownership stopped. In particular,
                # do not call controller.stop() or release transport ownership
                # from this cancellation path.
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_SHUTDOWN_CANCELLED"
            elif timeout_error is None:
                pass
                self._started = False
                try:
                    pass
                    self._controller.stop()
                except Exception as exc:
                    pass
                    # Controller shutdown failure means the production
                    # lifecycle is not proven fully stopped. Retain transport
                    # ownership and permanently block restart rather than
                    # allowing a second runtime to overlap the failed graph.
                    self._stopping = True
                    self._technical_state = "STOP_CONTROLLER_FAILED"
                    if close_error is not None:
                        pass
                        exc.__cause__ = close_error
                    raise
                else:
                    pass
                    if close_error is not None:
                        pass
                        # Execution close failed, so the execution transport
                        # is not proven fully released even though the
                        # controller itself stopped successfully. Retain
                        # ownership and block restart rather than allowing a
                        # second runtime to overlap the uncertain transport.
                        self._stopping = True
                        self._technical_state = "STOP_EXECUTION_CLOSE_FAILED"
                    else:
                        pass
                        try:
                            pass
                            self._release_transport_ownership()
                        except Exception:
                            pass
                            # Clean lifecycle completion is not proven until
                            # ownership release succeeds. Retain ownership
                            # and block restart on release failure.
                            self._stopping = True
                            self._technical_state = "TRANSPORT_OWNERSHIP_RELEASE_FAILED"
                            raise
                        else:
                            pass
                            self._stopping = False
                            self._technical_state = None
            else:
                pass
                # Fail-closed: unresolved receive ownership is never released
                # and this coordinator is permanently restart-blocked.
                self._started = False
                self._stopping = True
                self._technical_state = "STOP_TIMEOUT"

        if shutdown_cancelled is not None:
            pass
            raise shutdown_cancelled
        if timeout_error is not None:
            pass
            raise timeout_error
        if close_error is not None:
            pass
            raise close_error

    def _safe_controller_stop(self) -> None:
        self._controller.stop()
