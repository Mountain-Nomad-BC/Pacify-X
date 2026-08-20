# Calculation evidence

Trace inputs, dimensions, conversions, derived values, thresholds, branches, flags, outputs, and consumers before changing a formula. Use `runtime.foundation_assurance.validate_dimension_steps` for declared add, subtract, multiply, and divide steps; it checks dimensional algebra without evaluating source text.

Test zero, boundary, negative-when-valid, large finite, missing, non-numeric, non-finite, unit-conversion, threshold-adjacent, and failure-mode cases. Use replay/scenario fixtures when available. A dimensionally valid expression can still be semantically wrong, so require domain evidence and output-contract tests.
