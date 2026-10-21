# Embedded skills

This directory contains skills that are available to the ticket assistant at runtime.

- `vendor/superpowers`: the public `obra/superpowers` skill collection, vendored with its MIT license and source commit.
- `local/to-tickets`: a locally authored compatibility implementation for the requested `mattpocock/to-tickets` behavior. The supplied upstream URL was not publicly accessible, so this directory must not be described as an upstream copy.

The backend loader only accepts `SKILL.md` files under this directory. See `backend/app/skills/loader.py`.
