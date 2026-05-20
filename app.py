import streamlit as st
import pandas as pd
import numpy as np
from openai import AzureOpenAI
import json
import os
import requests
from datetime import datetime
from dotenv import load_dotenv
import streamlit.components.v1 as components
from utils import gpt_call, gpt_call_with_usage, gemini_call_with_usage, category_prompt, basictype_prompt, generic_keyword_prompt, batch_generic_keyword_prompt, batch_category_prompt, batch_basictype_prompt, batch_basictype_category_prompt, batch_embedding_bt_category_prompt
from embedding_utils import build_bt_embeddings, get_sku_embeddings, find_similar_basic_types_batch, load_cache, EMBEDDING_BATCH_SIZE

# Load environment variables from .env file
load_dotenv()

# Page config
st.set_page_config(page_title="SKU Tagging System", layout="wide", initial_sidebar_state="collapsed")

# Title
st.title("🏷️ SKU Tagging System")
st.markdown("Load SKUs from Google Sheets and automatically tag them with Categories, Basic Types, and Generic Keywords")

# Azure OpenAI configuration (loaded from environment variables)
open_api_key = os.getenv('AZURE_OPENAI_API_KEY')
api_version = os.getenv('AZURE_OPENAI_API_VERSION', '2024-02-01')
azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
deployment_name = os.getenv('AZURE_OPENAI_DEPLOYMENT_NAME')
embedding_deployment_name = os.getenv('AZURE_OPENAI_EMBEDDING_DEPLOYMENT', '')

# Google Gemini configuration (loaded from environment variables)
gemini_api_key = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = "gemini-3.1-flash-lite"  # Model for Gemini tagging

# Validate required environment variables
if not all([open_api_key, azure_endpoint, deployment_name]):
    st.error("❌ Missing required environment variables. Please configure your .env file with Azure OpenAI credentials.")
    st.info("Required variables: AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT_NAME")
    st.stop()

# Initialize session state
if 'sku_data' not in st.session_state:
    st.session_state.sku_data = None
if 'category_df' not in st.session_state:
    st.session_state.category_df = None
if 'bt_df' not in st.session_state:
    st.session_state.bt_df = None
if 'gk_df' not in st.session_state:
    st.session_state.gk_df = None
if 'mapping_cat_bt_df' not in st.session_state:
    st.session_state.mapping_cat_bt_df = None
if 'mapping_bt_gk_df' not in st.session_state:
    st.session_state.mapping_bt_gk_df = None
if 'api_usage_stats' not in st.session_state:
    st.session_state.api_usage_stats = []
if 'total_session_cost' not in st.session_state:
    st.session_state.total_session_cost = 0.0
if 'total_session_tokens' not in st.session_state:
    st.session_state.total_session_tokens = 0
if 'session_id' not in st.session_state:
    # Generate a unique session ID for tracking
    import uuid
    st.session_state.session_id = str(uuid.uuid4())[:8]
if 'suggested_new_bts' not in st.session_state:
    # Store suggested new basic types: {sku_idx: {'suggested_bt': '...', 'category': '...'}}
    st.session_state.suggested_new_bts = {}
if 'multi_cat_bts' not in st.session_state:
    # Basic types mapped to multiple categories: {bt_name: [cat1, cat2, ...]}
    st.session_state.multi_cat_bts = {}
if 'needs_category_review' not in st.session_state:
    # Set of SKU indices whose category needs manual review (multi-category BT)
    st.session_state.needs_category_review = set()
if 'accepted_new_bts' not in st.session_state:
    # Store accepted new basic types for export: {'bt_name': {'category': '...', 'generic_keywords': [...]}}
    st.session_state.accepted_new_bts = {}
if 'tagging_complete' not in st.session_state:
    st.session_state.tagging_complete = False
if 'page_index' not in st.session_state:
    st.session_state.page_index = 0
if 'total_sheet_rows' not in st.session_state:
    # Total number of data rows in the Google Sheet (for pagination display)
    st.session_state.total_sheet_rows = 0
if 'sheet_skus_loaded' not in st.session_state:
    # Flag to track if SKUs have been loaded from Google Sheet
    st.session_state.sheet_skus_loaded = False

ROWS_PER_PAGE = 10

# Number of SKUs to load from Google Sheet at startup
SKU_LOAD_LIMIT = 100

# Load mapping files from Google Sheets
import os

# Google Sheets configuration
SPREADSHEET_ID = "1-1DejLMWTf7YbUNKVa84fIiguL1XXb14wKJ-w28yOh4"
SHEET_IDS = {
    "BT_GK_mappings": "1433148032",
    "BT_CT_mappings": "1757740042",
    "SKU_Names": "911707286"
}

# Google Apps Script Web App URL for logging GPT costs
# Replace this with your deployed Web App URL after deploying the Apps Script
GOOGLE_SHEETS_WEBAPP_URL = os.getenv('GOOGLE_SHEETS_WEBAPP_URL', '')

