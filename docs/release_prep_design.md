# GitHub Release Preparation — Design

**Date:** 2026-04-14
**Status:** Design approved, pending user review of spec
**Repo:** https://github.com/GongZhengxin/pynpxpipe.git

## Goal

Prepare pynpxpipe for public release on GitHub so that other Windows users can install it via `uv add git+<repo>.git` without cloning the whole development tree.

## Decisions

| Topic | Choice |
|---|---|
| Distribution mode | Git-based install (PyPI deferred) |
| License | MIT |
| README style | "Storefront" — concise intro + link to `getting_started.md` |
| README language | Bilingual (English + 中文) |
| Branch name | Rename local `master` → `main` before push |
| Unrelated WIP changes | Left untouched; only release-relevant files committed |
| Build backend | Keep `uv_build` (change deferred until PyPI publish) |

## Scope

### Files to create
1. **`LICENSE`** — Standard MIT text, copyright 2026 GongZhengxin.
2. **`README.md`** — Bilingual (EN + 中文), ~100 lines. Sections: one-line intro, Features, Installation, Quick Start, Documentation links, License.

### Files to modify
1. **`.gitignore`** — Replace the 12-line stub with a full exclude list covering: Python/uv cache, tool working dirs (`.claude/`, `.superpowers/`, `.prompt4claude/`, graphify), IDE, runtime outputs (`kilosort4_output/`, `logs/`, `*.nwb`, `*.zarr/`, `*.mat`), private dirs (`legacy_reference/`, `spec_manifests/`, `tests/fixtures/bhv2_ground_truth/`, `docs/audit/`, `docs/bug_spec/`, `docs/temp/`, `docs/superpowers/`), and private subject YAMLs (`monkeys/*.yaml` with `!monkeys/MonkeyTemplate.yaml` exception).
2. **`pyproject.toml`** — Add `license`, `keywords`, `classifiers`, `[project.urls]` (Homepage/Repository/Issues). Do NOT change `build-backend`.
3. **`getting_started.md`** — Rewrite §1 (Install) to show both "consumer mode" (`uv add git+...`) and "developer mode" (`git clone + uv sync`). Add short subsections describing the new UI features (Figures Viewer, Chat Help, SubjectForm save button). Other sections unchanged.
4. **`CLAUDE.md`** — Update the "current development phase" paragraph; add `src/pynpxpipe/agent/` to the directory tree. Do not touch development workflow rules or spec index table (agent module is UI-auxiliary, not a pipeline stage).
5. **`docs/progress.md`** — Append UI S6 (Chat Help), UI S7 (Figures Viewer), UI S8 (SubjectForm save-yaml). Record the two bug fixes (`imec_sync_code` removal, `nblocks` default). Update total test count from 972 → 1160 (verified via `uv run pytest --collect-only`).

### Files NOT modified
Everything else in the current `git status` M list stays untouched. The release commit touches only the files above plus `LICENSE`/`README.md` creation.

## Untracked-files cleanup

Before committing, run `git ls-files` against the new `.gitignore` exclude list to find items that are already tracked but should be excluded. For each, `git rm --cached <path>` (removes from index, keeps on disk). Expected candidates: none major, but verify.

## Commit strategy

Two commits on the new `main` branch, each scoped to one concern:

1. **`chore(release): add LICENSE, README, .gitignore; update pyproject metadata`**
   — Creates LICENSE, README.md, replaces .gitignore, updates pyproject.toml metadata.

2. **`docs(release): refresh getting_started, CLAUDE, progress for public release`**
   — Updates the three docs.

Rationale: splits license/metadata from docs so reviewers can see each clearly. Both commits are self-contained and reversible.

## Branch rename & push

1. `git branch -m master main`
2. `git remote add origin https://github.com/GongZhengxin/pynpxpipe.git`
3. Show `git status` + list of files to be pushed for user confirmation.
4. Wait for explicit user go-ahead.
5. `git push -u origin main`

## Risks / Notes

- **Unrelated WIP will NOT be pushed** because those files stay `modified` in the working tree and are never `git add`-ed. They remain local until the user decides what to do with them.
- **`uv.lock` is committed** (already tracked) — guarantees reproducible `uv sync` for developers.
- **No history rewrite** — if something sensitive is already in git history, we keep it there (accept the tradeoff) rather than `git filter-branch`. User has confirmed nothing sensitive is historically tracked.
- **README bilingual ordering**: English section first (international reach), then 中文. Both sections self-contained.

## Verification before reporting done

- `git status` shows unrelated M files still modified (not committed)
- `git log --oneline -5` shows the two new commits on `main`
- `git ls-files | grep -E '\.(claude|superpowers|prompt4claude)'` returns empty
- `git ls-files | grep 'tests/fixtures/bhv2_ground_truth'` returns empty
- `git ls-files | grep 'legacy_reference'` returns empty
- Remote is added but **push is not yet executed** — that requires user confirmation in a separate step.

## Out of scope

- PyPI publish (deferred)
- License headers in source files (MIT is inferred from `LICENSE` file, no per-file headers)
- CI/CD workflow file (`.github/workflows/ci.yml`) — exists or not, untouched this round
- History rewriting or force-push
- Any changes to the 45 unrelated modified files
