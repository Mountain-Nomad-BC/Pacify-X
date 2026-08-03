#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,platform,shutil,subprocess
def cmd(x):
 try: return subprocess.check_output(x,text=True,stderr=subprocess.DEVNULL,timeout=3).strip()
 except Exception: return None
def main():
 argparse.ArgumentParser(description='Report bounded local hardware facts.').parse_args()
 mem=None
 try:
  for line in open('/proc/meminfo'):
   if line.startswith('MemTotal:'): mem=int(line.split()[1])*1024; break
 except (OSError, ValueError): mem=None
 gpus=cmd(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader,nounits'])
 print(json.dumps({'platform':platform.platform(),'python':platform.python_version(),'cpu_count_logical':os.cpu_count(),'memory_bytes':mem,'disk_free_bytes':shutil.disk_usage('.').free,'nvidia_gpus':gpus.splitlines() if gpus else [],'unknowns':[] if mem else ['total memory unavailable']},indent=2))
if __name__=='__main__': raise SystemExit(main() or 0)