def log_gpt_cost_to_sheets(usage_stats, operation_details=None):
    """
    Log GPT token usage and costs to Google Sheets 'GPT Token Costs' tab
    
    Args:
        usage_stats: Dictionary containing token usage and cost information
        operation_details: Optional dictionary with additional context about the operation
    """
    if not GOOGLE_SHEETS_WEBAPP_URL:
        print("[WARN] Google Sheets Web App URL not configured. Skipping cost logging.")
        return False
    
    try:
        # Prepare the data payload
        payload = {
            'timestamp': datetime.now().isoformat(),
            'operation': usage_stats.get('operation', 'Unknown'),
            'batch_info': usage_stats.get('batch', 'N/A'),
            'model': usage_stats.get('model', 'Unknown'),
            'prompt_tokens': usage_stats.get('prompt_tokens', 0),
            'completion_tokens': usage_stats.get('completion_tokens', 0),
            'total_tokens': usage_stats.get('total_tokens', 0),
            'input_cost': usage_stats.get('input_cost', 0),
            'output_cost': usage_stats.get('output_cost', 0),
            'total_cost': usage_stats.get('total_cost', 0),
            'session_id': st.session_state.get('session_id', 'Unknown'),
        }
        
        # Add operation details if provided
        if operation_details:
            payload['sku_count'] = operation_details.get('sku_count', 0)
            payload['notes'] = operation_details.get('notes', '')
        
        # Send to Google Sheets via Web App
        response = requests.post(
            GOOGLE_SHEETS_WEBAPP_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        if response.status_code == 200:
            print(f"[OK] GPT cost logged to Google Sheets: {usage_stats.get('total_cost', 0):.6f} USD")
            return True
        else:
            print(f"[ERROR] Failed to log to Google Sheets: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Error logging to Google Sheets: {str(e)}")
        return False

def update_bt_gk_mappings(bt_gk_updates):
    """
    Update BT_GK_mappings in Google Sheets with new generic keywords
    
    Args:
        bt_gk_updates: Dictionary with basic_type as key and list of new keywords to add as value
                      e.g., {'Cauliflower': ['New Keyword 1', 'New Keyword 2']}
    
    Returns:
        bool: True if successful, False otherwise
    """
    if not GOOGLE_SHEETS_WEBAPP_URL:
        print("[WARN] Google Sheets Web App URL not configured. Skipping BT_GK update.")
        return False
    
    if not bt_gk_updates:
        print("No BT_GK updates to send.")
        return True
    
    try:
        # Prepare the data payload
        payload = {
            'action': 'update_bt_gk_mappings',
            'timestamp': datetime.now().isoformat(),
            'updates': bt_gk_updates,
            'session_id': st.session_state.get('session_id', 'Unknown'),
        }
        
        # Send to Google Sheets via Web App
        response = requests.post(
            GOOGLE_SHEETS_WEBAPP_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"[OK] BT_GK mappings updated in Google Sheets: {result}")
            return True
        else:
            print(f"[ERROR] Failed to update BT_GK mappings: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Error updating BT_GK mappings: {str(e)}")
        return False


def update_bt_ct_mappings(bt_ct_updates):
    """
    Add new basic types to BT_CT_mappings in Google Sheets
    
    Args:
        bt_ct_updates: List of dicts with 'basic_type' and 'category' keys
                      e.g., [{'basic_type': 'New Type', 'category': 'Groceries'}]
    
    Returns:
        bool: True if successful, False otherwise
    """
    if not GOOGLE_SHEETS_WEBAPP_URL:
        print("[WARN] Google Sheets Web App URL not configured. Skipping BT_CT update.")
        return False
    
    if not bt_ct_updates:
        print("No BT_CT updates to send.")
        return True
    
    try:
        # Prepare the data payload
        payload = {
            'action': 'update_bt_ct_mappings',
            'timestamp': datetime.now().isoformat(),
            'updates': bt_ct_updates,
            'session_id': st.session_state.get('session_id', 'Unknown'),
        }
        
        # Send to Google Sheets via Web App
        response = requests.post(
            GOOGLE_SHEETS_WEBAPP_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"[OK] BT_CT mappings updated in Google Sheets: {result}")
            return True
        else:
            print(f"[ERROR] Failed to update BT_CT mappings: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Error updating BT_CT mappings: {str(e)}")
        return False


def log_new_bt_update(bt_name, category, sku_name, action='added'):
    """
    Log new basic type additions to BT_Update_Log sheet
    
    Args:
        bt_name: The new basic type name
        category: The category for the new basic type
        sku_name: The SKU name that triggered the new BT suggestion
        action: The action taken ('added', 'suggested', etc.)
    
    Returns:
        bool: True if successful, False otherwise
    """
    if not GOOGLE_SHEETS_WEBAPP_URL:
        print("[WARN] Google Sheets Web App URL not configured. Skipping BT Update log.")
        return False
    
    try:
        # Prepare the data payload
        payload = {
            'action': 'log_bt_update',
            'timestamp': datetime.now().isoformat(),
            'basic_type': bt_name,
            'category': category,
            'sku_name': sku_name,
            'update_action': action,
            'session_id': st.session_state.get('session_id', 'Unknown'),
        }
        
        # Send to Google Sheets via Web App
        response = requests.post(
            GOOGLE_SHEETS_WEBAPP_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"[OK] BT Update logged in Google Sheets: {result}")
            return True
        else:
            print(f"[ERROR] Failed to log BT Update: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Error logging BT Update: {str(e)}")
        return False


def add_new_bt_to_mappings(bt_name, category, generic_keywords=None):
    """
    Add a new basic type to BT_CT_mappings and BT_GK_mappings
    
    Args:
        bt_name: The new basic type name
        category: The category for the new basic type
        generic_keywords: Optional list of generic keywords for the new basic type
    
    Returns:
        bool: True if successful, False otherwise
    """
    if not GOOGLE_SHEETS_WEBAPP_URL:
        print("[WARN] Google Sheets Web App URL not configured. Skipping new BT addition.")
        return False
    
    try:
        # Prepare the data payload
        payload = {
            'action': 'add_new_basic_type',
            'timestamp': datetime.now().isoformat(),
            'basic_type': bt_name,
            'category': category,
            'generic_keywords': generic_keywords or [],
            'session_id': st.session_state.get('session_id', 'Unknown'),
        }
        
        # Send to Google Sheets via Web App
        response = requests.post(
            GOOGLE_SHEETS_WEBAPP_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"[OK] New basic type added to Google Sheets: {result}")
            return True
        else:
            print(f"[ERROR] Failed to add new basic type: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Error adding new basic type: {str(e)}")
        return False


def get_existing_gk_for_basic_type(basic_type):
    """
    Get the existing generic keywords for a given basic type from the mapping
    
    Args:
        basic_type: The basic type to look up
    
    Returns:
        set: Set of existing generic keywords for this basic type
    """
    if st.session_state.mapping_bt_gk_df is None or not basic_type:
        return set()
    
    gk_list = st.session_state.mapping_bt_gk_df.loc[
        st.session_state.mapping_bt_gk_df.iloc[:, 0] == basic_type,
        st.session_state.mapping_bt_gk_df.columns[1]
    ].tolist()
    
    # Flatten all values — cells may be lists (parsed) or strings (unparsed)
    result = set()
    for item in gk_list:
        if isinstance(item, list):
            result.update(item)
        elif isinstance(item, str):
            # Try to parse stringified list that safe_parse_list may have missed
            stripped = item.strip()
            if stripped.startswith('['):
                try:
                    parsed = json.loads(stripped.replace("'", '"'))
                    if isinstance(parsed, list):
                        result.update(parsed)
                        continue
                except Exception:
                    pass
            result.add(item)
    return result


def load_skus_from_main_sheet(offset=0, limit=100):
    """
    Load SKUs from the Main sheet in the SKU Tagging spreadsheet via Google Apps Script.
    
    Args:
        offset: 0-based row offset (default 0)
        limit: Max number of rows to return (default 100)
    
    Returns:
        dict: {success, skus: [{row, sku_name, category, basic_type, generic_keywords}, ...], total_rows}
    """
    if not GOOGLE_SHEETS_WEBAPP_URL:
        print("[WARN] Google Sheets Web App URL not configured. Cannot load SKUs from Main sheet.")
        return {'success': False, 'error': 'GOOGLE_SHEETS_WEBAPP_URL not configured', 'skus': [], 'total_rows': 0}
    
    try:
        payload = {
            'action': 'get_main_skus',
            'offset': offset,
            'limit': limit,
        }
        
        response = requests.post(
            GOOGLE_SHEETS_WEBAPP_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print(f"[OK] Loaded {len(result.get('skus', []))} SKUs from Main sheet (offset={offset}, total={result.get('total_rows', 0)})")
                return result
            else:
                print(f"[ERROR] Failed to load SKUs from Main sheet: {result.get('error')}")
                return {'success': False, 'error': result.get('error'), 'skus': [], 'total_rows': 0}
        else:
            print(f"[ERROR] Failed to load SKUs from Main sheet: HTTP {response.status_code}")
            return {'success': False, 'error': f'HTTP {response.status_code}', 'skus': [], 'total_rows': 0}
            
    except Exception as e:
        print(f"[ERROR] Error loading SKUs from Main sheet: {str(e)}")
        return {'success': False, 'error': str(e), 'skus': [], 'total_rows': 0}


def update_skus_in_main_sheet(updates):
    """
    Update SKU tags in the Main sheet via Google Apps Script.
    
    Args:
        updates: List of dicts with {row, category, basic_type, generic_keywords}
                where row is the 1-indexed sheet row number
    
    Returns:
        dict: {success, message, updated_count}
    """
    if not GOOGLE_SHEETS_WEBAPP_URL:
        print("[WARN] Google Sheets Web App URL not configured. Cannot update SKUs in Main sheet.")
        return {'success': False, 'error': 'GOOGLE_SHEETS_WEBAPP_URL not configured'}
    
    if not updates:
        print("[INFO] No SKU updates to send.")
        return {'success': True, 'message': 'No updates to send', 'updated_count': 0}
    
    try:
        payload = {
            'action': 'update_main_sku_tags',
            'updates': updates,
            'session_id': st.session_state.get('session_id', 'Unknown'),
        }
        
        response = requests.post(
            GOOGLE_SHEETS_WEBAPP_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=60  # Longer timeout for batch updates
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print(f"[OK] Updated {result.get('updated_count', 0)} SKUs in Main sheet")
                return result
            else:
                print(f"[ERROR] Failed to update SKUs in Main sheet: {result.get('error')}")
                return {'success': False, 'error': result.get('error')}
        else:
            print(f"[ERROR] Failed to update SKUs in Main sheet: HTTP {response.status_code}")
            return {'success': False, 'error': f'HTTP {response.status_code}'}
            
    except Exception as e:
        print(f"[ERROR] Error updating SKUs in Main sheet: {str(e)}")
        return {'success': False, 'error': str(e)}


def sync_current_page_to_sheet():
    """
    Sync the current page's SKU tags to the Google Sheet.
    Also syncs any new BT/GK mappings.
    
    Returns:
        bool: True if successful, False otherwise
    """
    if not st.session_state.sku_data:
        return True
    
    # Build updates list from sku_data (only items that have a sheet row number)
    updates = []
    for item in st.session_state.sku_data:
        if 'sheet_row' not in item:
            continue
        
        # Format generic keywords as comma-separated string
        gks = item.get('generic_keywords', [])
        gks_str = ', '.join(gks) if isinstance(gks, list) else str(gks)
        
        updates.append({
            'row': item['sheet_row'],
            'category': item.get('category', ''),
            'basic_type': item.get('basic_type', ''),
            'generic_keywords': gks_str
        })
    
    if not updates:
        return True
    
    # First, sync any new BT/GK mappings
    all_existing_bts = set()
    if st.session_state.bt_df is not None:
        all_existing_bts = set(st.session_state.bt_df.iloc[:, 0].tolist())
    
    # Detect new basic types
    new_bts = {}
    for item in st.session_state.sku_data:
        basic_type = item.get('basic_type', '')
        category = item.get('category', '')
        if not basic_type:
            continue
        if basic_type not in all_existing_bts:
            if basic_type not in new_bts:
                new_bts[basic_type] = {
                    'category': category if category else 'Uncategorized',
                    'generic_keywords': set(),
                    'source_sku': item['sku_name']
                }
            if item.get('generic_keywords'):
                new_bts[basic_type]['generic_keywords'].update(item['generic_keywords'])
    
    # Detect new GK mappings
    new_gk_mappings = {}
    for item in st.session_state.sku_data:
        basic_type = item.get('basic_type', '')
        current_keywords = item.get('generic_keywords', [])
        if not basic_type or not current_keywords:
            continue
        existing_keywords = get_existing_gk_for_basic_type(basic_type)
        new_keywords = [kw for kw in current_keywords if kw not in existing_keywords]
        if new_keywords:
            if basic_type not in new_gk_mappings:
                new_gk_mappings[basic_type] = set()
            new_gk_mappings[basic_type].update(new_keywords)
    
    # Add new basic types to mappings
    for bt_name, bt_info in new_bts.items():
        gks = list(bt_info['generic_keywords'])
        success = add_new_bt_to_mappings(bt_name, bt_info['category'], gks)
        if success:
            log_new_bt_update(bt_name, bt_info['category'], bt_info.get('source_sku', 'Unknown'), 'added')
            print(f"[OK] Added new BT '{bt_name}' to Google Sheets")
        else:
            print(f"[WARN] Could not add new BT '{bt_name}' to Google Sheets")
    
    # Sync new GK mappings (for existing BTs only)
    existing_bt_gk_mappings = {bt: list(kws) for bt, kws in new_gk_mappings.items() if bt not in new_bts}
    if existing_bt_gk_mappings:
        success = update_bt_gk_mappings(existing_bt_gk_mappings)
        if success:
            print(f"[OK] Synced {sum(len(v) for v in existing_bt_gk_mappings.values())} new GKs to Google Sheets")
        else:
            print("[WARN] Could not sync new GKs to Google Sheets")
    
    # Now update the SKU tags in the Main sheet
    result = update_skus_in_main_sheet(updates)
    return result.get('success', False)


def _init_page_widget_keys(page_idx):
    """Initialize widget session state keys for the given page SKU slice."""
    start = page_idx * ROWS_PER_PAGE
    end = min(start + ROWS_PER_PAGE, len(st.session_state.sku_data))
    for idx in range(start, end):
        item = st.session_state.sku_data[idx]
        # Only init multiselect keys (tags) — selectboxes use index param instead
        if f"tags_{idx}" not in st.session_state:
            st.session_state[f"tags_{idx}"] = item.get('generic_keywords', [])


def load_google_sheet(spreadsheet_id, sheet_gid):
    """Load a Google Sheet as a pandas DataFrame"""
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={sheet_gid}"
    try:
        df = pd.read_csv(url)
        return df
    except Exception as e:
        print(f"Error loading sheet (gid={sheet_gid}): {str(e)}")
        return None

def safe_parse_list(value):
    """Safely parse a string representation of a list or return the value as-is"""
    if pd.isna(value) or value is None:
        return value
    if not isinstance(value, str):
        return value
    
    stripped = value.strip()
    if stripped.startswith('[') or stripped.startswith('{'):
        # Try ast.literal_eval first (handles single quotes, nested structures)
        try:
            import ast
            result = ast.literal_eval(stripped)
            if isinstance(result, (list, dict)):
                return result
        except Exception:
            pass
        # Fallback: JSON parse with quote replacement
        try:
            return json.loads(stripped.replace("'", '"'))
        except Exception:
            pass
    return value

# Only load from Google Sheets if data hasn't been loaded yet (avoid re-fetching on every rerun)
if 'sheets_loaded' not in st.session_state:
    st.session_state.sheets_loaded = False

# Sidebar button to force-refresh mapping data
if st.sidebar.button("🔄 Reload Mapping Data"):
    st.session_state.sheets_loaded = False

if not st.session_state.sheets_loaded:
    try:
        print("\n" + "="*60)
        print("Loading data from Google Sheets...")
        print("="*60)
        
        # Load Category-BasicType Mapping (BT_CT_mappings sheet)
        print(f"\nLoading BT_CT_mappings (gid={SHEET_IDS['BT_CT_mappings']})...")
        st.session_state.mapping_cat_bt_df = load_google_sheet(SPREADSHEET_ID, SHEET_IDS['BT_CT_mappings'])
        if st.session_state.mapping_cat_bt_df is not None:
            print(f"[OK] Category-BasicType Mapping loaded: {len(st.session_state.mapping_cat_bt_df)} records")
            print(f"  Columns: {list(st.session_state.mapping_cat_bt_df.columns)}")
            # Parse list columns if stored as strings
            for col in st.session_state.mapping_cat_bt_df.columns:
                if st.session_state.mapping_cat_bt_df[col].dtype == object:
                    st.session_state.mapping_cat_bt_df[col] = st.session_state.mapping_cat_bt_df[col].apply(safe_parse_list)
        
        # Load BasicType-GenericKeywords Mapping (BT_GK_mappings sheet)
        print(f"\nLoading BT_GK_mappings (gid={SHEET_IDS['BT_GK_mappings']})...")
        st.session_state.mapping_bt_gk_df = load_google_sheet(SPREADSHEET_ID, SHEET_IDS['BT_GK_mappings'])
        if st.session_state.mapping_bt_gk_df is not None:
            print(f"[OK] BasicType-GenericKeywords Mapping loaded: {len(st.session_state.mapping_bt_gk_df)} records")
            print(f"  Columns: {list(st.session_state.mapping_bt_gk_df.columns)}")
            # Parse list columns if stored as strings
            for col in st.session_state.mapping_bt_gk_df.columns:
                if st.session_state.mapping_bt_gk_df[col].dtype == object:
                    st.session_state.mapping_bt_gk_df[col] = st.session_state.mapping_bt_gk_df[col].apply(safe_parse_list)
        
        # Extract unique categories from the mapping (from Category Tag Type column - index 1)
        if st.session_state.mapping_cat_bt_df is not None:
            st.session_state.category_df = pd.DataFrame({
                'Category': st.session_state.mapping_cat_bt_df.iloc[:, 1].unique()
            })
            print(f"\n[OK] Categories extracted: {len(st.session_state.category_df)} unique categories")
            
            # Identify basic types mapped to multiple categories
            bt_col = st.session_state.mapping_cat_bt_df.columns[0]
            cat_col = st.session_state.mapping_cat_bt_df.columns[1]
            bt_cats = st.session_state.mapping_cat_bt_df.groupby(bt_col)[cat_col].apply(lambda x: list(x.unique())).to_dict()
            st.session_state.multi_cat_bts = {bt: cats for bt, cats in bt_cats.items() if len(cats) > 1}
            if st.session_state.multi_cat_bts:
                print(f"[INFO] Found {len(st.session_state.multi_cat_bts)} basic types mapped to multiple categories:")
                for bt, cats in st.session_state.multi_cat_bts.items():
                    print(f"  - {bt}: {cats}")
        
        # Extract unique basic types from the mapping
        if st.session_state.mapping_bt_gk_df is not None:
            st.session_state.bt_df = pd.DataFrame({
                st.session_state.mapping_bt_gk_df.columns[0]: st.session_state.mapping_bt_gk_df.iloc[:, 0].unique()
            })
            print(f"[OK] Basic Types extracted: {len(st.session_state.bt_df)} unique basic types")
        
        # Extract unique generic keywords from the mapping
        if st.session_state.mapping_bt_gk_df is not None:
            all_keywords = []
            gk_column = st.session_state.mapping_bt_gk_df.columns[1]
            for keywords in st.session_state.mapping_bt_gk_df[gk_column]:
                if isinstance(keywords, list):
                    all_keywords.extend(keywords)
                elif isinstance(keywords, str):
                    # Try to parse stringified list that safe_parse_list may have missed
                    stripped = keywords.strip()
                    if stripped.startswith('['):
                        parsed = safe_parse_list(stripped)
                        if isinstance(parsed, list):
                            all_keywords.extend(parsed)
                        else:
                            all_keywords.append(keywords)
                    else:
                        all_keywords.append(keywords)
            # Filter out empty strings and deduplicate
            all_keywords = sorted(set(kw for kw in all_keywords if kw and str(kw).strip()))
            st.session_state.gk_df = pd.DataFrame({
                'Generic Keywords': all_keywords
            })
            print(f"[OK] Generic Keywords extracted: {len(st.session_state.gk_df)} unique keywords")
        
        # Mark as loaded so we don't re-fetch on every rerun
        st.session_state.sheets_loaded = True
        
        # Status message
        files_loaded = sum([st.session_state.mapping_cat_bt_df is not None,
                           st.session_state.mapping_bt_gk_df is not None,
                           st.session_state.category_df is not None,
                           st.session_state.bt_df is not None,
                           st.session_state.gk_df is not None])
        
        print("\n" + "="*60)
        print(f"Data loading complete: {files_loaded}/5 datasets loaded")
        print("="*60 + "\n")
        
        if files_loaded == 5:
            st.sidebar.success(f"✅ All mapping data loaded from Google Sheets ({files_loaded}/5)")
        else:
            st.sidebar.warning(f"⚠️ {files_loaded}/5 datasets loaded from Google Sheets")
            
    except Exception as e:
        print(f"\n[ERROR] Error loading data from Google Sheets: {str(e)}")
        st.sidebar.error(f"Error loading data from Google Sheets: {str(e)}")
else:
    # Data already loaded - just show status in sidebar
    files_loaded = sum([st.session_state.mapping_cat_bt_df is not None,
                       st.session_state.mapping_bt_gk_df is not None,
                       st.session_state.category_df is not None,
                       st.session_state.bt_df is not None,
                       st.session_state.gk_df is not None])
    if files_loaded == 5:
        st.sidebar.success(f"✅ All mapping data loaded from Google Sheets ({files_loaded}/5)")
    else:
        st.sidebar.warning(f"⚠️ {files_loaded}/5 datasets loaded from Google Sheets")

# Sidebar - Batch Processing Configuration
st.sidebar.header("⚙️ Batch Processing Config")
CATEGORY_BATCH_SIZE = st.sidebar.number_input(
    "Category Batch Size", 
    min_value=1, 
    max_value=50, 
    value=30, 
    help="Number of SKUs to process in one GPT call for categories"
)
BASIC_TYPE_BATCH_SIZE = st.sidebar.number_input(
    "Basic Type Batch Size", 
    min_value=1, 
    max_value=50, 
    value=20, 
    help="Number of SKUs to process in one GPT call for basic types"
)
BT_CATEGORY_BATCH_SIZE = st.sidebar.number_input(
    "BT & Category Batch Size", 
    min_value=1, 
    max_value=50, 
    value=15, 
    help="Number of SKUs to process in one GPT call for combined Basic Type and Category lookup"
)

# Embedding-based BT config
st.sidebar.header("🧠 Embedding Config")
EMBEDDING_TOP_K = st.sidebar.number_input(
    "Top-K Similar BTs",
    min_value=5,
    max_value=100,
    value=30,
    help="Number of most similar basic types to shortlist per SKU via embeddings before sending to GPT"
)
EMBEDDING_BT_BATCH_SIZE = st.sidebar.number_input(
    "Embedding BT Batch Size",
    min_value=1,
    max_value=50,
    value=15,
    help="Number of SKUs per GPT call when using embedding-filtered basic types"
)
if not embedding_deployment_name:
    st.sidebar.warning("⚠️ Set AZURE_OPENAI_EMBEDDING_DEPLOYMENT in .env to use embedding features")

# Sidebar - API Usage Statistics
st.sidebar.header("📊 API Usage Stats")
st.sidebar.metric("Total Tokens", f"{st.session_state.total_session_tokens:,}")
st.sidebar.metric("Total Cost", f"${st.session_state.total_session_cost:.4f}")

# Show detailed usage in expander
with st.sidebar.expander("📋 Detailed Usage Log"):
    if st.session_state.api_usage_stats:
        for i, stat in enumerate(reversed(st.session_state.api_usage_stats[-10:])):  # Show last 10
            st.markdown(f"**{stat.get('operation', 'API Call')}**")
            st.markdown(f"- Batch: {stat.get('batch', 'N/A')}")
            st.markdown(f"- Tokens: {stat['total_tokens']:,} (in: {stat['prompt_tokens']:,}, out: {stat['completion_tokens']:,})")
            st.markdown(f"- Cost: ${stat['total_cost']:.6f}")
            st.markdown("---")
    else:
        st.info("No API calls yet")

# Reset usage stats button
if st.sidebar.button("🔄 Reset Usage Stats"):
    st.session_state.api_usage_stats = []
    st.session_state.total_session_cost = 0.0
    st.session_state.total_session_tokens = 0
    st.rerun()

# Main content area
st.header("")

# Load SKUs from Google Sheet on page load
st.subheader("📋 SKU List from Google Sheet")

# Sidebar button to force-refresh SKU data
if st.sidebar.button("🔄 Reload SKUs from Sheet"):
    st.session_state.sheet_skus_loaded = False
    # Clear old per-SKU widget keys
    if st.session_state.sku_data:
        for old_idx in range(len(st.session_state.sku_data)):
            for prefix in ['cat_', 'bt_', 'tags_', 'bt_select_', 'bt_custom_', 'bt_adding_new_',
                           'gk_adding_new_', 'sku_',
                           'accept_new_bt_', 'accept_bt_', 'dismiss_new_bt_', 'dismiss_bt_', 'new_gk_']:
                key = f"{prefix}{old_idx}"
                if key in st.session_state:
                    del st.session_state[key]
    st.session_state.sku_data = None
    st.session_state.page_index = 0
    st.rerun()

# Load SKUs from Google Sheet if not already loaded
if not st.session_state.sheet_skus_loaded:
    if not GOOGLE_SHEETS_WEBAPP_URL:
        st.error("❌ GOOGLE_SHEETS_WEBAPP_URL not configured. Please set it in your .env file.")
        st.info("This URL is the deployed Google Apps Script Web App endpoint.")
        st.stop()
    
    with st.spinner("Loading SKUs from Google Sheet..."):
        result = load_skus_from_main_sheet(offset=0, limit=SKU_LOAD_LIMIT)
        
        if result.get('success') and result.get('skus'):
            # Clear old per-SKU widget keys from session state
            if st.session_state.sku_data:
                for old_idx in range(len(st.session_state.sku_data)):
                    for prefix in ['cat_', 'bt_', 'tags_', 'bt_select_', 'bt_custom_', 'bt_adding_new_',
                                   'gk_adding_new_', 'sku_',
                                   'accept_new_bt_', 'accept_bt_', 'dismiss_new_bt_', 'dismiss_bt_', 'new_gk_']:
                        key = f"{prefix}{old_idx}"
                        if key in st.session_state:
                            del st.session_state[key]
            
            st.session_state.sku_data = []
            st.session_state.suggested_new_bts = {}
            st.session_state.needs_category_review = set()
            st.session_state.page_index = 0
            st.session_state.tagging_complete = False
            st.session_state.total_sheet_rows = result.get('total_rows', 0)
            
            for sku_info in result.get('skus', []):
                sku_name = sku_info.get('sku_name', '').strip()
                if sku_name and sku_name.lower() != 'nan':
                    # Parse generic keywords from comma-separated string
                    gks_raw = sku_info.get('generic_keywords', '')
                    gks = [kw.strip() for kw in gks_raw.split(',') if kw.strip()] if gks_raw else []
                    
                    st.session_state.sku_data.append({
                        'sku_name': sku_name,
                        'category': sku_info.get('category', ''),
                        'basic_type': sku_info.get('basic_type', ''),
                        'generic_keywords': gks,
                        'sheet_row': sku_info.get('row')  # Store the sheet row number for updates
                    })
            
            _init_page_widget_keys(0)
            st.session_state.sheet_skus_loaded = True
            print(f"[OK] Loaded {len(st.session_state.sku_data)} SKUs from Google Sheet (total in sheet: {st.session_state.total_sheet_rows})")
            st.rerun()
        else:
            error_msg = result.get('error', 'Unknown error')
            st.error(f"❌ Failed to load SKUs from Google Sheet: {error_msg}")
            st.info("Make sure the Google Apps Script is deployed and the 'Main' sheet exists with SKU data.")
            st.stop()

# Show status
if st.session_state.sku_data:
    total_skus = len(st.session_state.sku_data)
    total_pages = (total_skus + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE
    current_page = st.session_state.page_index + 1
    tagged_count = sum(1 for item in st.session_state.sku_data if item.get('basic_type') or item.get('category'))
    st.success(f"✅ Loaded {total_skus} SKUs ({tagged_count} tagged) | Page {current_page} of {total_pages} | Total in sheet: {st.session_state.total_sheet_rows}")
else:
    st.info("⏳ Loading SKUs from Google Sheet...")
    st.stop()

if st.session_state.sku_data:
    
    # Check if all mapping files are loaded
    all_files_loaded = all([
        st.session_state.category_df is not None,
        st.session_state.bt_df is not None,
        st.session_state.gk_df is not None,
        st.session_state.mapping_cat_bt_df is not None,
        st.session_state.mapping_bt_gk_df is not None
    ])
    
    if not all_files_loaded:
        st.warning("⚠️ Mapping files are required for auto-tagging features")
    
    # Action buttons
    st.header("🤖 Auto-Tagging Actions")
    col1, col2 = st.columns(2)
    
    with col1:
        azure_disabled = not all_files_loaded
        if st.button("🔵 Tag with Azure GPT", disabled=azure_disabled, use_container_width=True, help="Find BT, Category, and Generic Keywords using Azure OpenAI"):
            if all_files_loaded:
                # ========== PHASE 1: Find Basic Type and Category ==========
                with st.spinner("Phase 1/2: Finding basic types and categories..."):
                    # Get ALL unique basic types from BT_CT_mappings (first column)
                    all_basic_types = st.session_state.mapping_cat_bt_df.iloc[:, 0].unique().tolist()
                    
                    # Build BT to Category mapping dictionary
                    bt_to_category = {}
                    for _, row in st.session_state.mapping_cat_bt_df.iterrows():
                        bt = row.iloc[0]
                        cat = row.iloc[1]
                        bt_to_category[bt] = cat
                    
                    total_skus = len(st.session_state.sku_data)
                    progress_bar = st.progress(0, text="Phase 1: Finding BT & Categories...")
                    processed = 0
                    batch_usage_stats = []
                    
                    # Clear previous suggestions and review flags
                    st.session_state.suggested_new_bts = {}
                    st.session_state.needs_category_review = set()
                    
                    # Process BT+Category in batches
                    for batch_start in range(0, total_skus, BT_CATEGORY_BATCH_SIZE):
                        batch_end = min(batch_start + BT_CATEGORY_BATCH_SIZE, total_skus)
                        batch_skus = [item['sku_name'] for item in st.session_state.sku_data[batch_start:batch_end]]
                        
                        print(f"\n>>> [Azure] Processing BT & Category Batch: SKUs {batch_start+1}-{batch_end}")
                        
                        try:
                            result, usage_stats = gpt_call_with_usage(
                                open_api_key, api_version, azure_endpoint, deployment_name,
                                batch_basictype_category_prompt(batch_skus, all_basic_types, bt_to_category)
                            )
                            
                            usage_stats['operation'] = 'Azure: Find BT and CT'
                            usage_stats['batch'] = f"SKUs {batch_start+1}-{batch_end}"
                            batch_usage_stats.append(usage_stats)
                            st.session_state.api_usage_stats.append(usage_stats)
                            st.session_state.total_session_cost += usage_stats['total_cost']
                            st.session_state.total_session_tokens += usage_stats['total_tokens']
                            
                            log_gpt_cost_to_sheets(usage_stats, {
                                'sku_count': len(batch_skus),
                                'notes': f'[Azure] Batch BT+CT for {len(batch_skus)} SKUs'
                            })
                            
                            result_clean = result.strip()
                            if result_clean.startswith('```'):
                                lines = result_clean.split('\n')
                                result_clean = '\n'.join([l for l in lines if not l.startswith('```')])
                            
                            batch_results = json.loads(result_clean)['results']
                            results_by_sku = {r['sku']: r for r in batch_results}
                            
                            for idx in range(batch_start, batch_end):
                                sku_name = st.session_state.sku_data[idx]['sku_name']
                                if sku_name not in results_by_sku:
                                    continue
                                
                                result_item = results_by_sku[sku_name]
                                basic_type = result_item['basic_type']
                                category = result_item.get('category', bt_to_category.get(basic_type, ''))
                                is_new_bt = result_item.get('is_new_bt', False)
                                suggested_bt = result_item.get('suggested_bt', None)
                                
                                st.session_state.sku_data[idx]['basic_type'] = basic_type
                                st.session_state.sku_data[idx]['category'] = category
                                
                                if basic_type in st.session_state.multi_cat_bts:
                                    st.session_state.needs_category_review.add(idx)
                                
                                if is_new_bt and suggested_bt:
                                    all_bt_set = set(all_basic_types)
                                    closest_existing = basic_type if basic_type in all_bt_set else ''
                                    if not closest_existing and category:
                                        cat_bts = [bt for bt, cat in bt_to_category.items() if cat == category]
                                        if cat_bts:
                                            sku_lower = sku_name.lower()
                                            scored = [(bt, sum(w in bt.lower() for w in sku_lower.split())) for bt in cat_bts]
                                            scored.sort(key=lambda x: -x[1])
                                            closest_existing = scored[0][0]
                                    st.session_state.sku_data[idx]['basic_type'] = closest_existing
                                    st.session_state.suggested_new_bts[idx] = {
                                        'suggested_bt': suggested_bt, 'category': category,
                                        'sku_name': sku_name, 'closest_existing_bt': closest_existing
                                    }
                            
                            processed = batch_end
                        except Exception as e:
                            print(f"[ERROR] Azure BT+Cat batch error: {str(e)}")
                            st.error(f"Error in BT+Cat batch {batch_start+1}-{batch_end}: {str(e)}")
                        
                        progress_bar.progress(processed / total_skus, text=f"Phase 1: {processed}/{total_skus} SKUs...")
                
                # ========== PHASE 2: Find Generic Keywords ==========
                with st.spinner("Phase 2/2: Finding generic keywords..."):
                    from collections import defaultdict
                    bt_groups = defaultdict(list)
                    for idx, item in enumerate(st.session_state.sku_data):
                        if item['basic_type']:
                            bt_groups[(item['basic_type'], item['category'])].append((idx, item))
                    
                    total_groups = len(bt_groups)
                    groups_done = 0
                    gk_processed = 0
                    
                    for (basic_type, category), group_items in bt_groups.items():
                        try:
                            gk_list = st.session_state.mapping_bt_gk_df.loc[
                                st.session_state.mapping_bt_gk_df.iloc[:, 0] == basic_type,
                                st.session_state.mapping_bt_gk_df.columns[1]
                            ].tolist()
                            
                            if not gk_list:
                                groups_done += 1
                                continue
                            if isinstance(gk_list[0], list):
                                gk_list = gk_list[0]
                            
                            sku_names = [item['sku_name'] for _, item in group_items]
                            group_size = len(sku_names)
                            
                            if group_size == 1:
                                idx, item = group_items[0]
                                result, usage_stats = gpt_call_with_usage(
                                    open_api_key, api_version, azure_endpoint, deployment_name,
                                    generic_keyword_prompt(item['sku_name'], category, basic_type, gk_list)
                                )
                                usage_stats['operation'] = 'Azure: Find GK'
                                usage_stats['batch'] = f"SKU: {item['sku_name'][:30]}..."
                            else:
                                result, usage_stats = gpt_call_with_usage(
                                    open_api_key, api_version, azure_endpoint, deployment_name,
                                    batch_generic_keyword_prompt(sku_names, category, basic_type, gk_list)
                                )
                                usage_stats['operation'] = 'Azure: Find GK (batch)'
                                usage_stats['batch'] = f"BT: {basic_type} ({group_size} SKUs)"
                            
                            batch_usage_stats.append(usage_stats)
                            st.session_state.api_usage_stats.append(usage_stats)
                            st.session_state.total_session_cost += usage_stats['total_cost']
                            st.session_state.total_session_tokens += usage_stats['total_tokens']
                            
                            log_gpt_cost_to_sheets(usage_stats, {
                                'sku_count': group_size,
                                'notes': f'[Azure] GK for BT: {basic_type}'
                            })
                            
                            result_clean = result.strip()
                            if result_clean.startswith('```'):
                                lines = result_clean.split('\n')
                                result_clean = '\n'.join(lines[1:-1]) if len(lines) > 2 else result_clean
                            
                            parsed = json.loads(result_clean)
                            
                            if group_size == 1:
                                gk_response = parsed.get('selected_generic_keywords', [])
                                if gk_response and isinstance(gk_response[0], dict):
                                    generic_keywords = [kw['keyword'] for kw in gk_response if 'keyword' in kw]
                                else:
                                    generic_keywords = gk_response if isinstance(gk_response, list) else []
                                st.session_state.sku_data[idx]['generic_keywords'] = generic_keywords
                                st.session_state[f"tags_{idx}"] = generic_keywords
                                gk_processed += 1
                            else:
                                results_list = parsed.get('results', [])
                                results_by_name = {r['sku_name']: r.get('selected_generic_keywords', []) for r in results_list}
                                for idx, item in group_items:
                                    gk_response = results_by_name.get(item['sku_name'], [])
                                    if gk_response and isinstance(gk_response[0], dict):
                                        generic_keywords = [kw['keyword'] for kw in gk_response if 'keyword' in kw]
                                    else:
                                        generic_keywords = gk_response if isinstance(gk_response, list) else []
                                    st.session_state.sku_data[idx]['generic_keywords'] = generic_keywords
                                    st.session_state[f"tags_{idx}"] = generic_keywords
                                    gk_processed += 1
                        
                        except Exception as e:
                            print(f"[ERROR] Azure GK batch error for BT='{basic_type}': {str(e)}")
                        
                        groups_done += 1
                        progress_bar.progress(groups_done / total_groups, text=f"Phase 2: {groups_done}/{total_groups} BT groups...")
                    
                    progress_bar.empty()
                
                # Show final summary
                total_tokens = sum(s['total_tokens'] for s in batch_usage_stats)
                total_cost = sum(s['total_cost'] for s in batch_usage_stats)
                new_bt_count = len(st.session_state.suggested_new_bts)
                
                st.success(f"✅ Azure tagging complete! {processed} SKUs tagged | {gk_processed} GKs assigned | Tokens: {total_tokens:,} | Cost: ${total_cost:.4f}")
                if new_bt_count > 0:
                    st.info(f"💡 {new_bt_count} SKUs have suggested new basic types.")
                st.rerun()
    
    with col2:
        gemini_disabled = not all_files_loaded or not gemini_api_key
        gemini_help = "Find BT, Category, and Generic Keywords using Google Gemini" if gemini_api_key else "Set GEMINI_API_KEY in .env to enable"
        if st.button("🟢 Tag with Gemini", disabled=gemini_disabled, use_container_width=True, help=gemini_help):
            if all_files_loaded and gemini_api_key:
                # ========== PHASE 1: Find Basic Type and Category with Gemini ==========
                with st.spinner("Phase 1/2: Finding basic types and categories (Gemini)..."):
                    all_basic_types = st.session_state.mapping_cat_bt_df.iloc[:, 0].unique().tolist()
                    
                    bt_to_category = {}
                    for _, row in st.session_state.mapping_cat_bt_df.iterrows():
                        bt = row.iloc[0]
                        cat = row.iloc[1]
                        bt_to_category[bt] = cat
                    
                    total_skus = len(st.session_state.sku_data)
                    progress_bar = st.progress(0, text="Phase 1: Finding BT & Categories (Gemini)...")
                    processed = 0
                    batch_usage_stats = []
                    
                    st.session_state.suggested_new_bts = {}
                    st.session_state.needs_category_review = set()
                    
                    for batch_start in range(0, total_skus, BT_CATEGORY_BATCH_SIZE):
                        batch_end = min(batch_start + BT_CATEGORY_BATCH_SIZE, total_skus)
                        batch_skus = [item['sku_name'] for item in st.session_state.sku_data[batch_start:batch_end]]
                        
                        print(f"\n>>> [Gemini] Processing BT & Category Batch: SKUs {batch_start+1}-{batch_end}")
                        
                        try:
                            prompt = batch_basictype_category_prompt(batch_skus, all_basic_types, bt_to_category)
                            result, usage_stats = gemini_call_with_usage(gemini_api_key, prompt, GEMINI_MODEL)
                            
                            usage_stats['operation'] = 'Gemini: Find BT and CT'
                            usage_stats['batch'] = f"SKUs {batch_start+1}-{batch_end}"
                            batch_usage_stats.append(usage_stats)
                            st.session_state.api_usage_stats.append(usage_stats)
                            st.session_state.total_session_cost += usage_stats['total_cost']
                            st.session_state.total_session_tokens += usage_stats['total_tokens']
                            
                            log_gpt_cost_to_sheets(usage_stats, {
                                'sku_count': len(batch_skus),
                                'notes': f'[Gemini/{GEMINI_MODEL}] Batch BT+CT for {len(batch_skus)} SKUs'
                            })
                            
                            result_clean = result.strip()
                            if result_clean.startswith('```'):
                                lines = result_clean.split('\n')
                                result_clean = '\n'.join([l for l in lines if not l.startswith('```')])
                            
                            batch_results = json.loads(result_clean)['results']
                            results_by_sku = {r['sku']: r for r in batch_results}
                            
                            for idx in range(batch_start, batch_end):
                                sku_name = st.session_state.sku_data[idx]['sku_name']
                                if sku_name not in results_by_sku:
                                    continue
                                
                                result_item = results_by_sku[sku_name]
                                basic_type = result_item['basic_type']
                                category = result_item.get('category', bt_to_category.get(basic_type, ''))
                                is_new_bt = result_item.get('is_new_bt', False)
                                suggested_bt = result_item.get('suggested_bt', None)
                                
                                st.session_state.sku_data[idx]['basic_type'] = basic_type
                                st.session_state.sku_data[idx]['category'] = category
                                
                                if basic_type in st.session_state.multi_cat_bts:
                                    st.session_state.needs_category_review.add(idx)
                                
                                if is_new_bt and suggested_bt:
                                    all_bt_set = set(all_basic_types)
                                    closest_existing = basic_type if basic_type in all_bt_set else ''
                                    if not closest_existing and category:
                                        cat_bts = [bt for bt, cat in bt_to_category.items() if cat == category]
                                        if cat_bts:
                                            sku_lower = sku_name.lower()
                                            scored = [(bt, sum(w in bt.lower() for w in sku_lower.split())) for bt in cat_bts]
                                            scored.sort(key=lambda x: -x[1])
                                            closest_existing = scored[0][0]
                                    st.session_state.sku_data[idx]['basic_type'] = closest_existing
                                    st.session_state.suggested_new_bts[idx] = {
                                        'suggested_bt': suggested_bt, 'category': category,
                                        'sku_name': sku_name, 'closest_existing_bt': closest_existing
                                    }
                            
                            processed = batch_end
                        except Exception as e:
                            print(f"[ERROR] Gemini BT+Cat batch error: {str(e)}")
                            st.error(f"Error in Gemini BT+Cat batch {batch_start+1}-{batch_end}: {str(e)}")
                        
                        progress_bar.progress(processed / total_skus, text=f"Phase 1: {processed}/{total_skus} SKUs (Gemini)...")
                
                # ========== PHASE 2: Find Generic Keywords with Gemini ==========
                with st.spinner("Phase 2/2: Finding generic keywords (Gemini)..."):
                    from collections import defaultdict
                    bt_groups = defaultdict(list)
                    for idx, item in enumerate(st.session_state.sku_data):
                        if item['basic_type']:
                            bt_groups[(item['basic_type'], item['category'])].append((idx, item))
                    
                    total_groups = len(bt_groups)
                    groups_done = 0
                    gk_processed = 0
                    
                    for (basic_type, category), group_items in bt_groups.items():
                        try:
                            gk_list = st.session_state.mapping_bt_gk_df.loc[
                                st.session_state.mapping_bt_gk_df.iloc[:, 0] == basic_type,
                                st.session_state.mapping_bt_gk_df.columns[1]
                            ].tolist()
                            
                            if not gk_list:
                                groups_done += 1
                                continue
                            if isinstance(gk_list[0], list):
                                gk_list = gk_list[0]
                            
                            sku_names = [item['sku_name'] for _, item in group_items]
                            group_size = len(sku_names)
                            
                            if group_size == 1:
                                idx, item = group_items[0]
                                prompt = generic_keyword_prompt(item['sku_name'], category, basic_type, gk_list)
                                result, usage_stats = gemini_call_with_usage(gemini_api_key, prompt, GEMINI_MODEL)
                                usage_stats['operation'] = 'Gemini: Find GK'
                                usage_stats['batch'] = f"SKU: {item['sku_name'][:30]}..."
                            else:
                                prompt = batch_generic_keyword_prompt(sku_names, category, basic_type, gk_list)
                                result, usage_stats = gemini_call_with_usage(gemini_api_key, prompt, GEMINI_MODEL)
                                usage_stats['operation'] = 'Gemini: Find GK (batch)'
                                usage_stats['batch'] = f"BT: {basic_type} ({group_size} SKUs)"
                            
                            batch_usage_stats.append(usage_stats)
                            st.session_state.api_usage_stats.append(usage_stats)
                            st.session_state.total_session_cost += usage_stats['total_cost']
                            st.session_state.total_session_tokens += usage_stats['total_tokens']
                            
                            log_gpt_cost_to_sheets(usage_stats, {
                                'sku_count': group_size,
                                'notes': f'[Gemini/{GEMINI_MODEL}] GK for BT: {basic_type}'
                            })
                            
                            result_clean = result.strip()
                            if result_clean.startswith('```'):
                                lines = result_clean.split('\n')
                                result_clean = '\n'.join(lines[1:-1]) if len(lines) > 2 else result_clean
                            
                            parsed = json.loads(result_clean)
                            
                            if group_size == 1:
                                gk_response = parsed.get('selected_generic_keywords', [])
                                if gk_response and isinstance(gk_response[0], dict):
                                    generic_keywords = [kw['keyword'] for kw in gk_response if 'keyword' in kw]
                                else:
                                    generic_keywords = gk_response if isinstance(gk_response, list) else []
                                st.session_state.sku_data[idx]['generic_keywords'] = generic_keywords
                                st.session_state[f"tags_{idx}"] = generic_keywords
                                gk_processed += 1
                            else:
                                results_list = parsed.get('results', [])
                                results_by_name = {r['sku_name']: r.get('selected_generic_keywords', []) for r in results_list}
                                for idx, item in group_items:
                                    gk_response = results_by_name.get(item['sku_name'], [])
                                    if gk_response and isinstance(gk_response[0], dict):
                                        generic_keywords = [kw['keyword'] for kw in gk_response if 'keyword' in kw]
                                    else:
                                        generic_keywords = gk_response if isinstance(gk_response, list) else []
                                    st.session_state.sku_data[idx]['generic_keywords'] = generic_keywords
                                    st.session_state[f"tags_{idx}"] = generic_keywords
                                    gk_processed += 1
                        
                        except Exception as e:
                            print(f"[ERROR] Gemini GK batch error for BT='{basic_type}': {str(e)}")
                        
                        groups_done += 1
                        progress_bar.progress(groups_done / total_groups, text=f"Phase 2: {groups_done}/{total_groups} BT groups (Gemini)...")
                    
                    progress_bar.empty()
                
                # Show final summary
                total_tokens = sum(s['total_tokens'] for s in batch_usage_stats)
                total_cost = sum(s['total_cost'] for s in batch_usage_stats)
                new_bt_count = len(st.session_state.suggested_new_bts)
                
                st.success(f"✅ Gemini tagging complete! {processed} SKUs tagged | {gk_processed} GKs assigned | Tokens: {total_tokens:,} | Cost: ${total_cost:.4f}")
                if new_bt_count > 0:
                    st.info(f"💡 {new_bt_count} SKUs have suggested new basic types.")
                st.rerun()
    
    # Display and edit table
    st.header("📊 SKU Tagging Table")
    
    # Get dropdown options
    category_options = [''] + (st.session_state.category_df['Category'].tolist() if st.session_state.category_df is not None else [])
    bt_options = [''] + (st.session_state.bt_df.iloc[:, 0].tolist() if st.session_state.bt_df is not None else [])
    gk_options = st.session_state.gk_df.iloc[:, 0].tolist() if st.session_state.gk_df is not None else []
    
    # Debug info - Show category assignment status
    with st.expander("🔍 Debug Info - Category Assignment Status"):
        assigned_count = sum(1 for item in st.session_state.sku_data if item['category'])
        st.write(f"**Categories assigned:** {assigned_count}/{len(st.session_state.sku_data)} SKUs")
        if assigned_count > 0:
            st.write("**Sample assignments:**")
            for item in st.session_state.sku_data[:5]:
                if item['category']:
                    st.write(f"- {item['sku_name']}: `{item['category']}`")
        
        # Show available categories in dropdown
        st.write(f"\n**Total categories in dropdown:** {len(category_options) - 1}")
        st.write(f"**First 20 categories in dropdown:** {category_options[1:21]}")
        
        # Check if assigned categories match dropdown options
        assigned_cats = [item['category'] for item in st.session_state.sku_data if item['category']]
        for cat in assigned_cats:
            if cat in category_options:
                st.write(f"✅ `{cat}` - FOUND in dropdown at index {category_options.index(cat)}")
            else:
                st.write(f"❌ `{cat}` - NOT FOUND in dropdown")
                # Check for similar matches
                similar = [opt for opt in category_options if cat.lower() in opt.lower() or opt.lower() in cat.lower()]
                if similar:
                    st.write(f"   Similar options: {similar[:5]}")
    
    # Debug: Check if assigned categories are in the options
    if st.session_state.sku_data:
        assigned_cats = [item['category'] for item in st.session_state.sku_data if item['category']]
        missing_cats = [cat for cat in assigned_cats if cat and cat not in category_options]
        if missing_cats:
            st.warning(f"⚠️ Warning: {len(missing_cats)} assigned categories not found in dropdown options: {missing_cats[:5]}")
            print(f"[WARN] Missing categories in dropdown: {missing_cats}")
            print(f"[INFO] Available categories (first 10): {category_options[1:11]}")
    
    # Custom CSS for compact table
    st.markdown("""
    <style>
    .sku-table {
        font-size: 0.9em;
    }
    .sku-row {
        border-bottom: 1px solid #e0e0e0;
        padding: 8px 0;
    }
    .stSelectbox, .stTextInput {
        margin-bottom: 0px !important;
    }
    div[data-testid="column"] {
        padding: 5px;
    }
    /* Make disabled text inputs black instead of grey */
    input:disabled {
        color: #000000 !important;
        -webkit-text-fill-color: #000000 !important;
        opacity: 1 !important;
    }
    /* Hide "Select all" and "Select X matches" options in multiselect dropdowns */
    div[data-testid="stMultiSelect"] li[role="option"]:has(span[data-testid="multiselect-option-selectAll"]),
    div[data-testid="stMultiSelect"] li[role="option"]:has(span[data-testid="multiselect-option-selectVisible"]) {
        display: none !important;
    }
    /* Highlight category selectbox for multi-category basic types */
    div[data-testid="stColumn"]:has(.cat-needs-review) div[data-baseweb="select"] > div {
        border: 2px solid #ff4b4b !important;
        box-shadow: 0 0 4px rgba(255, 75, 75, 0.4) !important;
    }
    /* Remove gap in category column when it has the review warning */
    div[data-testid="stColumn"]:has(.cat-needs-review) div[data-testid="stVerticalBlock"] {
        gap: 0 !important;
    }
    /* Remove gap in the last column (Generic Keywords) for table rows only */
    div[data-testid="stColumn"]:nth-child(5) div[data-testid="stVerticalBlock"] {
        gap: 0 !important;
    }
    /* Prevent multiselect pills from truncating text with ellipsis */
    span[data-baseweb="tag"] {
        max-width: none !important;
    }
    span[data-baseweb="tag"] span {
        max-width: none !important;
        overflow: visible !important;
        text-overflow: unset !important;
    }
    /* Green outline for new (custom) basic type selectbox */
    div[data-testid="stColumn"]:has(.bt-is-new) div[data-baseweb="select"] > div {
        border: 2px solid #28a745 !important;
        box-shadow: 0 0 4px rgba(40, 167, 69, 0.4) !important;
    }
    /* Remove vertical gap when new-bt label is shown */
    div[data-testid="stColumn"]:has(.bt-is-new) div[data-testid="stVerticalBlock"] {
        gap: 0 !important;
    }
    /* GK refresh button alignment - make the nested columns row align items to top */
    div[data-testid="stColumn"]:nth-child(5) div[data-testid="stHorizontalBlock"] {
        align-items: flex-start !important;
        gap: 0.25rem !important;
    }
    /* The refresh button column - remove extra spacing */
    div[data-testid="stColumn"]:nth-child(5) div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:last-child {
        padding-top: 0 !important;
        margin-top: 0 !important;
    }
    div[data-testid="stColumn"]:nth-child(5) div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:last-child > div {
        padding-top: 0 !important;
    }
    /* Make the refresh button smaller and aligned */
    div[data-testid="stColumn"]:nth-child(5) div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:last-child button {
        padding: 0.25rem 0.5rem !important;
        min-height: 38px !important;
        height: 38px !important;
        line-height: 1 !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Hide "Select all" / "Select X matches" in multiselect dropdowns and auto-focus first real option
    components.html("""
    <script>
    const pdoc = window.parent.document;
    const HIDE_RE = /select all|\\d+ match|select \\d+/i;
    function fixMultiselect() {
        // Target listbox items
        pdoc.querySelectorAll('li[role="option"]').forEach(function(li) {
            var text = (li.textContent || '').trim();
            if (HIDE_RE.test(text)) {
                li.style.display = 'none';
            }
        });
        // Target any element with select-all related data-testid
        pdoc.querySelectorAll('[data-testid*="select"]').forEach(function(el) {
            var tid = el.getAttribute('data-testid') || '';
            if (/selectAll|selectVisible|select-all|select-visible|selectMatches/i.test(tid)) {
                var li = el.closest('li') || el;
                li.style.display = 'none';
            }
        });
        // Target header sections above listbox (Streamlit 1.50+)
        pdoc.querySelectorAll('div[data-baseweb="popover"] div, div[data-baseweb="menu"] div').forEach(function(div) {
            var text = (div.textContent || '').trim();
            // Only target small divs that just contain the "Select all" / "X matches" text
            if (div.children.length <= 2 && HIDE_RE.test(text) && text.length < 30) {
                div.style.display = 'none';
            }
        });
        // Focus first visible option in newly opened lists
        pdoc.querySelectorAll('ul[role="listbox"]').forEach(function(ul) {
            if (ul.dataset.hlfixed) return;
            var items = ul.querySelectorAll('li[role="option"]');
            for (var i = 0; i < items.length; i++) {
                if (items[i].style.display !== 'none' && items[i].offsetParent !== null) {
                    items[i].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                    ul.dataset.hlfixed = '1';
                    break;
                }
            }
        });
    }
    var obs = new MutationObserver(fixMultiselect);
    obs.observe(pdoc.body, { childList: true, subtree: true });
    </script>
    """, height=0)

    def _get_gk_options_for_bt(basic_type):
        """Get GK options filtered by the SKU's basic type, falling back to all GKs."""
        if basic_type and st.session_state.mapping_bt_gk_df is not None:
            gk_list = st.session_state.mapping_bt_gk_df.loc[
                st.session_state.mapping_bt_gk_df.iloc[:, 0] == basic_type,
                st.session_state.mapping_bt_gk_df.columns[1]
            ].tolist()
            # Flatten
            filtered = []
            for item in gk_list:
                if isinstance(item, list):
                    filtered.extend(item)
                elif isinstance(item, str):
                    parsed = safe_parse_list(item)
                    if isinstance(parsed, list):
                        filtered.extend(parsed)
                    else:
                        filtered.append(item)
            if filtered:
                return sorted(set(filtered))
        # Fallback to all GKs
        return gk_options

    def _refresh_gks_with_gemini(idx):
        """Fetch new GKs for a single SKU using Gemini API based on current Basic Type."""
        item = st.session_state.sku_data[idx]
        basic_type = item.get('basic_type', '')
        category = item.get('category', '')
        sku_name = item.get('sku_name', '')
        
        if not basic_type:
            st.toast(f"⚠️ No Basic Type set for '{sku_name[:30]}...'", icon="⚠️")
            return
        
        if not gemini_api_key:
            st.toast("⚠️ GEMINI_API_KEY not set", icon="⚠️")
            return
        
        # Get GK list for the basic type
        gk_list = []
        if st.session_state.mapping_bt_gk_df is not None:
            gk_rows = st.session_state.mapping_bt_gk_df.loc[
                st.session_state.mapping_bt_gk_df.iloc[:, 0] == basic_type,
                st.session_state.mapping_bt_gk_df.columns[1]
            ].tolist()
            if gk_rows:
                if isinstance(gk_rows[0], list):
                    gk_list = gk_rows[0]
                else:
                    gk_list = gk_rows
        
        if not gk_list:
            st.toast(f"⚠️ No GK mapping found for BT '{basic_type}'", icon="⚠️")
            return
        
        try:
            # Call Gemini API
            prompt = generic_keyword_prompt(sku_name, category, basic_type, gk_list)
            result, usage_stats = gemini_call_with_usage(gemini_api_key, prompt, GEMINI_MODEL)
            
            # Track usage
            usage_stats['operation'] = 'Gemini: Refresh GK'
            usage_stats['batch'] = f"SKU: {sku_name[:30]}..."
            st.session_state.api_usage_stats.append(usage_stats)
            st.session_state.total_session_cost += usage_stats['total_cost']
            st.session_state.total_session_tokens += usage_stats['total_tokens']
            
            # Log to Google Sheets
            log_gpt_cost_to_sheets(usage_stats, {
                'sku_count': 1,
                'notes': f'[Gemini/{GEMINI_MODEL}] Refresh GK for: {sku_name[:50]}'
            })
            
            # Parse response
            result_clean = result.strip()
            if result_clean.startswith('```'):
                lines = result_clean.split('\n')
                result_clean = '\n'.join(lines[1:-1]) if len(lines) > 2 else result_clean
            
            parsed = json.loads(result_clean)
            gk_response = parsed.get('selected_generic_keywords', [])
            
            # Handle confidence-level format
            if gk_response and isinstance(gk_response[0], dict):
                generic_keywords = [kw['keyword'] for kw in gk_response if 'keyword' in kw]
            else:
                generic_keywords = gk_response if isinstance(gk_response, list) else []
            
            # Update sku_data (the widget will pick up new values after rerun)
            st.session_state.sku_data[idx]['generic_keywords'] = generic_keywords
            # Delete the widget key so it re-initializes with new default on rerun
            if f"tags_{idx}" in st.session_state:
                del st.session_state[f"tags_{idx}"]
            
            st.toast(f"✅ Refreshed {len(generic_keywords)} GKs for '{sku_name[:25]}...'", icon="✅")
            print(f"[OK] Gemini GK refresh for '{sku_name}': {generic_keywords}")
            
        except Exception as e:
            st.toast(f"❌ Error: {str(e)[:50]}", icon="❌")
            print(f"[ERROR] Gemini GK refresh failed for '{sku_name}': {e}")

    def _render_keywords_fragment(idx, gk_options):
        """Render keyword multiselect + manual entry + refresh button."""
        current_keywords = st.session_state.sku_data[idx]['generic_keywords']
        
        ADD_NEW_SENTINEL = "+ Add New"
        
        # Build options: all known GKs + any custom ones already on this SKU
        all_options = list(gk_options) if gk_options else []
        for kw in current_keywords:
            if kw not in all_options:
                all_options.append(kw)
        
        is_adding = st.session_state.get(f"gk_adding_new_{idx}", False)
        
        # Layout: multiselect takes most space, refresh button on the right (top-aligned)
        gk_col, refresh_col = st.columns([0.90, 0.10], vertical_alignment="top", gap="small")
        
        with gk_col:
            if not is_adding:
                # Normal mode: multiselect with "+ Add New" as first option (always visible at top)
                options_with_add = [ADD_NEW_SENTINEL] + all_options
                
                # Use on_change to detect "+ Add New" selection (can't modify widget key after render)
                def _on_gk_change(idx=idx):
                    selected = st.session_state.get(f"tags_{idx}", [])
                    if ADD_NEW_SENTINEL in selected:
                        # Strip sentinel, save real keywords, switch to adding mode
                        real = [kw for kw in selected if kw != ADD_NEW_SENTINEL]
                        st.session_state.sku_data[idx]['generic_keywords'] = real
                        st.session_state[f"tags_{idx}"] = real
                        st.session_state[f"gk_adding_new_{idx}"] = True
                    else:
                        st.session_state.sku_data[idx]['generic_keywords'] = list(selected)
                
                st.multiselect(
                    "GK",
                    options=options_with_add,
                    default=current_keywords,
                    key=f"tags_{idx}",
                    label_visibility="collapsed",
                    placeholder="Select keywords...",
                    on_change=_on_gk_change
                )
            else:
                # Adding mode: multiselect (no sentinel) + text input below
                def _on_gk_select_change(idx=idx):
                    selected = st.session_state.get(f"tags_{idx}", [])
                    st.session_state.sku_data[idx]['generic_keywords'] = list(selected)
                
                st.multiselect(
                    "GK",
                    options=all_options,
                    default=current_keywords,
                    key=f"tags_{idx}",
                    label_visibility="collapsed",
                    placeholder="Select keywords...",
                    on_change=_on_gk_select_change
                )
                
                def _on_new_gk(idx=idx):
                    val = st.session_state.get(f"new_gk_{idx}", "").strip()
                    if val:
                        kw_cap = val.title()
                        current = st.session_state.sku_data[idx]['generic_keywords']
                        if kw_cap.lower() not in {k.lower() for k in current}:
                            current.append(kw_cap)
                            st.session_state.sku_data[idx]['generic_keywords'] = current
                        st.session_state[f"tags_{idx}"] = current
                    st.session_state[f"new_gk_{idx}"] = ""
                    st.session_state[f"gk_adding_new_{idx}"] = False
                    # Flag to refocus the multiselect after rerun
                    st.session_state[f"gk_refocus_{idx}"] = True
                
                st.text_input(
                    "Add GK",
                    key=f"new_gk_{idx}",
                    label_visibility="collapsed",
                    placeholder="Type new keyword and press Enter...",
                    on_change=_on_new_gk
                )
                # Auto-focus the new GK text input
                components.html(
                    f"""
                    <script>
                    const inputs = window.parent.document.querySelectorAll('input[aria-label="Add GK"]');
                    if (inputs.length > 0) {{ inputs[inputs.length - 1].focus(); }}
                    </script>
                    """,
                    height=0
                )
        
        with refresh_col:
            # Refresh button - calls Gemini to get new GKs based on current BT
            has_bt = bool(st.session_state.sku_data[idx].get('basic_type', ''))
            has_gemini = bool(gemini_api_key)
            
            def _on_refresh_gk(idx=idx):
                st.session_state[f"gk_refresh_pending_{idx}"] = True
            
            st.button(
                "🔄",
                key=f"refresh_gk_{idx}",
                on_click=_on_refresh_gk,
                disabled=not (has_bt and has_gemini),
                help="Refresh GKs using Gemini (based on current Basic Type)" if has_gemini else "Set GEMINI_API_KEY to enable",
                use_container_width=True
            )
        
        # Handle pending refresh (execute after button click triggers rerun)
        if st.session_state.pop(f"gk_refresh_pending_{idx}", False):
            with st.spinner("🔄 Fetching GKs..."):
                _refresh_gks_with_gemini(idx)
                st.rerun()
        
        # After adding a new GK, refocus the multiselect input for THIS SKU
        if st.session_state.pop(f"gk_refocus_{idx}", False):
            page_offset = idx - (st.session_state.page_index * ROWS_PER_PAGE)
            components.html(
                f"""
                <script>
                // Find all GK multiselects on the page and pick this SKU's by position
                const allGK = window.parent.document.querySelectorAll('div[data-testid="stMultiSelect"]');
                const pagePos = {page_offset};
                if (allGK.length > pagePos && pagePos >= 0) {{
                    const input = allGK[pagePos].querySelector('input');
                    if (input) {{ input.focus(); input.click(); }}
                }}
                </script>
                """,
                height=0
            )

    # Table header
    header_cols = st.columns([0.3, 3, 1.7, 1.7, 3.8])
    with header_cols[0]:
        st.markdown("**#**")
    with header_cols[1]:
        st.markdown("**SKU Name**")
    with header_cols[2]:
        st.markdown("**Category**")
    with header_cols[3]:
        st.markdown("**Basic Type**")
    with header_cols[4]:
        st.markdown("**Generic Keywords**")
    
    st.divider()
    
    # Pagination: determine current page slice
    _init_page_widget_keys(st.session_state.page_index)
    page_start = st.session_state.page_index * ROWS_PER_PAGE
    page_end = min(page_start + ROWS_PER_PAGE, len(st.session_state.sku_data))
    page_items = list(enumerate(st.session_state.sku_data))[page_start:page_end]
    
    # Display each SKU as a row (only current page)
    for idx, item in page_items:
        cols = st.columns([0.3, 3, 1.7, 1.7, 3.8])
        
        with cols[0]:
            st.markdown(f"**{idx + 1}**")
        
        with cols[1]:
            st.text_input("SKU", value=item['sku_name'], disabled=True, key=f"sku_{idx}", label_visibility="collapsed")
        
        with cols[2]:
            # STREAMLIT WIDGET STATE PATTERN:
            # Use index-based rendering for selectboxes so values survive page navigation.
            # Streamlit clears session_state widget keys when the widget isn't rendered,
            # so pre-setting session_state[key] doesn't work across pages.
            # Instead: read value from sku_data, compute index, pass to selectbox.
            
            # Dynamically check if the current basic type is mapped to multiple categories
            current_bt_for_review = item.get('basic_type', '')
            needs_review = current_bt_for_review in st.session_state.multi_cat_bts
            if needs_review:
                # Hidden marker div - CSS :has() selector will highlight the selectbox
                st.markdown(
                    '<div class="cat-needs-review" style="display:none;"></div>',
                    unsafe_allow_html=True
                )
            
            # Only initialize session_state widget key when it doesn't exist (first render).
            # Don't overwrite user selections - use on_change callback to sync to sku_data.
            cat_key = f"cat_{idx}"
            if cat_key not in st.session_state:
                cat_value = item.get('category', '')
                if cat_value and cat_value in category_options:
                    st.session_state[cat_key] = cat_value
                else:
                    st.session_state[cat_key] = ''
            
            def _on_cat_select_change(idx=idx):
                """Sync category selectbox value back to sku_data immediately on change."""
                val = st.session_state.get(f"cat_{idx}", "")
                if val != st.session_state.sku_data[idx].get('category', ''):
                    st.session_state.sku_data[idx]['category'] = val
            
            selected_category = st.selectbox(
                "Cat",
                options=category_options,
                key=cat_key,
                label_visibility="collapsed",
                on_change=_on_cat_select_change
            )
            
            if needs_review:
                possible_cats_str = ', '.join(st.session_state.multi_cat_bts.get(current_bt_for_review, []))
                st.markdown(
                    f'<small style="color: #ff4b4b;">⚠️ {current_bt_for_review} in: {possible_cats_str}</small>',
                    unsafe_allow_html=True
                )
        
        with cols[3]:
            # Filter basic types based on selected category
            # Use selected_category from the just-rendered category selectbox
            effective_category = selected_category or item.get('category', '')
            if effective_category and st.session_state.mapping_cat_bt_df is not None:
                # Category is in column 1 (Category Tag Type), Basic Types in column 0 (Basic Tag Type)
                filtered_bt = st.session_state.mapping_cat_bt_df.loc[
                    st.session_state.mapping_cat_bt_df.iloc[:, 1] == effective_category,
                    st.session_state.mapping_cat_bt_df.columns[0]
                ].tolist()
                if filtered_bt and len(filtered_bt) > 0:
                    if isinstance(filtered_bt[0], list):
                        filtered_bt = filtered_bt[0]
                    bt_suggestions = [''] + filtered_bt + ['+ Add New']
                else:
                    bt_suggestions = bt_options + ['+ Add New']
            else:
                bt_suggestions = bt_options + ['+ Add New']
            
            # Check if there's a suggested new BT that was accepted (check BEFORE widget renders)
            accepted_suggestion_key = f"accept_new_bt_{idx}"
            if accepted_suggestion_key in st.session_state and st.session_state[accepted_suggestion_key]:
                if idx in st.session_state.suggested_new_bts:
                    suggestion = st.session_state.suggested_new_bts[idx]
                    suggested_bt = suggestion['suggested_bt']
                    suggested_cat = suggestion['category']
                    
                    # Update sku_data with the new basic type
                    st.session_state.sku_data[idx]['basic_type'] = suggested_bt
                    # Also update the Basic Type selectbox state so the UI shows it
                    st.session_state[f"bt_select_{idx}"] = suggested_bt
                    
                    # Track as accepted new basic type
                    if suggested_bt not in st.session_state.accepted_new_bts:
                        st.session_state.accepted_new_bts[suggested_bt] = {
                            'category': suggested_cat,
                            'generic_keywords': [],
                            'source_sku': suggestion['sku_name']
                        }
                    
                    # Remove from suggestions
                    del st.session_state.suggested_new_bts[idx]
                
                st.session_state[accepted_suggestion_key] = False
            
            # Check if user dismissed a suggestion
            dismissed_key = f"dismiss_new_bt_{idx}"
            if dismissed_key in st.session_state and st.session_state[dismissed_key]:
                if idx in st.session_state.suggested_new_bts:
                    del st.session_state.suggested_new_bts[idx]
                st.session_state[dismissed_key] = False
            
            # Build options list - include current value if it's custom (not in standard list)
            current_bt = item['basic_type']
            
            dropdown_options = bt_suggestions.copy()
            if current_bt and current_bt not in dropdown_options and current_bt != '+ Add New':
                # Insert custom value before the "+ Add New" option
                dropdown_options = dropdown_options[:-1] + [current_bt] + ['+ Add New']
            
            # Always sync session_state widget key from sku_data (source of truth)
            # But skip when user is actively adding a new BT (to not override their selection)
            selectbox_key = f"bt_select_{idx}"
            is_adding_new = st.session_state.get(f"bt_adding_new_{idx}", False)
            if not is_adding_new:
                if current_bt and current_bt in dropdown_options:
                    st.session_state[selectbox_key] = current_bt
                elif selectbox_key not in st.session_state:
                    st.session_state[selectbox_key] = ''
            
            def _on_bt_select_change(idx=idx):
                val = st.session_state.get(f"bt_select_{idx}", "")
                if val == '+ Add New':
                    st.session_state[f"bt_adding_new_{idx}"] = True
                elif val:
                    st.session_state.sku_data[idx]['basic_type'] = val
                    st.session_state[f"bt_adding_new_{idx}"] = False
                    st.session_state[f"bt_custom_{idx}"] = ""
                else:
                    st.session_state[f"bt_adding_new_{idx}"] = False
            
            selected_bt = st.selectbox(
                "BT",
                options=dropdown_options,
                key=selectbox_key,
                label_visibility="collapsed",
                on_change=_on_bt_select_change
            )
            
            # Check if user selected "Type new..."
            custom_bt_key = f"bt_custom_{idx}"
            if custom_bt_key not in st.session_state:
                st.session_state[custom_bt_key] = ""
            
            if selected_bt == '+ Add New':
                # Show text input for custom basic type
                def _on_custom_bt_change(idx=idx):
                    val = st.session_state.get(f"bt_custom_{idx}", "").strip()
                    if val:
                        st.session_state.sku_data[idx]['basic_type'] = val
                        # Stop "adding new" mode so dropdown switches to the new value
                        st.session_state[f"bt_adding_new_{idx}"] = False
                        if val not in st.session_state.accepted_new_bts:
                            current_cat = st.session_state.sku_data[idx].get('category', '') or 'Uncategorized'
                            st.session_state.accepted_new_bts[val] = {
                                'category': current_cat,
                                'generic_keywords': [],
                                'source_sku': st.session_state.sku_data[idx]['sku_name']
                            }

                st.text_input(
                    "New BT:",
                    key=custom_bt_key,
                    label_visibility="collapsed",
                    placeholder="Type new basic type...",
                    on_change=_on_custom_bt_change
                )
                # Auto-focus the new BT text input
                components.html(
                    f"""
                    <script>
                    const inputs = window.parent.document.querySelectorAll('input[aria-label="New BT:"]');
                    if (inputs.length > 0) {{ inputs[inputs.length > {idx + 1} ? {idx} : inputs.length - 1].focus(); }}
                    </script>
                    """,
                    height=0
                )
            else:
                # Sync selection back to sku_data
                if selected_bt and selected_bt != item['basic_type']:
                    st.session_state.sku_data[idx]['basic_type'] = selected_bt
                
                # Show green highlight if this is a new (custom) basic type
                all_existing_bts = set()
                if st.session_state.bt_df is not None:
                    all_existing_bts = set(st.session_state.bt_df.iloc[:, 0].tolist())
                if selected_bt and selected_bt not in all_existing_bts:
                    st.markdown('<div class="bt-is-new" style="display:none;"></div>', unsafe_allow_html=True)
                    st.markdown(
                        '<small style="color: #28a745;">New Basic Type</small>',
                        unsafe_allow_html=True
                    )
            
            # Show LLM suggested new basic type if available
            if idx in st.session_state.suggested_new_bts:
                suggestion = st.session_state.suggested_new_bts[idx]
                suggested_bt = suggestion['suggested_bt']
                
                st.markdown(f"<small style='color: #1f77b4;'>💡 Suggest: <b>{suggested_bt}</b></small>", unsafe_allow_html=True)
                # Accept / Dismiss buttons inline
                col_accept, col_dismiss = st.columns(2)
                with col_accept:
                    def accept_suggestion(idx=idx):
                        st.session_state[f"accept_new_bt_{idx}"] = True
                    st.button("✓ Use", key=f"accept_bt_{idx}", on_click=accept_suggestion, help=f"Use '{suggested_bt}' as basic type")
                with col_dismiss:
                    def dismiss_suggestion(idx=idx):
                        st.session_state[f"dismiss_new_bt_{idx}"] = True
                    st.button("✗ Keep", key=f"dismiss_bt_{idx}", on_click=dismiss_suggestion, help="Keep the current basic type")
        
        with cols[4]:
            # Render keywords in a fragment to prevent full-page reruns on rapid edits
            # This avoids WebSocket "Cached ForwardMsg MISS" errors when quickly deleting keywords
            _render_keywords_fragment(idx, gk_options)
        
        st.markdown("<div style='margin: 5px 0;'></div>", unsafe_allow_html=True)
    
    # Save & Navigate
    st.header("📤 Save & Navigate")
    
    # Calculate pagination info
    total_skus = len(st.session_state.sku_data)
    total_pages = (total_skus + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE
    current_page = st.session_state.page_index
    page_start = current_page * ROWS_PER_PAGE
    page_end_idx = min(page_start + ROWS_PER_PAGE, total_skus)
    
    # Detect all new basic types (both manually entered and from suggestions) — ALL SKUs
    def detect_new_basic_types():
        all_existing_bts = set()
        if st.session_state.bt_df is not None:
            all_existing_bts = set(st.session_state.bt_df.iloc[:, 0].tolist())
        
        new_bts = {}
        for item in st.session_state.sku_data:
            basic_type = item.get('basic_type', '')
            category = item.get('category', '')
            if not basic_type:
                continue
            if basic_type not in all_existing_bts:
                if basic_type not in new_bts:
                    new_bts[basic_type] = {
                        'category': category if category else 'Uncategorized',
                        'generic_keywords': set(),
                        'source_sku': item['sku_name']
                    }
                if item.get('generic_keywords'):
                    new_bts[basic_type]['generic_keywords'].update(item['generic_keywords'])
        for bt in new_bts:
            new_bts[bt]['generic_keywords'] = list(new_bts[bt]['generic_keywords'])
        return new_bts
    
    # Detect manually added generic keywords — ALL SKUs
    def detect_new_gk_mappings():
        new_mappings = {}
        for item in st.session_state.sku_data:
            basic_type = item.get('basic_type', '')
            current_keywords = item.get('generic_keywords', [])
            if not basic_type or not current_keywords:
                continue
            existing_keywords = get_existing_gk_for_basic_type(basic_type)
            new_keywords = [kw for kw in current_keywords if kw not in existing_keywords]
            if new_keywords:
                if basic_type not in new_mappings:
                    new_mappings[basic_type] = set()
                new_mappings[basic_type].update(new_keywords)
        return {bt: list(keywords) for bt, keywords in new_mappings.items()}
    
    # Show detected new mappings
    new_gk_mappings = detect_new_gk_mappings()
    new_basic_types = detect_new_basic_types()
    
    if new_gk_mappings:
        with st.expander("🆕 New Generic Keywords Detected", expanded=True):
            st.info("The following generic keywords were manually added and will be synced to Google Sheets when you click 'Update Tags':")
            for bt, keywords in new_gk_mappings.items():
                st.markdown(f"**{bt}:** {', '.join(keywords)}")
    
    if new_basic_types:
        with st.expander("🆕 New Basic Types Detected", expanded=True):
            st.info("The following new basic types will be added to Google Sheets when you click 'Update Tags':")
            for bt_name, bt_info in new_basic_types.items():
                st.markdown(f"**{bt_name}** → Category: *{bt_info['category']}*")
                if bt_info['generic_keywords']:
                    st.markdown(f"  - Generic Keywords: {', '.join(bt_info['generic_keywords'])}")
    
    # Page navigation info
    st.markdown(f"**Page {current_page + 1} of {total_pages}** — showing SKUs {page_start + 1}–{page_end_idx} of {total_skus}")
    
    nav_col1, nav_col2, nav_col3 = st.columns([1, 1, 1])
    
    with nav_col1:
        prev_disabled = (current_page == 0)
        if st.button("⬅️ Previous Page", use_container_width=True, disabled=prev_disabled):
            # Sync current page to Google Sheet before navigating
            with st.spinner("Saving tags to Google Sheet..."):
                success = sync_current_page_to_sheet()
                if success:
                    st.toast("✅ Tags saved to Google Sheet", icon="✅")
                else:
                    st.toast("⚠️ Some tags may not have been saved", icon="⚠️")
            st.session_state.page_index -= 1
            st.rerun()
    
    with nav_col2:
        # Update Tags button - syncs current data to Google Sheet
        if st.button("📤 Update Tags", use_container_width=True, type="primary", help="Save all tags to Google Sheet"):
            with st.spinner("Saving tags to Google Sheet..."):
                # First sync new mappings
                if new_gk_mappings or new_basic_types:
                    progress = st.progress(0, text="Syncing new mappings...")
                    total_steps = len(new_basic_types) + (1 if new_gk_mappings else 0) + 1
                    step = 0
                    
                    # Add new basic types
                    if new_basic_types:
                        for bt_name, bt_info in new_basic_types.items():
                            success = add_new_bt_to_mappings(
                                bt_name,
                                bt_info['category'],
                                bt_info.get('generic_keywords', [])
                            )
                            if success:
                                log_new_bt_update(bt_name, bt_info['category'], bt_info.get('source_sku', 'Unknown'), 'added')
                                print(f"[OK] Added new BT '{bt_name}' to Google Sheets")
                            step += 1
                            progress.progress(step / total_steps, text=f"Added BT: {bt_name}")
                        st.session_state.accepted_new_bts = {}
                    
                    # Sync new GK mappings
                    existing_bt_gk_mappings = {bt: kws for bt, kws in new_gk_mappings.items() if bt not in new_basic_types}
                    if existing_bt_gk_mappings:
                        progress.progress(step / total_steps, text="Syncing new generic keywords...")
                        update_bt_gk_mappings(existing_bt_gk_mappings)
                        step += 1
                    
                    progress.progress(1.0, text="Updating SKU tags...")
                    progress.empty()
                
                # Now sync SKU tags to the Main sheet
                success = sync_current_page_to_sheet()
                if success:
                    st.success("✅ All tags saved to Google Sheet!")
                else:
                    st.warning("⚠️ Some tags may not have been saved. Check the console for details.")
    
    with nav_col3:
        is_last_page = (current_page + 1) >= total_pages
        if st.button("Next Page ➡️", use_container_width=True, disabled=is_last_page):
            # Sync current page to Google Sheet before navigating
            with st.spinner("Saving tags to Google Sheet..."):
                success = sync_current_page_to_sheet()
                if success:
                    st.toast("✅ Tags saved to Google Sheet", icon="✅")
                else:
                    st.toast("⚠️ Some tags may not have been saved", icon="⚠️")
            st.session_state.page_index += 1
            st.rerun()