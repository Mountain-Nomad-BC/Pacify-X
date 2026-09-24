#!/usr/bin/env python3
import subprocess, sys, time
from pathlib import Path
pid_file = Path(sys.argv[1])
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
pid_file.write_text(str(child.pid), encoding="ascii")
try:
    time.sleep(60)
finally:
    if child.poll() is None:
        child.kill()
