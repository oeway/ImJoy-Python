"""Provide a worker template."""
import argparse
import inspect
import logging
import math
import os
import sys
import threading
from functools import reduce
from types import ModuleType

from imjoySocketIO_client import LoggingNamespace, SocketIO, find_callback
from worker_utils import ReferenceStore, debounce, dotdict, get_psutil, set_interval

if sys.version_info >= (3, 0):
    import asyncio
    import janus
    from worker_utils3 import FuturePromise
    from worker3 import task_worker

    PYTHON3 = True
else:
    from worker_utils import Promise
    from worker import task_worker

    PYTHON3 = False

try:
    import queue
except ImportError:
    import Queue as queue

ARRAY_CHUNK = 1000000
logger = logging.getLogger("plugin")


def kill(proc_pid):
    """Kill process id."""
    psutil = get_psutil()
    if psutil is None:
        return

    process = psutil.Process(proc_pid)
    for proc in process.children(recursive=True):
        proc.kill()
    process.kill()


def ndarray(typedArray, shape, dtype):
    """Return a ndarray."""
    _dtype = type(typedArray)
    if dtype and dtype != _dtype:
        raise Exception(
            "dtype doesn't match the type of the array: " + _dtype + " != " + dtype
        )
    shape = shape or (len(typedArray),)
    return {
        "__jailed_type__": "ndarray",
        "__value__": typedArray,
        "__shape__": shape,
        "__dtype__": _dtype,
    }


api_utils = dotdict(
    ndarray=ndarray, kill=kill, debounce=debounce, set_interval=set_interval
)


