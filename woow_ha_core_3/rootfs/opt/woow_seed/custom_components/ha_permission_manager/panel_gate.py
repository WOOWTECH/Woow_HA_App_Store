"""The Panel Gate: the one place a panel map leaves Home Assistant.

`websocket_get_panels` in `homeassistant/components/frontend/__init__.py` is
the only place a panel map reaches a browser — nothing embedded in HTML, no
REST endpoint. This module takes that handler over, lets Home Assistant compute
its own answer, and deletes from the result the panels the asking user may not
see. A denied panel is then **absent**, not hidden: no route survives for a
bookmark or a `navigate()` to reach.

Three things make the takeover work, all verified against Home Assistant
2026.7.2 and recorded in ADR-0011:

- `async_register_command` does `handlers[command] = (handler, schema)`, and
  `ActiveConnection.__init__` takes `self.handlers = hass.data["websocket_api"]`
  as a **reference, not a copy**. So installing affects connections that
  already exist, and handing back takes effect without a restart.
- `send_message` is in `ActiveConnection.__slots__` and Home Assistant
  reassigns it itself in `async_handle_close()`, so swapping it for the
  duration of one call is a supported thing to do to a connection.
- `connection.user.is_admin` is readable before the answer is, so an
  administrator's response is passed through whatever the answer turns out to
  look like. That is the escape hatch that keeps the Permission Manager panel
  reachable when everything else here has failed.

Nothing in this module copies Home Assistant's own filtering, so a change to
`to_response()` or to `config_override` cannot silently make us wrong. And
nothing here decides *which* panels a user may see: that is
`panel_policy.visible_panel_ids()`, the same function `get_panel_permissions`
reports from, so the decision and the report cannot drift (#17).

When we are installed and cannot answer, we close: a non-administrator gets the
degraded set — the router fallback and their own account page — rather than
Home Assistant's unfiltered list. When we are not installed at all there is no
choice to make, Home Assistant serves its own list, and **disabling this
integration lifts every restriction**. That is deliberate, and it is why
failing to install is an error and a notification rather than a debug line.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.components import persistent_notification
from homeassistant.components.websocket_api import const as websocket_api_const
from homeassistant.components.websocket_api import messages as websocket_api_messages
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.debounce import Debouncer

from .const import DOMAIN
from .discovery import get_registered_panels
from .panel_policy import (
    PANELS_WITHOUT_PERMISSION,
    ROUTER_FALLBACK_PANELS,
    visible_panel_ids,
)

_LOGGER = logging.getLogger(__name__)

# Home Assistant's own event for "the panel list changed, ask again". The
# frontend's `subscribePanels` re-runs `get_panels` on it, and it is in the
# WebSocket API's SUBSCRIBE_ALLOWLIST — so unlike the Permission store's own
# announcement, which Home Assistant refuses a non-administrator (#13), this
# one reaches the user a revocation is actually about. That is the whole reason
# the Gate can tell a live page anything at all. Spelt once, here, and imported
# by __init__.py; the two events are not interchangeable and ADR-0011 says why.
EVENT_PANELS_UPDATED = "panels_updated"

# The command we take over, and the module the handler we expect belongs to.
GET_PANELS = "get_panels"
FRONTEND_MODULE = "homeassistant.components.frontend"

# Keys in hass.data[DOMAIN].
DATA_GATE = "panel_gate"
DATA_STORE_LOADED = "permissions_loaded"
DATA_FALLBACK_CHECKED = "panel_gate_fallback_checked"
DATA_DEBOUNCER = "panels_updated_debouncer"

# How long a burst of Permission writes is collapsed over, in seconds.
#
# It is the same number `async_save_permissions` gives `Store.async_delay_save`,
# because #19 asked for that — "debounced to match the store's own batching".
# **The two are not causally linked**, and it is worth being clear about that
# because the opposite is easy to assume: the Gate answers `get_panels` from the
# in-memory map in `hass.data[DOMAIN]`, which `_async_write` has already mutated
# by the time it calls here, and `async_delay_save` delays only the write to
# disk, which nothing reads again until a restart. There is no window in which a
# browser could re-read stale rows, and if there were, `immediate=True` would
# already be inside it — the leading edge goes out a whole cooldown before the
# save.
#
# What actually decides the number: long enough to collapse a run of
# back-to-back service calls, short enough that the trailing broadcast still
# arrives while somebody is looking at the page. One second does both.
# tests/test_panel_gate.py holds the two values equal as a tripwire, so that
# retuning the save delay is a decision about this one too rather than an
# accident.
PANELS_UPDATED_COOLDOWN = 1.0

NOTIFICATION_ID = "ha_permission_manager_panel_gate"
NOTIFICATION_TITLE = "Permission Manager: panel filtering"

# The Permission store, as `hass.data[DOMAIN]` keeps it. Read here as well as
# in websocket_api and __init__.py; unifying the three readers is a change of
# its own and ADR-0011 notes it.
DATA_PERMISSIONS = "permissions"


def _handlers(hass: HomeAssistant) -> dict[str, Any] | None:
    """Home Assistant's WebSocket handler registry, if it looks like one.

    The dict every `ActiveConnection` holds a reference to. One reader, so
    there is one place to change when Home Assistant changes how it keeps them.
    """
    handlers = hass.data.get(websocket_api_const.DOMAIN)
    if not isinstance(handlers, dict) or GET_PANELS not in handlers:
        return None
    return handlers


@callback
def async_install_panel_gate(hass: HomeAssistant) -> bool:
    """Take `get_panels` over. Returns whether the Gate is in place.

    Idempotent: `async_setup` installs before any config entry exists, and
    `async_setup_entry` installs again because a disable/enable cycle never
    runs `async_setup` a second time. Whichever gets there first wins and the
    other is a no-op.

    Returns False, loudly, when we are not in control — there is no
    `get_panels` handler, or the one registered is not Home Assistant's. Home
    Assistant then serves its own unfiltered list, which looks like a perfectly
    normal instance to everybody except the user who is supposed to be
    restricted.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_GATE) is not None:
        return True

    handlers = _handlers(hass)
    if handlers is None:
        _report(
            hass,
            "Home Assistant has no `get_panels` WebSocket handler to filter, so "
            "panel permissions are NOT being applied and every user can see "
            "every panel.",
        )
        return False

    original, schema = handlers[GET_PANELS]
    owner = getattr(original, "__module__", "")
    if owner != FRONTEND_MODULE:
        _report(
            hass,
            f"The `get_panels` WebSocket handler belongs to `{owner}`, not to "
            f"`{FRONTEND_MODULE}`. Something else is already wrapping it, so "
            "panel permissions are NOT being applied.",
        )
        return False

    _check_router_fallback(hass, final=False)

    handlers[GET_PANELS] = (_gated(original), schema)
    domain_data[DATA_GATE] = original
    _LOGGER.info("Panel Gate installed over %s.%s", owner, original.__name__)

    # Every browser already connected is holding Home Assistant's own answer,
    # asked for before we were here. `85d4977` caught exactly that in the act:
    # a page that reconnected during startup read the full list and had no
    # reason to ask again.
    hass.bus.async_fire(EVENT_PANELS_UPDATED)
    return True


