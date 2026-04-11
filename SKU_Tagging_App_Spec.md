# SKU Tagging System — Full Feature & Code Specification

> Based on `app_old.py` — the reference implementation before pagination changes.

---

## 1. Application Setup

### Imports
- **Streamlit:** `streamlit`, `streamlit_tags` (`st_tags`), `streamlit.components.v1`
- **Data:** `pandas`, `numpy`, `json`
- **AI:** `openai.AzureOpenAI`
- **Utils:** `gpt_call`, `gpt_call_with_usage`, all prompt functions from `utils.py`
- **Embeddings:** `build_bt_embeddings`, `get_sku_embeddings`, `find_similar_basic_types_batch`, `load_cache` from `embedding_utils.py`
- **Env:** `dotenv`, `os`, `requests`, `datetime`

### Page Config
- `layout="wide"`, sidebar starts collapsed
- Title: "🏷️ SKU Tagging System"

### Required Environment Variables
- `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME`  
- Optional: `AZURE_OPENAI_API_VERSION` (default `2024-02-01`), `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`, `GOOGLE_SHEETS_WEBAPP_URL`
- App stops with error if any required var is missing.

---

## 2. Session State Variables

| Key | Type | Default | Purpose |
|-----|------|---------|---------|
| `sku_data` | `list[dict]` / `None` | `None` | Main data store. Each dict: `{sku_name, category, basic_type, generic_keywords: []}` |
| `category_df` | `DataFrame` / `None` | `None` | Unique categories from BT_CT_mappings |
| `bt_df` | `DataFrame` / `None` | `None` | Unique basic types from BT_GK_mappings |
| `gk_df` | `DataFrame` / `None` | `None` | All unique generic keywords, flattened from BT_GK_mappings |
| `mapping_cat_bt_df` | `DataFrame` / `None` | `None` | Raw BT_CT_mappings (col 0 = Basic Type, col 1 = Category) |
| `mapping_bt_gk_df` | `DataFrame` / `None` | `None` | Raw BT_GK_mappings (col 0 = Basic Type, col 1 = GKs as parsed list) |
| `api_usage_stats` | `list[dict]` | `[]` | Chronological log of every GPT call |
| `total_session_cost` | `float` | `0.0` | Running total USD cost |
| `total_session_tokens` | `int` | `0` | Running total tokens consumed |
| `session_id` | `str` | 8-char UUID | For Google Sheets logging |
| `suggested_new_bts` | `dict` | `{}` | `{sku_idx: {suggested_bt, category, sku_name, closest_existing_bt}}` — GPT-suggested new BTs |
| `multi_cat_bts` | `dict` | `{}` | `{bt_name: [cat1, cat2, ...]}` — BTs belonging to >1 category |
| `needs_category_review` | `set` | `set()` | SKU indices whose BT maps to multiple categories |
| `accepted_new_bts` | `dict` | `{}` | `{bt_name: {category, generic_keywords, source_sku}}` — accepted new BTs pending export |
| `gk_version` | `int` | `0` | Counter to force st_tags re-render after GPT keyword updates |
| `sheets_loaded` | `bool` | `False` | Prevents re-fetching Google Sheets on every rerun |
| `uploaded_file_name` | `str` | `None` | Detects new file uploads |

### Per-SKU Widget State Keys (initialized during upload)
- `cat_{idx}` — Category selectbox value
- `bt_{idx}` — Basic Type data mirror
- `bt_select_{idx}` — Actual BT selectbox widget key
- `bt_custom_{idx}` — Custom BT text input value
- `tags_{idx}` — Generic keywords list for st_tags
- `accept_new_bt_{idx}` — Boolean flag set by "✓" accept button callback

---

## 3. Google Sheets Integration

### Spreadsheet Structure

**Spreadsheet ID:** `1-1DejLMWTf7YbUNKVa84fIiguL1XXb14wKJ-w28yOh4`

The app interacts with the following sheets (tabs) in this spreadsheet:

#### Sheet: `BT_CT_mappings` (gid: `1757740042`)
Maps Basic Types to Category Types.

| Column | Name | Description |
|--------|------|-------------|
| A (col 0) | Basic Tag Type | The basic type name (e.g., "Butter", "Milk") |
| B (col 1) | Category Tag Type | The category (e.g., "Dairy", "Groceries") |

