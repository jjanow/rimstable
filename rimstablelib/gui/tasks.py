"""Background work for the GUI.

Read-only data (manifest, snapshots, diff) is computed in-process on a thread pool. Everything that changes
files runs the rimstable CLI as a child process, so the GUI goes through exactly the same checks as the
command line and its output can be shown live.
"""
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QRunnable, Qt, QThreadPool, Signal

from .. import core


def error_text(e):
    if isinstance(e, core.RimstableError):
        return str(e)
    if isinstance(e, subprocess.CalledProcessError):
        err = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        last = err.strip().splitlines()[-1:]
        return f"{Path(str(e.cmd[0])).name} failed" + (f": {last[0]}" if last else f" (exit {e.returncode})")
    if isinstance(e, FileNotFoundError) and e.filename:
        return f"not found: {e.filename}"
    return f"{type(e).__name__}: {e}"


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn, signals):
        super().__init__()
        self.fn, self.signals = fn, signals

    def run(self):
        try:
            result = self.fn()
        except Exception as e:  # shown to the user; the GUI must not die on a bad Steam folder
            self.signals.failed.emit(error_text(e))
        else:
            self.signals.done.emit(result)


_live = set()  # keeps signal objects alive until their task reports back


def run_async(fn, on_done, on_failed=None):
    """Run fn() on the thread pool; on_done(result) / on_failed(message) are called on the GUI thread."""
    sig = _Signals()
    _live.add(sig)
    sig.done.connect(on_done, Qt.QueuedConnection)
    if on_failed:
        sig.failed.connect(on_failed, Qt.QueuedConnection)
    sig.done.connect(lambda _: _live.discard(sig), Qt.QueuedConnection)
    sig.failed.connect(lambda _: _live.discard(sig), Qt.QueuedConnection)
    QThreadPool.globalInstance().start(_Task(fn, sig))


def child_python(gui=False):
    """Interpreter for CLI children. pythonw.exe has no stdout to stream, so use python.exe for piped runs;
    Qt starts it without a console window when the GUI itself has none. Detached runs (gui=True) keep pythonw
    so no console window pops up."""
    py = Path(sys.executable)
    if core.WINDOWS:
        con, win = py.with_name("python.exe"), py.with_name("pythonw.exe")
        if gui and win.exists():
            return win
        if not gui and py.name.lower() == "pythonw.exe" and con.exists():
            return con
    return py


def child_env():
    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONIOENCODING", "utf-8")
    env.insert("PYTHONUNBUFFERED", "1")
    env.remove("RIMSTABLE_REEXEC")
    return env


class CommandRunner(QObject):
    """Runs one `rimstable <args>` at a time and streams its merged output line by line."""
    started = Signal(list)
    output = Signal(str)
    finished = Signal(bool, str)  # ok, error message for the user

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = None
        self._buf = ""
        self._lines = []

    @property
    def busy(self):
        return self.proc is not None

    def run(self, args):
        if self.proc:
            return False
        p = QProcess(self)
        p.setProcessEnvironment(child_env())
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.setWorkingDirectory(str(core.APP_DIR))
        p.readyReadStandardOutput.connect(self._read)
        p.finished.connect(self._finished)
        p.errorOccurred.connect(self._error)
        self.proc, self._buf, self._lines = p, "", []
        self.started.emit(list(args))
        p.start(str(child_python()), ["-u", str(core.SCRIPT), *args])
        return True

    def _read(self):
        self._buf += bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        *lines, self._buf = self._buf.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        for line in lines:
            self._lines.append(line)
            self.output.emit(line)

    def _flush(self):
        self._read()
        if self._buf:
            self._lines.append(self._buf)
            self.output.emit(self._buf)
            self._buf = ""

    def _done(self, ok, msg):
        self.proc.deleteLater()
        self.proc = None
        self.finished.emit(ok, msg)

    def _finished(self, code, status):
        self._flush()
        ok = status == QProcess.NormalExit and code == 0
        self._done(ok, "" if ok else self._error_message(code, status))

    def _error(self, err):
        if err == QProcess.FailedToStart and self.proc:
            self._done(False, f"could not start {child_python()}: {self.proc.errorString()}")

    def _error_message(self, code, status):
        for i, line in enumerate(self._lines):
            if line.startswith("rimstable: "):
                return "\n".join([line[len("rimstable: "):]] + self._lines[i + 1:]).strip()
        if status != QProcess.NormalExit:
            return "the command crashed"
        tail = [line for line in self._lines if line.strip()][-6:]
        return "\n".join(tail) or f"exited with code {code}"


def launch_detached(log_dir):
    """Start `rimstable launch` so it outlives the GUI (on Linux it exec()s into RimWorld).
    Its output goes to files in log_dir; returns (ok, stderr_path)."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    out, err = log_dir / "launch.out", log_dir / "launch.err"
    p = QProcess()
    p.setProgram(str(child_python(gui=True)))
    p.setArguments(["-u", str(core.SCRIPT), "launch"])
    p.setWorkingDirectory(str(core.APP_DIR))
    p.setProcessEnvironment(child_env())
    p.setStandardOutputFile(str(out))
    p.setStandardErrorFile(str(err))
    r = p.startDetached()
    ok = r[0] if isinstance(r, tuple) else bool(r)
    return ok, err
