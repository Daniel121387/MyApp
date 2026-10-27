# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A lightweight shopping-list web app (add / edit / delete / check items) built with Streamlit, to be deployed to Streamlit Community Cloud. All four stages of `PROMPTS.md` are done, and the bugs found in the stage-4 Playwright review are fixed.

- `PRD.md` — source of truth for requirements (features F-01–F-06, data model, UI layout, acceptance criteria in section 9). Check new work against it.
- `PROMPTS.md` — the 4-stage build plan (1: skeleton, 2: core features, 3: UI, 4: Playwright review).

The user writes in Korean; UI text and code comments are Korean as well.

Open issues against the PRD:
- With 100 items, adding one takes ~1.5 s (PRD 6 targets < 1 s). Toggle/delete are ~0.3 s. The server-side script run alone is ~0.6 s at 100 rows; the per-row cost hasn't been profiled yet. Adding a `key` back to row containers did not help.
- `app.py` is ~325 lines vs the PRD's 300-line target; the user has not yet decided whether to relax the target or compress the code.

## Commands

```bash
pip install -r requirements.txt               # streamlit is pinned to 1.58.0
streamlit run app.py                          # local dev, http://localhost:8501
streamlit run app.py --server.headless true   # for Playwright testing (run in background)
```

There is no test suite. Verify by running the app and driving it with Playwright. Back up `data/shopping_list.json` before tests that seed or wipe data, and restore it afterwards. `.streamlit/config.toml` turns off usage stats (otherwise CORS errors from the telemetry call show up in the browser console); changes to it need a server restart.

## Architecture (`app.py`)

- **The JSON file is the source of truth, not `session_state`.** `main()` reloads `data/shopping_list.json` on every rerun into `st.session_state["items"]` (a render-only cache). Every mutation goes through the `edit_items()` context manager: take lock → re-read file → mutate the list in place → save. Never write a session's own copy of the list back to the file, because that overwrote other tabs' changes. The lock comes from `@st.cache_resource` so it is shared across sessions; a module-level lock would be recreated on each rerun.
- `save_items` writes to `shopping_list.tmp` and then calls `os.replace`, so an interrupted write can't corrupt the file. `load_items` drops entries that fail `is_valid_item` (PRD section 4 model), so a hand-edited file can't crash rendering.
- The checkbox state is synced from the file each run (`st.session_state[f"check_{id}"] = item["checked"]`, with no `value=` argument). `set_checked` writes the widget's value rather than toggling, so stale tabs can't invert the state.
- Validation is in `validate()`, which checks name length with Python `len()` (code points). Widgets deliberately have **no** `max_chars` and **no** number_input `min_value`/`max_value`: `max_chars` counts UTF-16 units (an emoji counts as 2), and an out-of-range number_input traps keyboard focus.
- The add form has no `clear_on_submit`: `handle_add` clears the inputs only on success, so invalid input stays for correction. Because of that, a double-click submits twice; the `last_add` guard drops an identical (name, quantity) submission within 1 s.
- Callbacks report errors through `add_message` / `edit_message` in session state, which `show_message()` pops and renders next to the relevant form.
- The edit row is an `st.form` (Enter saves). While one row is in edit mode, the other rows' ✏️ buttons are disabled so unsaved edits are never silently discarded. `main()` clears `editing_id` if that item was deleted in another tab.
- Display order: unchecked first, then checked; within each group, by `created_at`.

## Streamlit pitfalls

- Address items by `id`, never by list index: the order changes as items get checked.
- Per-row widget keys include the item id (`check_`, `edit_`, `delete_`, `edit_name_`, `edit_quantity_`, `save_`, `cancel_`). Playwright tests locate rows through these `.st-key-<key>` classes.
- **Don't give row containers a per-item `key`.** Rapid clicks while a checked row moved left duplicate "ghost" rows in the DOM. Only the outer `item-list` container is keyed.
- `CUSTOM_CSS` stops Streamlit from stacking columns on mobile (≤640px). It targets `.st-key-add-area` / `.st-key-item-list` plus the internal test ids `stHorizontalBlock` / `stColumn`. Renaming those keys or upgrading Streamlit can silently break the mobile layout; re-check at 375px.
- Item names render via `st.html(html.escape(name))`: no markdown processing, so `*`, `<b>`, `$` and similar show literally.
- Use `on_click` / `on_change` callbacks for every state change, so updates don't show up one rerun late.
- Another tab's changes appear on this tab's next interaction or refresh; there is no live push.
- On Streamlit Cloud the JSON file is shared by all visitors and is wiped on restart. Durable per-user storage is the phase-2 option (PRD section 7.5).