- A basic type can appear in multiple rows if it belongs to multiple categories (e.g., "Butter" → "Dairy" and "Butter" → "Groceries").
- **Read at startup** to populate `mapping_cat_bt_df`, `category_df`, `multi_cat_bts`.
- **Written to** when new basic types are added via `add_new_bt_to_mappings()` or `update_bt_ct_mappings()`.

#### Sheet: `BT_GK_mappings` (gid: `1433148032`)
Maps Basic Types to their Generic Keywords.

| Column | Name | Description |
|--------|------|-------------|
| A (col 0) | Basic Type | The basic type name |
| B (col 1) | GKs | Generic keywords stored as a stringified Python list, e.g., `['Cereal', 'Baby Care', 'Baby Cereal', ...]` |

- One row per basic type. The GK column contains ALL keywords for that BT in a single cell as a string representation of a list.
- After loading, `safe_parse_list()` converts the stringified lists into actual Python lists.
- **Read at startup** to populate `mapping_bt_gk_df`, `bt_df`, `gk_df`.
- **Written to** when:
  - New GKs are added to existing BTs via `update_bt_gk_mappings()` (appends keywords to existing list in the cell)
  - New BTs are added via `add_new_bt_to_mappings()` (appends a new row)

#### Sheet: `GPT Token Costs`
Logs every GPT API call's token usage and cost.

| Column | Name |
|--------|------|
| A | Timestamp |
| B | Session ID |
| C | Operation (e.g., "Find BT and CT", "Find Generic Keywords") |
| D | Batch Info (e.g., "SKUs 1-15") |
| E | Model |
| F | Prompt Tokens |
| G | Completion Tokens |
| H | Total Tokens |
| I | Input Cost (USD) |
| J | Output Cost (USD) |
| K | Total Cost (USD) |
| L | SKU Count |
| M | Notes |

- **Write-only** from the app via `log_gpt_cost_to_sheets()`.
- Created automatically by the Google Apps Script if it doesn't exist.

#### Sheet: `BT_Update_Log`
Logs all basic type additions/changes.

| Column | Name |
|--------|------|
| A | Timestamp |
| B | Session ID |
| C | Basic Type |
| D | Category |
| E | Action (e.g., "added", "accepted") |
| F | Generic Keywords |
| G | Source SKU |

- **Write-only** from the app via `log_new_bt_update()`.
- Created automatically by the Google Apps Script if it doesn't exist.

#### Sheet: `GK_Update_Log`
Logs when new generic keywords are added to existing basic types.

| Column | Name |
|--------|------|
| A | Timestamp |
| B | Session ID |
| C | Basic Type |
| D | Added Keywords |
| E | Status |

- **Write-only** — logged automatically by the Apps Script when `handleBtGkMappingUpdate` runs.
- Created automatically by the Apps Script if it doesn't exist.

#### Sheet: `GPT Costs Summary` (optional)
Auto-generated summary with formulas (total calls, total tokens, total cost, cost per operation).

---

### Read Operations (no auth, public CSV export)
- **`load_google_sheet(spreadsheet_id, sheet_gid)`** — Downloads CSV via `https://docs.google.com/spreadsheets/d/{id}/export?format=csv&gid={gid}`, returns `pd.DataFrame`.
- **Reads on startup** (when `sheets_loaded` is `False`):
  1. `BT_CT_mappings` → `mapping_cat_bt_df` → derive `category_df`, `multi_cat_bts`
  2. `BT_GK_mappings` → `mapping_bt_gk_df` → derive `bt_df`, `gk_df`
- Can be re-triggered via sidebar button "🔄 Reload Mapping Data" (resets `sheets_loaded` to `False`).

### Write Operations (via Google Apps Script Web App)
All POST JSON to `GOOGLE_SHEETS_WEBAPP_URL`. The Apps Script (`google_apps_script.js`) routes by `action` field in `doPost()`. All functions silently return `False` if URL is empty.

