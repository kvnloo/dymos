# Dymos #1239 fork-only diagnostic

AI-assisted research based on unchanged production source at
5bfbe394d251b5b7ccf510109648d576ecf4d390. The issue already has an owner;
this branch prepares independent evidence, not a competing upstream PR.

Eight real OpenMDAO/Dymos record-load_case cases compare baseline with the
reporter's proposed bounds-conversion strategy. Cases cover radians/degrees,
Kelvin/Celsius offsets, upper-only/lower-only bounds, unbounded state, same
units and genuine clipping. The candidate is applied to runner-local code only,
checked against the exact phase.py blob, and emitted as candidate.patch.

A green workflow requires the five expected baseline failures, three passing
controls, and all eight candidate cases passing. Unexpected errors fail the
comparison. Inspect the JSON receipts; this is not a full-suite pass.

No optimizer, ODE integration, spacecraft model, GPU or MPI is run. Controls,
vector-valued bounds, inferred units and changed interpolation grids are not
validated here. The script and candidate syntax are checked before execution.

Only this disposable branch replaces inherited workflows, avoiding unrelated
CI/publishing jobs. The fork default branch and upstream are not modified.
No comments or PRs are posted by the workflow. No schedule or secret is used.

Source issue: https://github.com/OpenMDAO/dymos/issues/1239
Contribution guidance: https://openmdao.org/dymos/docs/latest/contributing/contributing.html