class PluginConnection:
    """Represent a plugin connection."""

    def __init__(
        self,
        pid,
        secret,
        server,
        job_queue=None,
        loop=None,
        worker=None,
        namespace="/",
        work_dir=None,
        daemon=False,
        api=None,
    ):
        """Set up connection."""
        if work_dir is None or work_dir == "" or work_dir == ".":
            self.work_dir = os.getcwd()
        else:
            self.work_dir = work_dir
            if not os.path.exists(self.work_dir):
                os.makedirs(self.work_dir)
            os.chdir(self.work_dir)
        socketIO = SocketIO(server, Namespace=LoggingNamespace)
        self.socketIO = socketIO
        self.init = False
        self.secret = secret
        self.id = pid
        self.daemon = daemon

        def emit(msg):
            socketIO.emit("from_plugin_" + secret, msg)

        self.emit = emit

        self.local = {}
        _remote = dotdict()
        self._setLocalAPI(_remote)
        self.interface = {}
        self.plugin_interfaces = {}
        self.remote_set = False
        self.store = ReferenceStore()
        self.executed = False
        self.queue = job_queue
        self.loop = loop

        self.init = False
        sys.stdout.flush()
        socketIO.on("to_plugin_" + secret, self.sio_plugin_message)
        self.emit({"type": "initialized", "dedicatedThread": True})
        logger.info("Plugin %s initialized", pid)

        def on_disconnect():
            if not self.daemon:
                self.exit(1)

        socketIO.on("disconnect", on_disconnect)
        self.abort = threading.Event()
        self.worker = worker

    def wait_forever(self):
        """Wait forever."""
        if PYTHON3:
            self.sync_q = self.queue.sync_q
            fut = self.loop.run_in_executor(None, self.socketIO.wait)
            t = [
                self.worker(self, self.queue.async_q, logger, self.abort)
                for i in range(10)
            ]
            self.loop.run_until_complete(asyncio.gather(*t))
            self.loop.run_until_complete(fut)
        else:
            self.sync_q = queue.Queue()
            t = threading.Thread(target=self.socketIO.wait)
            t.daemon = True
            t.start()
            self.worker(self, self.sync_q, logger, self.abort)

    def default_exit(self):
        """Exit default."""
        logger.info("Terminating plugin: %s", self.id)
        self.abort.set()
        os._exit(0)

    def exit(self, code):
        """Exit."""
        if "exit" in self.interface:
            try:
                self.interface["exit"]()
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Error when exiting: %s", exc)
                sys.exit(1)
            else:
                logger.info("Terminating plugin")
                sys.exit(code)
        else:
            sys.exit(0)

    def _encode(self, aObject):
        """Encode object."""
        if aObject is None:
            return aObject
        if type(aObject) is tuple:
            aObject = list(aObject)
        isarray = type(aObject) is list
        bObject = [] if isarray else {}
        # skip if already encoded
        if (
            type(aObject) is dict
            and "__jailed_type__" in aObject
            and "__value__" in aObject
        ):
            return aObject

        # encode interfaces
        if (
            type(aObject) is dict
            and "__id__" in aObject
            and "__jailed_type__" in aObject
            and aObject["__jailed_type__"] == "plugin_api"
        ):
            encoded_interface = {}
            for k in aObject.keys():
                v = aObject[k]
                if callable(v):
                    bObject[k] = {
                        "__jailed_type__": "plugin_interface",
                        "__plugin_id__": aObject["__id__"],
                        "__value__": k,
                        "num": None,
                    }
                    encoded_interface[k] = v
            self.plugin_interfaces[aObject["__id__"]] = encoded_interface
            return bObject

        keys = range(len(aObject)) if isarray else aObject.keys()
        for k in keys:
            v = aObject[k]
            try:
                basestring
            except NameError:
                basestring = str
            if callable(v):
                interfaceFuncName = None
                for name in self.interface:
                    if self.interface[name] == v:
                        interfaceFuncName = name
                        break
                if interfaceFuncName is None:
                    cid = self.store.put(v)
                    vObj = {"__jailed_type__": "callback", "__value__": "f", "num": cid}
                else:
                    vObj = {
                        "__jailed_type__": "interface",
                        "__value__": interfaceFuncName,
                    }

            # send objects supported by structure clone algorithm
            # https://developer.mozilla.org/en-US/docs/Web/API/Web_Workers_API/Structured_clone_algorithm
            # if (
            #   v !== Object(v) ||
            #   v instanceof Boolean ||
            #   v instanceof String ||
            #   v instanceof Date ||
            #   v instanceof RegExp ||
            #   v instanceof Blob ||
            #   v instanceof File ||
            #   v instanceof FileList ||
            #   v instanceof ArrayBuffer ||
            #   v instanceof ArrayBufferView ||
            #   v instanceof ImageData
            # ) {
            # }
            elif "np" in self.local and isinstance(
                v, (self.local["np"].ndarray, self.local["np"].generic)
            ):
                vb = bytearray(v.tobytes())
                if len(vb) > ARRAY_CHUNK:
                    vl = int(math.ceil(1.0 * len(vb) / ARRAY_CHUNK))
                    v_bytes = []
                    for i in range(vl):
                        v_bytes.append(vb[i * ARRAY_CHUNK : (i + 1) * ARRAY_CHUNK])
                else:
                    v_bytes = vb
                vObj = {
                    "__jailed_type__": "ndarray",
                    "__value__": v_bytes,
                    "__shape__": v.shape,
                    "__dtype__": str(v.dtype),
                }
            elif type(v) is dict or type(v) is list:
                vObj = self._encode(v)
            elif not isinstance(v, basestring) and type(v) is bytes:
                vObj = v.decode()  # covert python3 bytes to str
            elif isinstance(v, Exception):
                vObj = {"__jailed_type__": "error", "__value__": str(v)}
            else:
                vObj = {"__jailed_type__": "argument", "__value__": v}

            if isarray:
                bObject.append(vObj)
            else:
                bObject[k] = vObj

        return bObject

    def _decode(self, aObject, callbackId, withPromise):
        """Decode object."""
        if aObject is None:
            return aObject
        if "__jailed_type__" in aObject and "__value__" in aObject:
            if aObject["__jailed_type__"] == "callback":
                bObject = self._genRemoteCallback(
                    callbackId, aObject["num"], withPromise
                )
            elif aObject["__jailed_type__"] == "interface":
                name = aObject["__value__"]
                if name in self._remote:
                    bObject = self._remote[name]
                else:
                    bObject = self._genRemoteMethod(name)
            elif aObject["__jailed_type__"] == "plugin_interface":
                bObject = self._genRemoteMethod(
                    aObject["__value__"], aObject["__plugin_id__"]
                )
            elif aObject["__jailed_type__"] == "ndarray":
                # create build array/tensor if used in the plugin
                try:
                    np = self.local["np"]
                    if isinstance(aObject["__value__"], bytearray):
                        aObject["__value__"] = aObject["__value__"]
                    elif isinstance(aObject["__value__"], list) or isinstance(
                        aObject["__value__"], tuple
                    ):
                        aObject["__value__"] = reduce(
                            (lambda x, y: x + y), aObject["__value__"]
                        )
                    else:
                        raise Exception(
                            "Unsupported data type: ",
                            type(aObject["__value__"]),
                            aObject["__value__"],
                        )
                    bObject = np.frombuffer(
                        aObject["__value__"], dtype=aObject["__dtype__"]
                    ).reshape(tuple(aObject["__shape__"]))
                except Exception as exc:
                    logger.debug("Error in converting: %s", exc)
                    bObject = aObject
                    raise exc
            elif aObject["__jailed_type__"] == "error":
                bObject = Exception(aObject["__value__"])
            elif aObject["__jailed_type__"] == "argument":
                bObject = aObject["__value__"]
            else:
                bObject = aObject["__value__"]
            return bObject
        else:
            if isinstance(aObject, tuple):
                aObject = list(aObject)
            isarray = isinstance(aObject, list)
            bObject = [] if isarray else dotdict()
            keys = range(len(aObject)) if isarray else aObject.keys()
            for k in keys:
                if isarray or k in aObject:
                    v = aObject[k]
                    if isinstance(v, dict) or isinstance(v, list):
                        if isarray:
                            bObject.append(self._decode(v, callbackId, withPromise))
                        else:
                            bObject[k] = self._decode(v, callbackId, withPromise)
            return bObject

    def _wrap(self, args):
        """Wrap arguments."""
        wrapped = self._encode(args)
        result = {"args": wrapped}
        return result

    def unwrap(self, args, withPromise):
        """Unwrap arguments."""
        if "callbackId" not in args:
            args["callbackId"] = None
        # wraps each callback so that the only one could be called
        result = self._decode(args["args"], args["callbackId"], withPromise)
        return result

    def setInterface(self, api):
        """Set interface."""
        if isinstance(api, dict):
            api = {a: api[a] for a in api.keys() if not a.startswith("_")}
        elif inspect.isclass(type(api)):
            api = {a: getattr(api, a) for a in dir(api) if not a.startswith("_")}
        else:
            raise Exception("unsupported api export")
        if "exit" in api:
            ext = api["exit"]

            def exit_wrapper():
                try:
                    ext()
                finally:
                    self.default_exit()

            api["exit"] = exit_wrapper
        else:
            api["exit"] = self.default_exit
        self.interface = api
        self.send_interface()

    def send_interface(self):
        """Send interface."""
        names = []
        for name in self.interface:
            if callable(self.interface[name]):
                names.append({"name": name, "data": None})
            else:
                data = self.interface[name]
                if data is not None and isinstance(data, dict):
                    data2 = {}
                    for k in data:
                        if callable(data[k]):
                            data2[k] = "**@@FUNCTION@@**:" + k
                        else:
                            data2[k] = data[k]
                    names.append({"name": name, "data": data2})
                elif type(data) in [str, int, float, bool]:
                    names.append({"name": name, "data": data})
        self.emit({"type": "setInterface", "api": names})

    def _genRemoteMethod(self, name, plugin_id=None):
        """Return remote method."""

        def remoteMethod(*arguments, **kwargs):
            # wrap keywords to a dictionary and pass to the first argument
            if len(arguments) == 0 and len(kwargs) > 0:
                arguments = [kwargs]

            def p(resolve, reject):
                resolve.__jailed_pairs__ = reject
                reject.__jailed_pairs__ = resolve
                call_func = {
                    "type": "method",
                    "name": name,
                    "pid": plugin_id,
                    "args": self._wrap(arguments),
                    "promise": self._wrap([resolve, reject]),
                }
                self.emit(call_func)

            if PYTHON3:
                return FuturePromise(p, self.loop)
            else:
                return Promise(p)

        remoteMethod.__remote_method = True
        return remoteMethod

    def _genRemoteCallback(self, id_, argNum, withPromise):
        """Return remote callback."""
        if withPromise:

            def remoteCallback(*arguments, **kwargs):
                # wrap keywords to a dictionary and pass to the first argument
                if len(arguments) == 0 and len(kwargs) > 0:
                    arguments = [kwargs]

                def p(resolve, reject):
                    resolve.__jailed_pairs__ = reject
                    reject.__jailed_pairs__ = resolve
                    self.emit(
                        {
                            "type": "callback",
                            "id": id_,
                            "num": argNum,
                            # 'pid'  : self.id,
                            "args": self._wrap(arguments),
                            "promise": self._wrap([resolve, reject]),
                        }
                    )

                if PYTHON3:
                    return FuturePromise(p, self.loop)
                else:
                    return Promise(p)

        else:

            def remoteCallback(*arguments, **kwargs):
                # wrap keywords to a dictionary and pass to the first argument
                if len(arguments) == 0 and len(kwargs) > 0:
                    arguments = [kwargs]
                ret = self.emit(
                    {
                        "type": "callback",
                        "id": id_,
                        "num": argNum,
                        # 'pid'  : self.id,
                        "args": self._wrap(arguments),
                    }
                )
                return ret

        return remoteCallback

    def set_remote(self, api):
        """Set remote."""
        _remote = dotdict()
        for i in range(len(api)):
            if isinstance(api[i], dict) and "name" in api[i]:
                name = api[i]["name"]
                data = api[i].get("data", None)
                if data is not None:
                    if isinstance(data, dict):
                        data2 = dotdict()
                        for key in data:
                            if key in data:
                                if data[key] == "**@@FUNCTION@@**:" + key:
                                    data2[key] = self._genRemoteMethod(name + "." + key)
                                else:
                                    data2[key] = data[key]
                        _remote[name] = data2
                    else:
                        _remote[name] = data
                else:
                    _remote[name] = self._genRemoteMethod(name)

        self._setLocalAPI(_remote)
        return _remote

    def _setLocalAPI(self, _remote):
        """Set local API."""
        _remote["export"] = self.setInterface
        _remote["utils"] = api_utils
        _remote["WORK_DIR"] = self.work_dir

        self.local["api"] = _remote

        # make a fake module with api
        m = ModuleType("imjoy")
        sys.modules[m.__name__] = m
        m.__file__ = m.__name__ + ".py"
        m.api = _remote

    def sio_plugin_message(self, *args):
        """Handle plugin message."""
        data = args[0]
        if data["type"] == "import":
            self.emit({"type": "importSuccess", "url": data["url"]})
        elif data["type"] == "disconnect":
            self.abort.set()
            callback, args = find_callback(args)
            try:
                if "exit" in self.interface and callable(self.interface["exit"]):
                    self.interface["exit"]()
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Error when exiting: %s", exc)
            if callback:
                callback(*args)
        elif data["type"] == "execute":
            if not self.executed:
                self.sync_q.put(data)
            else:
                logger.debug("Skip execution")
                self.emit({"type": "executeSuccess"})
        elif data["type"] == "message":
            d = data["data"]
            self.sync_q.put(d)
            logger.debug("Added task to the queue")
        sys.stdout.flush()