@callback
def async_restore_panel_gate(hass: HomeAssistant) -> None:
    """Hand `get_panels` back, and tell every browser to ask Home Assistant.

    A reload is unload plus setup, so there is a millisecond window with the
    Gate off. Accepted, and recorded in ADR-0011.
    """
    domain_data = hass.data.get(DOMAIN, {})
    original = domain_data.get(DATA_GATE)
    if original is None:
        return

    # Everything below decides before the record is discarded. Popping first
    # would throw Home Assistant's own handler away down the two paths that
    # then decline to put it back, leaving a wrapper installed and nothing
    # left that knows what it wraps.
    handlers = _handlers(hass)
    if handlers is None:
        _LOGGER.warning("Panel Gate removed, but there is no `get_panels` to restore")
        return

    installed, schema = handlers[GET_PANELS]
    if getattr(installed, "_panel_gate", None) is not True:
        # Somebody registered over us while we were installed. Putting the
        # original back would delete theirs, which is the thing we complain
        # about when it is done to us.
        _report(
            hass,
            "The `get_panels` WebSocket handler was replaced while the Panel "
            "Gate was installed, so Home Assistant's own handler has not been "
            "restored. Restart Home Assistant to be sure what is answering.",
        )
        return

    handlers[GET_PANELS] = (original, schema)
    domain_data.pop(DATA_GATE, None)
    _LOGGER.info("Panel Gate removed; Home Assistant answers `get_panels` again")
    hass.bus.async_fire(EVENT_PANELS_UPDATED)


