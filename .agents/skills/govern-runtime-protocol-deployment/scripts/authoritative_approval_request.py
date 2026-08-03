#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,uuid
from datetime import datetime,timezone,timedelta
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--action',required=True); ap.add_argument('--risk',required=True); ap.add_argument('--scope',required=True); ap.add_argument('--evidence',action='append',default=[]); ap.add_argument('--rollback',required=True); ap.add_argument('--expires-minutes',type=int,default=30); a=ap.parse_args(); print(json.dumps({'approval_id':'approval-'+uuid.uuid4().hex[:12],'action':a.action,'risk':a.risk,'scope':a.scope,'evidence':a.evidence,'rollback':a.rollback,'requested_at':datetime.now(timezone.utc).isoformat(),'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=a.expires_minutes)).isoformat(),'status':'pending'},indent=2))
if __name__=='__main__': main()