| # | Python Function | Apps Script `action` | Target Sheet(s) | When Triggered | Timeout |
|---|----------------|---------------------|-----------------|----------------|---------|
| 1 | `log_gpt_cost_to_sheets(usage_stats, operation_details)` | _(default, no action field)_ | `GPT Token Costs` | After every GPT API call (BT+Category batches, GK per-SKU calls) | 10s |
| 2 | `update_bt_gk_mappings(bt_gk_updates)` | `update_bt_gk_mappings` | `BT_GK_mappings` + `GK_Update_Log` | On CSV export — syncs manually added GKs for **existing** BTs | 30s |
| 3 | `update_bt_ct_mappings(bt_ct_updates)` | `update_bt_ct_mappings` | `BT_CT_mappings` | On CSV export — adds new BT→Category rows | 30s |
| 4 | `log_new_bt_update(bt_name, category, sku_name, action)` | `log_bt_update` | `BT_Update_Log` | On CSV export — logs each new BT addition | 10s |
| 5 | `add_new_bt_to_mappings(bt_name, category, generic_keywords)` | `add_new_basic_type` | `BT_CT_mappings` + `BT_GK_mappings` + `BT_Update_Log` | On CSV export — adds a completely new BT to both mapping sheets | 30s |

### How the Apps Script Handles Each Action

1. **Default (GPT cost logging):** Appends a row to `GPT Token Costs` with formatted timestamp, tokens, costs.
2. **`update_bt_gk_mappings`:** Finds the BT row in `BT_GK_mappings`, parses the existing keywords list from the cell, appends new keywords (deduped), writes updated stringified list back to the cell. Logs to `GK_Update_Log`.
3. **`update_bt_ct_mappings`:** Appends new `[basic_type, category]` rows to `BT_CT_mappings`.
4. **`add_new_basic_type`:** Appends `[basic_type, category]` to `BT_CT_mappings` AND `[basic_type, stringified_keywords]` to `BT_GK_mappings`. Also logs to `BT_Update_Log`.
5. **`log_bt_update`:** Appends a row to `BT_Update_Log` with timestamp, session_id, BT, category, action, and source SKU.

### Complete Data Flow: Google Sheets ↔ App

```
STARTUP (READ):
  Google Sheets                           App Session State
  ─────────────                           ──────────────────
  BT_CT_mappings ──CSV export──→ mapping_cat_bt_df
                                  ├─→ category_df (unique categories)
                                  └─→ multi_cat_bts (BTs in >1 category)
  
  BT_GK_mappings ──CSV export──→ mapping_bt_gk_df
                                  ├─→ bt_df (unique basic types)
                                  └─→ gk_df (all individual keywords, flattened)

DURING USE (WRITE - per GPT call):
  App ──POST──→ Apps Script ──→ GPT Token Costs sheet

ON EXPORT (WRITE):
  New BTs detected?
    YES → App ──POST (add_new_basic_type)──→ Apps Script
            ├──→ BT_CT_mappings (new row: BT, Category)
            ├──→ BT_GK_mappings (new row: BT, [keywords])
            └──→ BT_Update_Log (audit row)
    
  New GKs on existing BTs?
    YES → App ──POST (update_bt_gk_mappings)──→ Apps Script
            ├──→ BT_GK_mappings (update cell: append keywords to existing list)
            └──→ GK_Update_Log (audit row)
```

---

## 4. Helper Functions

### `safe_parse_list(value)`
Parses stringified lists from Google Sheets cells:
1. Returns as-is if `None`, `NaN`, or not a string
2. If starts with `[` or `{`: tries `json.loads` (with `'` → `"` replacement), then `ast.literal_eval`
3. Returns value unchanged if parsing fails

### `get_existing_gk_for_basic_type(basic_type)`
Looks up `mapping_bt_gk_df` where col 0 == basic_type. Returns col 1 as a `set` of keyword strings. Handles nested lists (list-of-lists). Returns empty set if no mapping found.

---

## 5. Data Loading Sequence

Triggered when `sheets_loaded` is `False`. Can be re-triggered via sidebar button "🔄 Reload Mapping Data".