@callback
def async_panel_gate_store_loaded(hass: HomeAssistant) -> None:
    """The Permission store is readable. Say so, and reopen the question.

    Between installing and this call the Gate is running and cannot answer, so
    every non-administrator is refused (see `_result_for`). That window is one
    file read, but a browser that asked inside it is holding the degraded set
    and will not ask again on its own.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[DATA_STORE_LOADED] = True
    if domain_data.get(DATA_GATE) is None:
        return

    # The router-fallback check runs at install time, which on a cold start can
    # be before the panel registry is populated — and installing is idempotent,
    # so it would never be retried. Here it is, once the rest of startup has
    # happened, and by now an empty registry is a real answer rather than an
    # ordering artefact.
    if not domain_data.get(DATA_FALLBACK_CHECKED):
        _check_router_fallback(hass, final=True)

    hass.bus.async_fire(EVENT_PANELS_UPDATED)


async def async_broadcast_panels_changed(hass: HomeAssistant) -> None:
    """A Permission changed, so the panels somebody may receive may have too.

    Issue #19. The Permission store's own announcement cannot carry this: Home
    Assistant refuses a non-administrator's subscription to it (#13), and a
    revocation is *about* a non-administrator. `panels_updated` is in the
    WebSocket API's SUBSCRIBE_ALLOWLIST, so it is the one channel that reaches
    the user whose access just changed. With the Gate deciding, re-running
    `get_panels` is the whole of what their page has to do about it.

    Called from `_async_write()` in __init__.py — the single place this
    integration writes the Permission store — and from nowhere else, so a write
    path cannot be added that forgets it. It is called for **every** write,
    including one that touched no panel and one that changed nothing. A
    decision in front of the announcement is exactly how two of the five write
    paths came to be silent (#14, ADR-0010), and it would buy nothing here: the
    debounce already bounds the cost.

    **This is a global broadcast.** One user's Permission change makes every
    connected client re-run `get_panels`, not just the user it concerns. Home
    Assistant's event bus has no way to address one connection, and at
    household scale the cost is a handful of small round trips. Nobody should
    later read this as point-to-point.

    Debounced over PANELS_UPDATED_COOLDOWN, leading edge first: the write that
    starts a burst reaches an open page immediately, and everything within the
    following second collapses into one more broadcast. Measured on an instance
    at 2 broadcasts for 6 back-to-back writes, at 0.02 s and 1.02 s.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    debouncer = domain_data.get(DATA_DEBOUNCER)
    if debouncer is None:

        async def _announce() -> None:
            hass.bus.async_fire(EVENT_PANELS_UPDATED)

        debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=PANELS_UPDATED_COOLDOWN,
            immediate=True,
            function=_announce,
        )
        domain_data[DATA_DEBOUNCER] = debouncer

    await debouncer.async_call()


@callback
def async_stop_panel_broadcasts(hass: HomeAssistant) -> None:
    """Drop any broadcast still waiting on the debounce.

    A pending one must not outlive the integration that scheduled it: unload
    fires `panels_updated` itself, immediately, and a second one arriving a
    second later would tell every browser to re-read a panel list that nothing
    had changed again.

    Synchronous, because `Debouncer.async_shutdown` is a `@callback` and not a
    coroutine — `async_call` is the coroutine, `async_shutdown` and
    `async_cancel` are not. Awaiting it raises `TypeError: 'NoneType' object
    can't be awaited` out of `async_unload_entry`, which means the entry never
    unloads: the Gate stays installed, and disabling the integration silently
    does nothing. That is the escape hatch this whole design leans on, so the
    signature is written down here rather than remembered.
    """
    domain_data = hass.data.get(DOMAIN, {})
    debouncer = domain_data.pop(DATA_DEBOUNCER, None)
    if debouncer is not None:
        debouncer.async_shutdown()


# =============================================================================
# The wrap
# =============================================================================


