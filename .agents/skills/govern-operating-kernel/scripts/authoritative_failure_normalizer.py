#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
RULES=[('PERMISSION_DENIED',r'permission|access denied|forbidden'),('TOOL_TIMEOUT',r'timeout|timed out'),('RESOURCE_EXHAUSTED',r'out of memory|no space|quota'),('AUTHENTICATION_FAILED',r'unauthorized|authentication|invalid token'),('TOOL_SCHEMA_MISMATCH',r'schema|validation error|unexpected field'),('DEPENDENCY_FAILURE',r'connection refused|dependency|service unavailable'),('TEST_FAILURE',r'assertion|test failed'),('SECURITY_POLICY_VIOLATION',r'policy|egress|secret|injection')]
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('message'); a=ap.parse_args(); code='MODEL_BEHAVIOR_FAILURE'
 for c,p in RULES:
  if re.search(p,a.message,re.I): code=c; break
 print(json.dumps({'code':code,'message':a.message,'retryable':code in ['TOOL_TIMEOUT','DEPENDENCY_FAILURE','RESOURCE_EXHAUSTED']},indent=2))
if __name__=='__main__': main()