def main():
    """Run script."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=str, required=True, help="plugin id")
    parser.add_argument("--secret", type=str, required=True, help="plugin secret")
    parser.add_argument("--namespace", type=str, default="/", help="socketio namespace")
    parser.add_argument(
        "--work_dir", type=str, default=".", help="plugin working directory"
    )
    parser.add_argument(
        "--server", type=str, default="http://127.0.0.1:9527", help="socketio server"
    )
    parser.add_argument("--daemon", action="store_true", help="daemon mode")
    parser.add_argument("--debug", action="store_true", help="debug mode")

    opt = parser.parse_args()

    if "" not in sys.path:
        sys.path.insert(0, "")

    imjoy_path = os.path.dirname(os.path.normpath(__file__))
    if imjoy_path not in sys.path:
        sys.path.insert(0, imjoy_path)

    logging.basicConfig(stream=sys.stdout)
    logger.setLevel(logging.INFO)
    if opt.debug:
        logger.setLevel(logging.DEBUG)

    if PYTHON3:
        event_loop = asyncio.get_event_loop()
        job_queue = janus.Queue(loop=event_loop)
    else:
        event_loop = None
        job_queue = None

    plugin_conn = PluginConnection(
        opt.id,
        opt.secret,
        server=opt.server,
        work_dir=opt.work_dir,
        job_queue=job_queue,
        loop=event_loop,
        worker=task_worker,
    )
    plugin_conn.wait_forever()


if __name__ == "__main__":
    main()
