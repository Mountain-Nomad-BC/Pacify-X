#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
from pathlib import Path
WRITE={'post','put','patch','delete'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('openapi'); ap.add_argument('--out',required=True); a=ap.parse_args(); spec=json.loads(Path(a.openapi).read_text()); tools=[]
 for path,item in spec.get('paths',{}).items():
  for method,op in item.items():
   if method.lower() not in {'get','post','put','patch','delete'}: continue
   destructive=method.lower()=='delete'; name=op.get('operationId') or re.sub(r'[^a-zA-Z0-9]+','_',method+'_'+path).strip('_')
   tools.append({'name':name,'method':method.upper(),'path':path,'risk_tier':'high' if destructive else 'medium' if method.lower() in WRITE else 'low','read_scope':[path] if method.lower()=='get' else [],'write_scope':[path] if method.lower() in WRITE else [],'network_scope':['api-base-url'],'requires_approval':destructive,'destructive':destructive,'idempotent':method.lower() in {'get','put','delete'},'input_schema':'generated/'+name+'.input.schema.json','output_schema':'generated/'+name+'.output.schema.json'})
 Path(a.out).write_text(json.dumps({'tools':tools},indent=2)+'\n'); print(json.dumps({'count':len(tools),'out':a.out},indent=2))
if __name__=='__main__': main()