1. **Load BT_CT_mappings** → `mapping_cat_bt_df`. Apply `safe_parse_list` to all object-dtype columns.
2. **Load BT_GK_mappings** → `mapping_bt_gk_df`. Apply `safe_parse_list` to all object-dtype columns. The GK column (col 1) becomes actual Python lists.
3. **Extract `category_df`**: Unique values from `mapping_cat_bt_df.iloc[:, 1]`.
4. **Detect `multi_cat_bts`**: Group by BT (col 0), get unique categories per BT. Store BTs with >1 category as `{bt_name: [cat1, cat2]}`.
5. **Extract `bt_df`**: Unique values from `mapping_bt_gk_df.iloc[:, 0]`.
6. **Extract `gk_df`**: Flatten all keyword lists from `mapping_bt_gk_df` col 1, deduplicate, sort. Each row should be an individual keyword string.
7. Set `sheets_loaded = True`.
8. Display load status in sidebar: `"✅ All mapping data loaded (5/5)"` or `"⚠️ X/5"`.

---

## 6. Sidebar Configuration

### Batch Processing Config
| Setting | Range | Default | Purpose |
|---------|-------|---------|---------|
| Category Batch Size | 1–50 | 30 | SKUs per GPT call for categories |
| Basic Type Batch Size | 1–50 | 20 | SKUs per GPT call for basic types |
| BT & Category Batch Size | 1–50 | 15 | SKUs per GPT call for combined BT+Category |

### Embedding Config
| Setting | Range | Default | Purpose |
|---------|-------|---------|---------|
| Top-K Similar BTs | 5–100 | 30 | BTs to shortlist via cosine similarity |
| Embedding BT Batch Size | 1–50 | 15 | SKUs per GPT call in embedding flow |

### API Usage Stats
- Metrics: Total Tokens, Total Cost
- Expander: Last 10 GPT calls with operation, batch, tokens, cost
- Reset button: Clears all stats and reruns

---

## 7. SKU Upload & Initialization

- `st.file_uploader` accepting CSV only.
- Column detection: Uses `'name'` column if present, otherwise first column.
- **New-file detection**: Compares `uploaded_file.name` to stored `uploaded_file_name`, plus checks length mismatch on `sku_data`.
- **Initialization loop** (when new file detected): Creates `sku_data` list and initializes all per-SKU widget state keys (`cat_{idx}`, `bt_{idx}`, `tags_{idx}`).
- If no file uploaded → warning + `st.stop()`.

---

## 8. Auto-Tagging: Find Basic Type and Category

### Button: "🔍 Find Basic Type and Category"

**Pre-work:**
- Builds `all_basic_types` list from `mapping_cat_bt_df.iloc[:, 0].unique()`
- Builds `bt_to_category` dict (BT → Category, last-wins for duplicates)
- Clears `suggested_new_bts` and `needs_category_review`

**Batch processing**: Iterates in chunks of `BT_CATEGORY_BATCH_SIZE`.

**GPT call**: `batch_basictype_category_prompt(batch_skus, all_basic_types, bt_to_category)`

**What the prompt does**: Groups all BTs by category (e.g., `"Fruits: [Apple, Banana]"`) and asks GPT to:
- Pick the best existing BT + its category for each SKU
- If no existing BT matches, set `is_new_bt: true` and suggest a `suggested_bt` name
- Output JSON: `{"results": [{"sku", "basic_type", "category", "is_new_bt", "suggested_bt"}, ...]}`

**Result parsing per SKU:**
1. Strip markdown code fences from response
2. Parse JSON, iterate `batch_results`
3. Find matching SKU index in the batch range (linear scan by `sku_name`)
4. Update `sku_data[idx]` fields: `basic_type`, `category`
5. Update widget state: `bt_{idx}`, `bt_select_{idx}`, `cat_{idx}`
6. **Multi-category check**: If BT is in `multi_cat_bts` → add `idx` to `needs_category_review`, print `[REVIEW]` log
7. **New BT suggestion**: If `is_new_bt` and `suggested_bt` → store in `suggested_new_bts[idx]` with `{suggested_bt, category, sku_name, closest_existing_bt: basic_type}`

**Post-loop:**
- Show success message with token/cost summary
- Show info banner if any new BTs were suggested: "💡 X SKUs have suggested new basic types"
- Call `st.rerun()`

---

## 9. Auto-Tagging: Find Generic Keywords

### Button: "🏷️ Find Generic Keywords"

