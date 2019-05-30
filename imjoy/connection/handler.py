"""Provide socketio event handlers."""
from imjoy.const import NAME_SPACE
from imjoy.helper import get_psutil
from imjoy.runners.subprocess import (
    disconnect_client_session,
    disconnect_plugin,
    kill_all_plugins,
)

from .decorator import ws_handler as sio_on


def register_services(engine, register_event_handler):
    """Register services running by the engine."""
    # basic engine service
    register_event_handler(engine, connect)
    register_event_handler(engine, disconnect)
    register_event_handler(engine, on_reset_engine)
    register_event_handler(engine, on_get_engine_status)


@sio_on("connect", namespace=NAME_SPACE)
def connect(engine, sid, _):
    """Connect client."""
    logger = engine.logger
    logger.info("Connect %s", sid)


@sio_on("reset_engine", namespace=NAME_SPACE)
async def on_reset_engine(engine, sid, kwargs):
    """Reset engine."""
    logger = engine.logger
    registered_sessions = engine.store.registered_sessions
    logger.info("Kill plugin: %s", kwargs)
    if sid not in registered_sessions:
        logger.debug("Client %s is not registered", sid)
        return {"success": False, "error": "client has not been registered"}

    await kill_all_plugins(engine, sid)

    engine.conn.reset_store(reset_clients=False)

    return {"success": True}


@sio_on("get_engine_status", namespace=NAME_SPACE)
async def on_get_engine_status(engine, sid, _):
    """Return engine status."""
    logger = engine.logger
    plugins = engine.store.plugins
    registered_sessions = engine.store.registered_sessions
    if sid not in registered_sessions:
        logger.debug("Client %s is not registered", sid)
        return {"success": False, "error": "client has not been registered."}
    psutil = get_psutil()
    if psutil is None:
        return {"success": False, "error": "psutil is not available."}
    current_process = psutil.Process()
    children = current_process.children(recursive=True)
    pid_dict = {}
    for plugin in plugins.values():
        if plugin["process_id"] is not None:
            pid_dict[plugin["process_id"]] = plugin

    procs = []
    for proc in children:
        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
            if proc.pid in pid_dict:
                procs.append({"name": pid_dict[proc.pid]["name"], "pid": proc.pid})
            else:
                procs.append({"name": proc.name(), "pid": proc.pid})

    return {
        "success": True,
        "plugin_num": len(plugins),
        "plugin_processes": procs,
        "engine_process": current_process.pid,
    }


@sio_on("disconnect", namespace=NAME_SPACE)
async def disconnect(engine, sid):
    """Disconnect client."""
    logger = engine.logger
    disconnect_client_session(engine, sid)
    disconnect_plugin(engine, sid)
    logger.info("Disconnect %s", sid)