def _gated(original: Callable[..., None]) -> Callable[..., None]:
    """Home Assistant's `get_panels`, with everybody else's answer filtered."""

    @callback
    def gated(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
        if connection.user.is_admin:
            # Not one key, and no swap at all — so there is nothing to be left
            # holding if the original throws on the way out.
            original(hass, connection, msg)
            return

        real_send = connection.send_message
        answered = False
        raised = False

        def intercept(message: Any) -> None:
            nonlocal answered
            answered = True
            # Put it back before doing any work of our own: whatever happens
            # next, this connection is not left filtering its own traffic.
            connection.send_message = real_send
            real_send(_result_for(hass, connection, msg["id"], message))

        connection.send_message = intercept
        try:
            original(hass, connection, msg)
        except Exception:  # noqa: BLE001 - a handler that raises must still close
            raised = True
            _LOGGER.exception("Home Assistant's `get_panels` raised behind the Panel Gate")
        finally:
            connection.send_message = real_send

        if answered:
            return

        if raised:
            # Already in the log, with its traceback. Only the notification is
            # owed, and it says which of the two happened.
            _notify(
                hass,
                "Home Assistant's `get_panels` raised, so non-administrators are "
                "receiving the degraded set — `notfound` and `profile`, and "
                "nothing else. See the log for the error.",
            )
        else:
            _report(
                hass,
                "Home Assistant's `get_panels` sent nothing while the Panel Gate "
                "was watching, so non-administrators are receiving the degraded "
                "set — `notfound` and `profile`, and nothing else.",
            )
        real_send(_degraded_message(hass, msg["id"]))

    gated._panel_gate = True  # what async_restore_panel_gate recognises
    return gated


def _result_for(
    hass: HomeAssistant, connection: Any, message_id: int, message: Any
) -> Any:
    """One `get_panels` response, with the panels this user may not see removed.

    Never raises: every way of not knowing the answer ends in the degraded set,
    because the alternative is handing a non-administrator Home Assistant's own
    list — which is exactly the fail-open #12 measured.
    """
    if not _is_result(message, message_id):
        _report(
            hass,
            "Home Assistant's `get_panels` answered in a shape the Panel Gate "
            "does not recognise, so non-administrators are receiving the "
            "degraded set — `notfound` and `profile`, and nothing else.",
        )
        return _degraded_message(hass, message_id)

    domain_data = hass.data.get(DOMAIN, {})
    if not domain_data.get(DATA_STORE_LOADED):
        # Installed, running, and not yet able to answer. Refusing is the whole
        # reason to install this early; the window closes at
        # async_panel_gate_store_loaded(). No notification: it is expected once
        # per start, and it corrects itself.
        _LOGGER.warning(
            "`get_panels` asked before the Permission store was loaded; "
            "refusing panels for user %s", connection.user.id
        )
        return _degraded_message(hass, message_id)

    try:
        offered = message["result"]
        panels = get_registered_panels(hass)
        visible = visible_panel_ids(
            panel_ids=offered.keys(),
            panels=panels,
            user_permissions=domain_data.get(DATA_PERMISSIONS, {}).get(
                connection.user.id, {}
            ),
            is_admin=False,
        )
        filtered = {
            panel_id: panel
            for panel_id, panel in offered.items()
            if panel_id in visible
        }
    except Exception:  # noqa: BLE001 - the decision failing must not fail open
        _LOGGER.exception("The Panel Gate could not decide; refusing panels")
        _notify(
            hass,
            "The Panel Gate could not decide which panels a user may see, so "
            "non-administrators are receiving the degraded set — `notfound` and "
            "`profile`, and nothing else. See the log for the error.",
        )
        return _degraded_message(hass, message_id)

    _LOGGER.debug(
        "Panel Gate: user %s offered %d panels, receives %d",
        connection.user.id, len(offered), len(filtered),
    )
    return websocket_api_messages.result_message(message_id, filtered)


def _is_result(message: Any, message_id: int) -> bool:
    """Whether this is the successful `get_panels` result we were waiting for.

    An error response is not one. It carries no panel map, so passing it
    through would leak nothing — but it also leaves the browser with no route
    at all, and it means the Gate is watching something it does not understand.
    Both are worth saying out loud, and the degraded set is the more usable of
    the two failures.
    """
    return (
        isinstance(message, dict)
        and message.get("type") == "result"
        and message.get("success") is True
        and message.get("id") == message_id
        and isinstance(message.get("result"), dict)
    )


def _degraded_message(hass: HomeAssistant, message_id: int) -> Any:
    """A refusal, in the shape of an answer.

    The router fallback and the user's own account page, built from the panel
    registry rather than from a literal — so if Home Assistant stops
    registering one of them this is smaller, rather than naming a panel that is
    not there.

    This is the last thing standing between a user and no answer at all, so it
    cannot raise: a registry it cannot read yields an empty result rather than
    an exception thrown back through Home Assistant's own handler, which is a
    request that never gets a reply.
    """
    degraded: dict[str, Any] = {}
    try:
        panels = get_registered_panels(hass)
        for panel_id in PANELS_WITHOUT_PERMISSION:
            panel = panels.get(panel_id)
            response = _panel_response(panel) if panel is not None else None
            if response is not None:
                degraded[panel_id] = response
    except Exception:  # noqa: BLE001 - a refusal must not raise on its way out
        _LOGGER.exception("Could not read the panel registry for the degraded set")
    return websocket_api_messages.result_message(message_id, degraded)


def _panel_response(panel: Any) -> Any:
    """One registered panel, as Home Assistant would put it in a result."""
    if isinstance(panel, dict):
        return panel
    to_response = getattr(panel, "to_response", None)
    if to_response is None:
        return None
    try:
        return to_response()
    except TypeError:
        # Home Assistant has taken a config override here — #16 quotes
        # `panel.to_response(config_override)` off the handler it read. Both
        # arities are answered rather than one of them guessed at.
        return to_response(None)
    except Exception:  # noqa: BLE001 - a refusal must not raise on its way out
        _LOGGER.exception("Could not render a panel for the degraded set")
        return None


# =============================================================================
# Saying so
# =============================================================================


def _check_router_fallback(hass: HomeAssistant, final: bool) -> None:
    """Is `notfound` actually registered? Issue #7 asks, and nothing checked.

    `ROUTER_FALLBACK_PANELS` keeps `notfound` without a Permission because Home
    Assistant resolves its default panel as `panels[default] ?? panels.home ??
    panels.notfound` and throws reading `.url_path` when all three are gone.
    The frontend could only assume that; the backend can look.

    A missing one is reported and does not stop the Gate installing. Refusing
    to install would lift every restriction on the instance in order to protect
    one router fallback, which is the worse of the two failures by a distance.

    `final` says whether an empty registry is an answer. At install time it is
    not — on a cold start the Gate goes in before the registry is filled — so
    the check goes unanswered and `async_panel_gate_store_loaded` asks again.
    Installing is idempotent, so without that second ask the check would simply
    never happen on such a boot, and #7 would be closed by a line that did not
    run.
    """
    panels = get_registered_panels(hass)
    if not panels:
        message = (
            "Home Assistant has registered no panels, so the Panel Gate cannot "
            "check that the router fallback `notfound` exists."
        )
        if final:
            _report(hass, message)
        else:
            _LOGGER.warning("%s Asking again once the Permission store loads.", message)
        return

    hass.data.setdefault(DOMAIN, {})[DATA_FALLBACK_CHECKED] = True
    missing = sorted(panel_id for panel_id in ROUTER_FALLBACK_PANELS if panel_id not in panels)
    if missing:
        _report(
            hass,
            f"Home Assistant has not registered {missing}, which the Panel Gate "
            "keeps unfiltered so a denied default panel still has a route. "
            "Expect routing errors on a restricted account.",
        )


def _report(hass: HomeAssistant, message: str) -> None:
    """An error in the log and a notification in the UI, for the same fact.

    Everything reported through here is a state in which this integration is
    not doing, or not fully doing, the one thing it exists for. A debug line
    would leave that looking like a working instance to everyone who is not the
    restricted user.
    """
    _LOGGER.error("%s", message)
    _notify(hass, message)


def _notify(hass: HomeAssistant, message: str) -> None:
    """The notification half, for a caller that has already said it in the log.

    One notification id, reused: each report replaces the last rather than
    stacking. Whoever reads them wants the current state of the Gate, and a
    handler that answers wrongly answers wrongly on every call.
    """
    persistent_notification.async_create(
        hass,
        message,
        title=NOTIFICATION_TITLE,
        notification_id=NOTIFICATION_ID,
    )