**Processes each SKU individually** (not batched). Only runs for SKUs with a non-empty `basic_type`.

**Keyword lookup per SKU:**
1. Get **primary keywords**: From `mapping_bt_gk_df` where col 0 == `item['basic_type']` → `gk_list`. Flatten nested lists.
2. Get **extended keywords**: Find all BTs in the same category via `mapping_cat_bt_df`. Collect their GKs from `mapping_bt_gk_df`. Remove duplicates and items already in `gk_list`.

**GPT call**: `generic_keyword_prompt(sku_name, category, basic_type, gk_list)` — sends only primary keywords (not extended).

**Result parsing:**
1. Strip code fences
2. Parse `selected_generic_keywords` from JSON
3. Handle two response formats:
   - New format: `[{"keyword": "...", "confidence": "..."}]` → extract `keyword` field
   - Old format: `["keyword1", "keyword2"]` → use directly
4. Update `sku_data[idx]['generic_keywords']` and `st.session_state[f"tags_{idx}"]`

**Post-loop:**
- Increment `gk_version` (forces `st_tags` widgets to re-render with new key suffix `_v{gk_version}`)
- Show success with token/cost
- Call `st.rerun()`

---

## 10. Table Rendering

### Dropdown Option Lists
- `category_options`: `[''] + category_df['Category'].tolist()`
- `bt_options`: `[''] + bt_df.iloc[:, 0].tolist()`
- `gk_options`: `gk_df.iloc[:, 0].tolist()` — flat list of individual keyword strings (used as suggestions)

### Debug Info Expander
- Shows count of assigned categories, sample assignments
- Validates assigned categories exist in dropdown options (✅/❌ per category, plus similar matches)
- `st.warning` if any assigned categories are missing from dropdown

### Custom CSS (injected via `st.markdown(unsafe_allow_html=True)`)
- Remove bottom margin on selectboxes/text inputs
- 5px column padding
- Disabled text inputs forced to black text (overrides grey)
- **Multi-category highlighting**: `div:has(.cat-needs-review) div[data-baseweb="select"] > div` → red border + box-shadow
- Gap removal in category column when review warning present
- Gap removal in Generic Keywords column (5th child)
- Constrain `st_tags` iframe width within 5th column

### JavaScript Iframe Fix (`components.html`, height=0)
A `setInterval(500ms)` script that:
1. Iterates all `<iframe>` elements in parent document
2. Finds iframes with `.rti--container` (st_tags internals)
3. Injects CSS to constrain widths, enable `flex-wrap`, hide overflow
4. Clears residual text in unfocused `.rti--input` elements using native setter + synthetic events

### `_render_keywords_fragment(idx, gk_options)` — decorated with `@st.fragment`
- Renders `st_tags` widget in isolation (prevents full-page rerun on rapid edits)
- Key: `tags_{idx}_v{gk_version}` — version suffix forces re-render after GPT updates
- **Normalization**: Capitalizes first letter of each keyword, deduplicates case-insensitively
- **Duplicate toast**: Shows `st.toast("⚠️ '{kw}' already exists in row {idx+1}")` for duplicates
- Writes normalized list back to `sku_data[idx]['generic_keywords']`

### Column Layout: `[0.3, 3, 1.7, 1.7, 3.8]`
Headers: `#`, `SKU Name`, `Category`, `Basic Type`, `Generic Keywords`

### Table Header Row
Rendered once with `st.columns` + bold markdown. Then `st.divider()`.

---

## 11. Per-Row Rendering (for each SKU)

### Column 0: Row Number
- Bold `{idx + 1}`

### Column 1: SKU Name
- `st.text_input` with `disabled=True`, key `sku_{idx}`, collapsed label
- CSS makes disabled text black (not grey)

### Column 2: Category Selectbox
- **Initialize**: `cat_{idx}` in session state if missing
- **Multi-category check**: Dynamically checks current BT (`bt_select_{idx}`) against `multi_cat_bts`
- **If multi-category**:
  - Inject hidden `<div class="cat-needs-review">` — CSS `:has()` selector highlights selectbox with red border + glow
  - After selectbox: show warning `"⚠️ {BT} in: Cat1, Cat2"` in small red text
