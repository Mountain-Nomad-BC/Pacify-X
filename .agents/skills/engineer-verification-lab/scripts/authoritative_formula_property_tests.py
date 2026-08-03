#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,random
def kv(l,b,t,h,d,z): return 2*l*b*t*h*d*z
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--cases',type=int,default=1000); ap.add_argument('--seed',type=int,default=17); a=ap.parse_args(); r=random.Random(a.seed); failures=[]
 for i in range(a.cases):
  l,b,t,h,d,z=[r.randint(1,m) for m in [200,16,100000,256,512,4]]; base=kv(l,b,t,h,d,z)
  if kv(l,b,t+1,h,d,z)<=base: failures.append({'case':i,'property':'monotonic_tokens'})
  if kv(l,b,t,h,d,z)!=kv(l,b,t,h,d,z): failures.append({'case':i,'property':'deterministic'})
 print(json.dumps({'cases':a.cases,'failures':failures,'status':'PASS' if not failures else 'FAIL'},indent=2)); raise SystemExit(0 if not failures else 1)
if __name__=='__main__': main()
