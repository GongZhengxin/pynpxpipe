# A5 Design: Integration & Polish

Date: 2026-04-08

## Goal

Rewrite `app.py` from the A1 spike prototype into a production layout that wires all 10 existing UI components into a coherent single-page application with navigation, error handling, and visual polish.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Layout structure | Sidebar tabs | Panel FastListTemplate has built-in sidebar; clean workflow separation; all sections always accessible |
| Configure section | Collapsible cards | pn.Card already used in pipeline_form; Session Paths + Subject expanded by default, others collapsed |
| Execute section | Vertical stack | Run controls → progress bars → log viewer; natural top-to-bottom reading flow |
| Theme | Dark + Blue accent | Familiar to scientists (VS Code / JupyterLab dark); easy on eyes during long pipeline runs |
| Navigation mechanism | Sidebar buttons with visibility toggle | Simple state management; no routing needed |

## Architecture

### Template

```python
pn.template.FastListTemplate(
    title="pynpxpipe",
    theme="dark",
    accent_base_color="#1f6feb",
    sidebar=[...],       # Navigation buttons + status
    main=[...],          # Active section content
)
```

### Sidebar Contents

1. **Navigation buttons**: Configure / Execute / Review — styled as `pn.widgets.Button` with active state highlighting
2. **Status indicator**: Shows `run_status` from AppState (idle/running/completed/failed)
3. **Version**: From package metadata

### Main Area Sections

Three `pn.Column` containers, one visible at a time based on sidebar selection:

**Configure** — Collapsible cards:
- SessionForm (expanded)
- SubjectForm (expanded)
- PipelineForm (collapsed)
- SortingForm (collapsed)
- StageSelector (collapsed)

**Execute** — Vertical stack:
- RunPanel (run/stop buttons + status text)
- ProgressView (7-stage progress bars)
- LogViewer (scrollable monospace log)

**Review** — Vertical stack:
- SessionLoader (output_dir input + Load button)
- StatusView (7-stage status table + Reset buttons)

### Section Switching

```python
# Sidebar button click → toggle visibility
def _switch_section(section_name: str) -> None:
    for name, col in sections.items():
        col.visible = (name == section_name)
```

### Error Handling

- Global error banner: `pn.pane.Alert` at top of main area, bound to `state.error_message`
- Hidden when empty, shows with `alert_type="danger"` when error_message is set
- Catches PynpxpipeError from pipeline execution (already handled in RunPanel._run_wrapper)

### Entry Point

Already configured in pyproject.toml:
```toml
pynpxpipe-ui = "pynpxpipe.ui.app:main"
```

`main()` calls `create_app()` → `pn.serve(template, ...)`.

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `src/pynpxpipe/ui/app.py` | Rewrite | Replace spike with FastListTemplate + all components |
| `tests/test_ui/test_app.py` | Update | Test create_app returns template, sections exist, navigation works, error banner |

## Components Wired (no changes needed)

All 10 existing components are used as-is via their `.panel()` method:
- session_form, subject_form, pipeline_form, sorting_form, stage_selector
- run_panel, progress_view, log_viewer
- status_view, session_loader

## Test Plan

| Test | Verifies |
|------|----------|
| `test_create_app_returns_viewable` | create_app() returns pn.viewable.Viewable |
| `test_has_three_sections` | Configure, Execute, Review sections exist |
| `test_default_section_is_configure` | Configure visible, others hidden on startup |
| `test_switch_to_execute` | Switching shows Execute, hides others |
| `test_switch_to_review` | Switching shows Review, hides others |
| `test_error_banner_hidden_initially` | Error banner not visible when error_message is empty |
| `test_error_banner_shows_on_error` | Error banner appears when state.error_message is set |
| `test_configure_has_five_forms` | Configure section contains all 5 form components |
| `test_execute_has_three_components` | Execute section contains RunPanel + ProgressView + LogViewer |
| `test_review_has_two_components` | Review section contains SessionLoader + StatusView |
| `test_main_function_exists` | main() entry point is callable |
