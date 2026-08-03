# PACIFY-X quickstart demonstration

PACIFY-X is the project and framework. `engineering-bootstrap` is its Python package and command-line control plane.

From a source checkout, run:

```text
python examples/quickstart/demo.py --output ../pacify-x-demo
```

The output path must not already exist. The demonstration performs:

1. framework validation;
2. preview-first new-project initialization;
3. task classification;
4. a bounded working-set selection of at most three capabilities;
5. one-skill hydration;
6. an existing-project commissioning dry run;
7. project verification;
8. a hash-sealed evidence receipt.

It uses no network and deletes nothing. It creates only `<output>/project/` and `<output>/evidence/demo-receipt.json`. Inspect the receipt to see each result and the declared effects.
