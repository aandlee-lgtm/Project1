# Working rules for this repository

- Treat the owner's feedback as feature requests: add each one to `docs/BACKLOG.md`
  (date, description, status "Planned").
- Do **not** build, bump the version, publish a DMG or create a release until the owner's message
  explicitly includes `build_new`. CI enforces this: the macOS build and release jobs only run when
  the commit message contains the exact marker `[build_new]` (with brackets). Never write that
  marker in any other commit message.
- On `build_new`: implement all Planned backlog items, run the unit and UI tests, bump the version,
  commit with `[build_new]` in the message, wait for the macOS acceptance tests, then add the release
  notes (commit message also containing `[build_new]`) to publish the Release.
