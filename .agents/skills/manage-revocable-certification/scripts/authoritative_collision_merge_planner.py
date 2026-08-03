#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('duplicates'); a=ap.parse_args(); d=json.loads(Path(a.duplicates).read_text()); plans=[]
 for c in d.get('candidates',[]):
  exact=c.get('classification')=='exact-id'; s=c.get('similarity',0); action='merge-contracts-and-tests' if exact else 'review-complementary-merge' if s>=.6 else 'keep-separate-with-cross-reference'; plans.append({'left':c['left']['id'],'right':c['right']['id'],'action':action,'required_checks':['compare preconditions and invariants','union evidence contracts','resolve permission differences','preserve stronger tests','avoid duplicate registry IDs']})
 print(json.dumps({'plans':plans,'count':len(plans)},indent=2))
if __name__=='__main__': main()
