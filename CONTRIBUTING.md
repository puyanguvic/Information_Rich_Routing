# Contributing

Keep the repository usable as a compact research artifact.

## Before committing

Run:

```bash
make check
```

Do not commit:

- generated result directories under `results/`
- ns-3 build products
- Python bytecode or local virtual environments
- machine-local absolute paths
- raw large experiment outputs unless they are deliberately added as a small
  fixture

## License

Contributions to this repository are expected to be compatible with
`GPL-2.0-only`, matching the ns-3 simulator license.

## Code organization

- Keep ns-3 source in `ns3/contrib/information-routing/` so it can be copied or
  symlinked directly into an ns-3 checkout.
- Keep SR Linux/containerlab artifacts under `containerlab/`.
- Keep paper-facing aggregation and plotting scripts separate from experiment
  source code.
- Prefer relative paths from the repository root. For external results, use
  environment variables documented in `README.md`.

## Result files

Small trace fixtures belong in `traces/`. Full experiment results should remain
outside Git and be regenerated or published through a separate artifact archive.
