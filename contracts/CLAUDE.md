# Contracts

- Other parts of Franca rely on these files. Make a change here as a separate story, and update the tests in the same change.
- `openapi.yaml` is generated. To change it, change the server's routes, then run `scripts/update-contract`. oasdiff fails the build when there is a breaking change.
- `db/schema.sql` is built from `db/tables.sql` with `python3 contracts/db/build_schema.py`. Do not edit `schema.sql` by hand.
