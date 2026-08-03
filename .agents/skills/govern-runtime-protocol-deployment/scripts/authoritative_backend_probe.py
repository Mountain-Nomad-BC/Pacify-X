#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,shutil,subprocess
BACKENDS={'llama.cpp':['llama-server','llama-cli'],'vllm':['vllm'],'sglang':['python'],'tensorrt-llm':['trtllm-build']}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--backend',choices=BACKENDS); a=ap.parse_args(); names=[a.backend] if a.backend else list(BACKENDS); out={}
 for b in names:
  bins={x:shutil.which(x) for x in BACKENDS[b]}; out[b]={'installed':any(bins.values()),'executables':bins,'capabilities':{'structured_output':'untested','tool_calling':'untested','prefix_cache':'untested','multimodal':'untested','speculative_decoding':'untested'}}
 print(json.dumps(out,indent=2))
if __name__=='__main__': main()
