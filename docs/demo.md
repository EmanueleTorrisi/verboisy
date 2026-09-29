# Demonstrations

Use `scripts/evaluate.py` for an opt-in, paid evaluation across six fixed source layouts
and schemas. It writes exact-match results, accepted records, provider tokens, request
units and elapsed time. Negative cases include absent websites and mixed entities.

The baseline receives the same captured evidence and a schema prompt. This controls
source availability but is not a comparison against every browser-enabled assistant.
Real-browser integration tests are separate. Synthetic fixture success alone does not
establish live-web recall, accuracy, runtime cost or site compatibility.
