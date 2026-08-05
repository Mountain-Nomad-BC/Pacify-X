#!/usr/bin/env python3
from __future__ import annotations
import argparse
import ast
import json
from pathlib import Path


class Mut(ast.NodeTransformer):
    def __init__(self, target):
        self.i = 0
        self.target = target
        self.changed = False

    def visit_BinOp(self, n):
        self.generic_visit(n)
        if isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            if self.i == self.target:
                n.op = {
                    ast.Add: ast.Sub,
                    ast.Sub: ast.Add,
                    ast.Mult: ast.Add,
                    ast.Div: ast.Mult,
                }[type(n.op)]()
                self.changed = True
            self.i += 1
        return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t = ast.parse(Path(a.source).read_text())
    m = Mut(a.index)
    t = m.visit(t)
    ast.fix_missing_locations(t)
    if not m.changed:
        raise SystemExit("mutation target not found")
    Path(a.out).write_text(ast.unparse(t) + "\n")
    print(json.dumps({"mutated": a.out, "index": a.index}, indent=2))


if __name__ == "__main__":
    main()