- **Selectbox**: `key=f"cat_{idx}"`, `options=category_options`, collapsed label
- **No `index` parameter**: Value managed entirely via session state (avoids Streamlit warning about conflicting index + session state)
- **Sync back**: If selected value differs from `sku_data[idx]['category']`, update it

### Column 3: Basic Type Selectbox + Suggestions

#### BT Filtering by Category
- If category is set: filter `mapping_cat_bt_df` to BTs in that category → `bt_suggestions = [''] + filtered_bt + ['➕ Type new...']`
- Otherwise: `bt_options + ['➕ Type new...']`

#### Accept Suggestion Logic (runs BEFORE selectbox renders)
- Checks `accept_new_bt_{idx}` flag
- If `True`:
  1. Read suggestion from `suggested_new_bts[idx]`
  2. Set `sku_data[idx]['basic_type']` = suggested_bt
  3. Set `bt_select_{idx}` = suggested_bt
  4. Add to `accepted_new_bts[suggested_bt]` = `{category, generic_keywords: [], source_sku}`
  5. Remove from `suggested_new_bts[idx]`
  6. Reset flag to `False`

#### Custom Value in Dropdown
- If `current_bt` is not in `dropdown_options` (e.g., from GPT or typed), it's inserted before `'➕ Type new...'`

#### Selectbox
- Key: `bt_select_{idx}`, initialized once to `current_bt` if in options, else `''`
- Same session-state-only pattern as category

#### "➕ Type new..." Handling
When selected:
- Shows `st.text_input` (key `bt_custom_{idx}`, placeholder "Type new basic type...")
- On input:
  1. Update `sku_data[idx]['basic_type']` to the custom value
  2. Sync `bt_select_{idx}` to the custom value
  3. Add to `accepted_new_bts` with category (or `'Uncategorized'`)

#### Suggestion Display
If `idx` in `suggested_new_bts`:
- Two-column layout `[2, 1]`:
  - Left: Blue styled text `"💡 {suggested_bt}"` (small font, bold)
  - Right: Small "✓" button with `on_click` callback that sets `accept_new_bt_{idx} = True`

### Column 4: Generic Keywords
- Calls `_render_keywords_fragment(idx, gk_options)`
- Users can select from existing suggestions and type new keywords
- New keywords get auto-capitalized and deduplicated

### Row Spacer
- `<div style='margin: 5px 0;'>` after each row

---

## 12. Suggested New Basic Types — Complete Flow

1. **Detection**: During "Find BT & Category" GPT call. If GPT returns `is_new_bt: true`, the SKU gets `closest_existing_bt` as `basic_type`, and `suggested_new_bts[idx]` stores the suggestion details.
2. **Display**: Below the BT selectbox — blue `💡` text + `✓` button.
3. **Acceptance**: `✓` button's `on_click` sets `accept_new_bt_{idx} = True`. On next rerun, code updates `sku_data`, `bt_select_{idx}`, adds to `accepted_new_bts`, removes from `suggested_new_bts`.
4. **Export**: `detect_new_basic_types()` also catches manually typed BTs. On CSV download, calls `add_new_bt_to_mappings()` and `log_new_bt_update()` for each, then clears `accepted_new_bts`.

---

## 13. Multi-Category Basic Type Warnings — Complete Flow

1. **Detection**: During Sheets load, `multi_cat_bts` populated by grouping `mapping_cat_bt_df` by BT column, keeping entries with >1 unique category.
2. **Flagging**: During "Find BT & Category", if assigned BT is in `multi_cat_bts`, SKU index added to `needs_category_review` with `[REVIEW]` console log.
3. **Display**: In Category column, dynamically checks *current* BT (`bt_select_{idx}`) against `multi_cat_bts` (not just initial assignment). If match:
   - Hidden marker div → CSS red border + glow on category selectbox
   - Warning text: `"⚠️ {BT} in: Cat1, Cat2"`
4. **User action**: User manually selects the correct category from the dropdown.

---

## 14. Generic Keywords — Adding Manual/New Keywords

