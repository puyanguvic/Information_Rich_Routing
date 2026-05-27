# Public Release Checklist

Complete these items before making the repository public.

- Choose and add a formal open-source license.
- Add the final paper citation once the title/authors/venue metadata is fixed.
- Decide whether a separate archival result bundle is needed for full
  reproducibility.
- Confirm SR Linux image access instructions are accurate for external users.
- Re-run `make check` from a fresh clone.
- Re-run the ns-3 smoke test from a clean ns-3 checkout.
- Re-run at least one containerlab recovery trial on the target artifact machine.
