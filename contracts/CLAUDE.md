# Contracts

- Other parts of Franca rely on these files. A change here is its own story, with the tests updated in the same change.
- `openapi.yaml` is generated: change the server's routes, then run `scripts/update-contract`. A breaking change fails the pipeline (oasdiff).
- `db/schema.sql` is built from `db/tables.sql` with `python3 contracts/db/build_schema.py`. Do not edit `schema.sql` by hand.
