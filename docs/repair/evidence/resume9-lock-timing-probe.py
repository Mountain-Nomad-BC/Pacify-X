import sys, threading, time, tempfile, pathlib, traceback, faulthandler
sys.path.insert(0, str(pathlib.Path('.').resolve()))
faulthandler.dump_traceback_later(45, repeat=False)
import runtime.file_lock as FL
import runtime.operational_event_bus as OEB
from tests.test_operational_event_bus import _event

ROOT = pathlib.Path('.').resolve()
tmp = pathlib.Path(tempfile.mkdtemp())
bus = OEB.OperationalEventBus(ROOT, tmp / 'bus', tmp)
bus.publish(_event('seed', None))

spans = {}
meta = threading.local()

orig_enter, orig_exit = FL.FileLock.__enter__, FL.FileLock.__exit__
def enter(self):
    meta.name = self.path.name
    meta.t0 = time.perf_counter()
    try:
        out = orig_enter(self)
        meta.acq = time.perf_counter() - meta.t0
        return out
    except Exception as e:
        print(f'ENTER FAILED {threading.current_thread().name} after {time.perf_counter()-meta.t0:.2f}s {e}')
        raise

def exit_(self, *a):
    t = time.perf_counter()
    try:
        return orig_exit(self, *a)
    finally:
        if getattr(meta, 't0', None) is not None:
            spans.setdefault(threading.current_thread().name, []).append(
                (round(meta.acq, 2), round(time.perf_counter() - t, 2), round(time.perf_counter() - meta.t0, 2)))
            meta.t0 = None

FL.FileLock.__enter__, FL.FileLock.__exit__ = enter, exit_

def batch(i):
    t = time.perf_counter()
    try:
        bus.publish_batch([_event(f'x{i}a', None), _event(f'x{i}b', None)], link_current_head=True)
        print(threading.current_thread().name, 'ok', round(time.perf_counter() - t, 2))
    except Exception as e:
        print(threading.current_thread().name, 'FAIL', round(time.perf_counter() - t, 2), e)

ts = [threading.Thread(target=batch, args=(i,), name=f'b{i}') for i in range(4)]
[t.start() for t in ts]
[t.join(timeout=60) for t in ts]
print('alive', [t.name for t in ts if t.is_alive()])
for k, v in spans.items():
    print(k, 'acq/lock/release-total', v)