### Via `st_tags` widget (in `_render_keywords_fragment`)
- Users type free text into the st_tags input field
- The widget allows both selecting from `suggestions` (gk_options) AND typing new values
- On change:
  1. First letter capitalized
  2. Case-insensitive deduplication
  3. Duplicate → toast warning
  4. Normalized list written back to `sku_data[idx]['generic_keywords']`

### New Keywords Tracked for Export
- `detect_new_gk_mappings()` compares each SKU's current `generic_keywords` against `get_existing_gk_for_basic_type(basic_type)`
- Returns `{bt_name: [new_keywords]}` for keywords not in the original mapping
- Displayed in "🆕 New Generic Keywords Detected" expander before export
- On export: `update_bt_gk_mappings()` syncs new keywords to Google Sheets (only for existing BTs — new BTs get their keywords via `add_new_bt_to_mappings`)

---

## 15. Export Functionality

### `detect_new_basic_types()`
- Scans all `sku_data` for BTs not in `bt_df`
- Returns `{bt_name: {category, generic_keywords: list, source_sku}}`
- Aggregates generic keywords across all SKUs using the same new BT

### `detect_new_gk_mappings()`
- For each SKU, compares current keywords vs. `get_existing_gk_for_basic_type()`
- Returns `{bt_name: [new_keywords]}`

### Pre-Export Display
- **"🆕 New Generic Keywords Detected"** expander (expanded): Lists `bt: kw1, kw2, ...`
- **"🆕 New Basic Types to Add"** expander (expanded): Lists `bt → Category: cat` with keywords

### "📥 Download Tagged SKUs as CSV" Button
1. **Add new BTs**: For each, call `add_new_bt_to_mappings(bt_name, category, keywords)` + `log_new_bt_update()`. Show success/warning per BT. Clear `accepted_new_bts`.
2. **Sync new GK mappings**: Filter out BTs already handled above. Call `update_bt_gk_mappings(existing_bt_gk_mappings)`. Show success/warning.
3. **Generate CSV**: DataFrame with columns: `SKU Name`, `Category`, `Basic Type`, `Generic Keywords` (comma-joined). Via `st.download_button`, filename: `"tagged_skus.csv"`.

---

## 16. API Usage Tracking

Every GPT call via `gpt_call_with_usage()` returns:
```
{prompt_tokens, completion_tokens, total_tokens, input_cost, output_cost, total_cost, model}
```

The app adds `operation` and `batch` fields, then:
1. Appends to `api_usage_stats`
2. Adds to running `total_session_cost` and `total_session_tokens`
3. Calls `log_gpt_cost_to_sheets()` for Google Sheets persistence

Cost calculation uses per-model pricing in `utils.py` (`PRICING` dict) with `gpt-4o` as default.

---

## 17. Embedding-Based BT Features (Scaffolded)

Sidebar config exists (`EMBEDDING_TOP_K`, `EMBEDDING_BT_BATCH_SIZE`), imports exist, and `batch_embedding_bt_category_prompt` is imported — but **no button or code path** in `app_old.py` actually triggers the embedding flow. This is scaffolding for:
1. Build BT embeddings (pickle cache keyed by MD5 hash of sorted BT names)
2. Embed SKU names
3. Cosine similarity → top-K BTs per SKU
4. Send per-SKU shortlists to GPT via `batch_embedding_bt_category_prompt`

---

## 18. Key Implementation Patterns

### Selectbox Session State Pattern
- **Never** use `index` parameter — only `key`
- Initialize `st.session_state[key]` to desired value before widget renders
- Widget reads and manages value solely via session state
- Avoids Streamlit warning: "widget created with default value but also had value set via Session State API"

### Code Fence Stripping
Both BT and GK result parsers strip markdown fences: if response starts with `` ``` ``, filter out lines starting with `` ``` ``.

### st_tags Re-render Trick
`gk_version` counter appended to widget keys (`tags_{idx}_v{gk_version}`). Incrementing after GPT updates forces new widget instances, ensuring fresh values display.

### `@st.fragment` for Keywords
Prevents full-page rerun on rapid tag edits. Without this, concurrent modifications cause WebSocket desync ("Cached ForwardMsg MISS").

### BT Dropdown Dynamic Injection
If current BT value (from GPT/typed) doesn't exist in filtered dropdown options, it's injected before `'➕ Type new...'` so the selectbox can display it.
