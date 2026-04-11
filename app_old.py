import streamlit as st
import pandas as pd
import numpy as np
from openai import AzureOpenAI
import json
import os
import requests
from datetime import datetime
from dotenv import load_dotenv
from streamlit_tags import st_tags
import streamlit.components.v1 as components
from utils import gpt_call, gpt_call_with_usage, category_prompt, basictype_prompt, generic_keyword_prompt, batch_category_prompt, batch_basictype_prompt, batch_basictype_category_prompt, batch_embedding_bt_category_prompt
from embedding_utils import build_bt_embeddings, get_sku_embeddings, find_similar_basic_types_batch, load_cache, EMBEDDING_BATCH_SIZE

# Load environment variables from .env file
load_dotenv()

# Page config
st.set_page_config(page_title="SKU Tagging System", layout="wide", initial_sidebar_state="collapsed")

# Title
st.title("🏷️ SKU Tagging System")
st.markdown("Upload SKUs and automatically tag them with Categories, Basic Types, and Generic Keywords")

# Azure OpenAI configuration (loaded from environment variables)
open_api_key = os.getenv('AZURE_OPENAI_API_KEY')
api_version = os.getenv('AZURE_OPENAI_API_VERSION', '2024-02-01')
azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
deployment_name = os.getenv('AZURE_OPENAI_DEPLOYMENT_NAME')
embedding_deployment_name = os.getenv('AZURE_OPENAI_EMBEDDING_DEPLOYMENT', '')

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
if 'gk_version' not in st.session_state:
    # Version counter to force st_tags re-render after GPT updates (not on manual edits)
    st.session_state.gk_version = 0

# Load mapping files from Google Sheets
import os

# Google Sheets configuration
SPREADSHEET_ID = "1-1DejLMWTf7YbUNKVa84fIiguL1XXb14wKJ-w28yOh4"
SHEET_IDS = {
    "BT_GK_mappings": "1433148032",
    "BT_CT_mappings": "1757740042"
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
    
    if gk_list and len(gk_list) > 0:
        if isinstance(gk_list[0], list):
            return set(gk_list[0])
        else:
            return set(gk_list)
    return set()


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
    
    # Try to parse as JSON first
    if value.startswith('[') or value.startswith('{'):
        try:
            return json.loads(value.replace("'", '"'))
        except:
            # If JSON fails, try ast.literal_eval
            try:
                import ast
                return ast.literal_eval(value)
            except:
                # If all parsing fails, return as-is
                return value
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
                    all_keywords.append(keywords)
            st.session_state.gk_df = pd.DataFrame({
                'Generic Keywords': sorted(list(set(all_keywords)))
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

# Upload SKU list file
st.subheader("📤 Upload SKU List")
uploaded_file = st.file_uploader(
    "Upload a CSV file with SKU names (first row should be the header)",
    type=['csv'],
    help="Upload a CSV file containing SKU names. The first row should be the header row."
)

if uploaded_file is not None:
    try:
        sku_df = pd.read_csv(uploaded_file)
        st.info(f"📁 Loaded SKUs from uploaded file: {uploaded_file.name}")
        
        # Get column name (assume first column or 'name' column)
        sku_column = 'name' if 'name' in sku_df.columns else sku_df.columns[0]
        
        # Store the uploaded file name to detect new uploads
        if 'uploaded_file_name' not in st.session_state:
            st.session_state.uploaded_file_name = None
        
        # Initialize sku_data if not exists or if new file uploaded
        if (st.session_state.sku_data is None or 
            len(st.session_state.sku_data) != len(sku_df) or
            st.session_state.uploaded_file_name != uploaded_file.name):
            
            st.session_state.uploaded_file_name = uploaded_file.name
            st.session_state.sku_data = []
            for idx, row in sku_df.iterrows():
                st.session_state.sku_data.append({
                    'sku_name': row[sku_column],
                    'category': '',
                    'basic_type': '',
                    'generic_keywords': []
                })
                # IMPORTANT: Initialize widget state for selectboxes and st_tags
                # Streamlit widgets with a 'key' parameter store their value in st.session_state[key].
                # We must initialize these to match sku_data, otherwise the widgets will default to 
                # the first option and ignore values set in sku_data.
                st.session_state[f"cat_{idx}"] = ''
                st.session_state[f"bt_{idx}"] = ''
                st.session_state[f"tags_{idx}"] = []
        
        st.success(f"✅ Loaded {len(st.session_state.sku_data)} SKUs from column: '{sku_column}'")
    except Exception as e:
        st.error(f"❌ Error loading uploaded file: {str(e)}")
        st.stop()
else:
    st.warning("⚠️ Please upload a CSV file with SKU names to continue")
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
        if st.button("🔍 Find Basic Type and Category", disabled=not all_files_loaded, use_container_width=True):
            if all_files_loaded:
                with st.spinner("Finding basic types and categories in batches..."):
                    # Get ALL unique basic types from BT_CT_mappings (first column)
                    all_basic_types = st.session_state.mapping_cat_bt_df.iloc[:, 0].unique().tolist()
                    
                    # Build BT to Category mapping dictionary
                    # Note: A basic type can be in multiple categories
                    bt_to_category = {}
                    for _, row in st.session_state.mapping_cat_bt_df.iterrows():
                        bt = row.iloc[0]  # Basic Type (first column)
                        cat = row.iloc[1]  # Category (second column)
                        bt_to_category[bt] = cat
                    
                    total_skus = len(st.session_state.sku_data)
                    
                    progress_bar = st.progress(0)
                    processed = 0
                    batch_usage_stats = []
                    
                    # Clear previous suggestions and review flags
                    st.session_state.suggested_new_bts = {}
                    st.session_state.needs_category_review = set()
                    
                    # Process in batches
                    for batch_start in range(0, total_skus, BT_CATEGORY_BATCH_SIZE):
                        batch_end = min(batch_start + BT_CATEGORY_BATCH_SIZE, total_skus)
                        batch_skus = [item['sku_name'] for item in st.session_state.sku_data[batch_start:batch_end]]
                        
                        print(f"\n>>> Processing BT & Category Batch: SKUs {batch_start+1}-{batch_end} ({len(batch_skus)} items)")
                        
                        try:
                            result, usage_stats = gpt_call_with_usage(
                                open_api_key, api_version, azure_endpoint, deployment_name,
                                batch_basictype_category_prompt(batch_skus, all_basic_types, bt_to_category)
                            )
                            
                            # Track usage stats
                            usage_stats['operation'] = 'Find BT and CT'
                            usage_stats['batch'] = f"SKUs {batch_start+1}-{batch_end}"
                            batch_usage_stats.append(usage_stats)
                            st.session_state.api_usage_stats.append(usage_stats)
                            st.session_state.total_session_cost += usage_stats['total_cost']
                            st.session_state.total_session_tokens += usage_stats['total_tokens']
                            
                            # Log to Google Sheets
                            log_gpt_cost_to_sheets(usage_stats, {
                                'sku_count': len(batch_skus),
                                'notes': f'Batch processing {len(batch_skus)} SKUs for BT and Category assignment'
                            })
                            
                            # Clean result to remove markdown code fences
                            result_clean = result.strip()
                            if result_clean.startswith('```'):
                                lines = result_clean.split('\n')
                                result_clean = '\n'.join([l for l in lines if not l.startswith('```')])
                            
                            batch_results = json.loads(result_clean)['results']
                            
                            # Update each SKU in the batch
                            for result_item in batch_results:
                                sku_name = result_item['sku']
                                basic_type = result_item['basic_type']
                                # Get category from result (now included in LLM response)
                                category = result_item.get('category', bt_to_category.get(basic_type, ''))
                                is_new_bt = result_item.get('is_new_bt', False)
                                suggested_bt = result_item.get('suggested_bt', None)
                                
                                # Find the SKU in our data and update
                                for idx in range(batch_start, batch_end):
                                    if st.session_state.sku_data[idx]['sku_name'] == sku_name:
                                        st.session_state.sku_data[idx]['basic_type'] = basic_type
                                        st.session_state.sku_data[idx]['category'] = category
                                        # Update widget state directly
                                        st.session_state[f"bt_{idx}"] = basic_type
                                        # This is the actual selectbox key for Basic Type column,
                                        # so update it as well to reflect GPT changes in the UI.
                                        st.session_state[f"bt_select_{idx}"] = basic_type
                                        st.session_state[f"cat_{idx}"] = category
                                        
                                        # Flag if this basic type is mapped to multiple categories
                                        if basic_type in st.session_state.multi_cat_bts:
                                            st.session_state.needs_category_review.add(idx)
                                            print(f"[REVIEW] '{sku_name}' has multi-category BT '{basic_type}' -> categories: {st.session_state.multi_cat_bts[basic_type]}")
                                        
                                        # Handle suggested new basic type
                                        if is_new_bt and suggested_bt:
                                            st.session_state.suggested_new_bts[idx] = {
                                                'suggested_bt': suggested_bt,
                                                'category': category,
                                                'sku_name': sku_name,
                                                'closest_existing_bt': basic_type
                                            }
                                            print(f"[OK] Set '{sku_name}' -> BT: {basic_type}, Category: {category} (Suggested NEW: {suggested_bt})")
                                        else:
                                            print(f"[OK] Set '{sku_name}' -> BT: {basic_type}, Category: {category}")
                                        break
                            
                            processed = batch_end
                            
                        except Exception as e:
                            print(f"[ERROR] Error processing batch {batch_start+1}-{batch_end}: {str(e)}")
                            st.error(f"Error processing batch {batch_start+1}-{batch_end}: {str(e)}")
                        
                        progress_bar.progress(processed / total_skus)
                    
                    progress_bar.empty()
                    
                    # Show usage summary for this operation
                    total_tokens = sum(s['total_tokens'] for s in batch_usage_stats)
                    total_cost = sum(s['total_cost'] for s in batch_usage_stats)
                    
                    # Show count of suggested new BTs
                    new_bt_count = len(st.session_state.suggested_new_bts)
                    if new_bt_count > 0:
                        st.success(f"✅ BT & Categories found for {processed} SKUs! | Tokens: {total_tokens:,} | Cost: ${total_cost:.4f}")
                        st.info(f"💡 {new_bt_count} SKUs have suggested new basic types. See suggestions below each SKU in the table.")
                    else:
                        st.success(f"✅ BT & Categories found for {processed} SKUs! | Tokens: {total_tokens:,} | Cost: ${total_cost:.4f}")
                    st.rerun()

    with col2:
        if st.button("🏷️ Find Generic Keywords", disabled=not all_files_loaded, use_container_width=True):
            if all_files_loaded:
                with st.spinner("Finding generic keywords..."):
                    progress_bar = st.progress(0)
                    batch_usage_stats = []
                    processed_count = 0
                    
                    for idx, item in enumerate(st.session_state.sku_data):
                        if item['basic_type']:
                            try:
                                print(f"\n>>> Processing SKU {idx+1}/{len(st.session_state.sku_data)}: {item['sku_name']}")
                                # Get generic keywords for this basic type (PRIMARY)
                                gk_list = st.session_state.mapping_bt_gk_df.loc[
                                    st.session_state.mapping_bt_gk_df.iloc[:, 0] == item['basic_type'],
                                    st.session_state.mapping_bt_gk_df.columns[1]
                                ].tolist()
                                
                                if gk_list and len(gk_list) > 0:
                                    # Flatten if nested list
                                    if isinstance(gk_list[0], list):
                                        gk_list = gk_list[0]
                                    
                                    # Get extended keywords from other basic types in the same category
                                    extended_keywords = []
                                    if item['category'] and st.session_state.mapping_cat_bt_df is not None:
                                        # Get all basic types for this category
                                        related_bt_list = st.session_state.mapping_cat_bt_df.loc[
                                            st.session_state.mapping_cat_bt_df.iloc[:, 1] == item['category'],
                                            st.session_state.mapping_cat_bt_df.columns[0]
                                        ].tolist()
                                        if related_bt_list and isinstance(related_bt_list[0], list):
                                            related_bt_list = related_bt_list[0]
                                        
                                        # Get keywords from related basic types (excluding current one)
                                        for related_bt in related_bt_list:
                                            if related_bt != item['basic_type']:
                                                related_gk = st.session_state.mapping_bt_gk_df.loc[
                                                    st.session_state.mapping_bt_gk_df.iloc[:, 0] == related_bt,
                                                    st.session_state.mapping_bt_gk_df.columns[1]
                                                ].tolist()
                                                if related_gk and len(related_gk) > 0:
                                                    if isinstance(related_gk[0], list):
                                                        extended_keywords.extend(related_gk[0])
                                                    else:
                                                        extended_keywords.extend(related_gk)
                                        # Remove duplicates and keywords already in primary list
                                        extended_keywords = list(set(extended_keywords) - set(gk_list))
                                    
                                    result, usage_stats = gpt_call_with_usage(
                                        open_api_key, api_version, azure_endpoint, deployment_name,
                                        generic_keyword_prompt(item['sku_name'], item['category'], item['basic_type'], gk_list)
                                    )
                                    
                                    # Track usage stats
                                    usage_stats['operation'] = 'Find Generic Keywords'
                                    usage_stats['batch'] = f"SKU: {item['sku_name'][:30]}..."
                                    batch_usage_stats.append(usage_stats)
                                    st.session_state.api_usage_stats.append(usage_stats)
                                    st.session_state.total_session_cost += usage_stats['total_cost']
                                    st.session_state.total_session_tokens += usage_stats['total_tokens']
                                    processed_count += 1
                                    
                                    # Log to Google Sheets
                                    log_gpt_cost_to_sheets(usage_stats, {
                                        'sku_count': 1,
                                        'notes': f'Processing keywords for SKU: {item["sku_name"][:50]}'
                                    })
                                    
                                    # Clean result to remove markdown code fences
                                    result_clean = result.strip()
                                    if result_clean.startswith('```'):
                                        lines = result_clean.split('\n')
                                        result_clean = '\n'.join(lines[1:-1]) if len(lines) > 2 else result_clean
                                    
                                    generic_keywords_response = json.loads(result_clean)['selected_generic_keywords']
                                    # Handle new format with confidence levels: extract just the keyword strings
                                    if generic_keywords_response and isinstance(generic_keywords_response, list):
                                        if isinstance(generic_keywords_response[0], dict):
                                            # New format: [{"keyword": "...", "confidence": "..."}]
                                            generic_keywords = [kw['keyword'] for kw in generic_keywords_response if 'keyword' in kw]
                                        else:
                                            # Old format: ["keyword1", "keyword2"]
                                            generic_keywords = generic_keywords_response
                                    else:
                                        generic_keywords = [generic_keywords_response] if generic_keywords_response else []
                                    
                                    st.session_state.sku_data[idx]['generic_keywords'] = generic_keywords
                                    # IMPORTANT: Update widget state directly for st_tags.
                                    # Like selectboxes, st_tags reads from st.session_state[key], not from the value param.
                                    st.session_state[f"tags_{idx}"] = generic_keywords
                                    print(f"[OK] Set generic keywords to: {generic_keywords}")
                            except Exception as e:
                                print(f"[ERROR] Error processing {item['sku_name']}: {str(e)}")
                                st.error(f"Error processing {item['sku_name']}: {str(e)}")
                        progress_bar.progress((idx + 1) / len(st.session_state.sku_data))
                    
                    progress_bar.empty()
                    
                    # Increment version to force st_tags widgets to re-render with new values
                    st.session_state.gk_version += 1
                    
                    # Show usage summary for this operation
                    total_tokens = sum(s['total_tokens'] for s in batch_usage_stats)
                    total_cost = sum(s['total_cost'] for s in batch_usage_stats)
                    st.success(f"✅ Generic keywords found for {processed_count} SKUs! | Tokens: {total_tokens:,} | Cost: ${total_cost:.4f}")
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
    /* Fix: Constrain st_tags iframe within the Generic Keywords column */
    div[data-testid="stColumn"]:nth-child(5) iframe {
        max-width: 100% !important;
        width: 100% !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # Fix: Inject CSS into st_tags iframes to constrain rti--container width,
    # and clear residual suggestion text on blur.
    components.html("""
    <script>
    (function() {
        function fixTagsIframes() {
            try {
                var parentDoc = window.parent.document;
                var iframes = parentDoc.querySelectorAll('iframe');
                for (var i = 0; i < iframes.length; i++) {
                    try {
                        var doc = iframes[i].contentDocument || iframes[i].contentWindow.document;
                        if (!doc) continue;
                        var container = doc.querySelector('.rti--container');
                        if (container && !doc.querySelector('#fix-tags-overflow')) {
                            var style = doc.createElement('style');
                            style.id = 'fix-tags-overflow';
                            style.textContent = [
                                '.rti--container {',
                                '  max-width: 100% !important;',
                                '  width: 100% !important;',
                                '  flex-wrap: wrap !important;',
                                '  overflow: hidden !important;',
                                '  box-sizing: border-box !important;',
                                '}',
                                '.rti--input {',
                                '  max-width: 100% !important;',
                                '  box-sizing: border-box !important;',
                                '  min-width: 80px !important;',
                                '  width: auto !important;',
                                '}',
                                '.rah-input-wrapper {',
                                '  max-width: 100% !important;',
                                '  overflow: hidden !important;',
                                '}'
                            ].join('\\n');
                            doc.head.appendChild(style);
                        }
                        // Also clear residual suggestion text in unfocused inputs
                        var input = doc.querySelector('.rti--input');
                        if (input && !input.matches(':focus') && input.value.trim() !== '') {
                            var nativeSetter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value'
                            ).set;
                            nativeSetter.call(input, '');
                            input.dispatchEvent(new Event('input', { bubbles: true }));
                            input.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    } catch(e) {}
                }
            } catch(e) {}
        }
        setInterval(fixTagsIframes, 500);
    })();
    </script>
    """, height=0)
    
    @st.fragment
    def _render_keywords_fragment(idx, gk_options):
        """Render keyword tags in an isolated fragment to avoid full-page reruns on rapid edits."""
        current_keywords = st.session_state.sku_data[idx]['generic_keywords']
        selected_keywords = st_tags(
            label='',
            text='Add keyword...',
            value=current_keywords,
            suggestions=gk_options if gk_options else [],
            key=f"tags_{idx}_v{st.session_state.gk_version}"
        )
        if selected_keywords != current_keywords:
            normalized = []
            duplicate_found = None
            seen_lower = set()
            for kw in selected_keywords:
                kw_cap = kw[:1].upper() + kw[1:] if kw else kw
                if kw_cap.lower() in seen_lower:
                    duplicate_found = kw_cap
                    continue
                seen_lower.add(kw_cap.lower())
                normalized.append(kw_cap)
            if duplicate_found:
                st.toast(f"⚠️ '{duplicate_found}' already exists in row {idx + 1}", icon="⚠️")
            st.session_state.sku_data[idx]['generic_keywords'] = normalized

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
    
    # Display each SKU as a row
    for idx, item in enumerate(st.session_state.sku_data):
        cols = st.columns([0.3, 3, 1.7, 1.7, 3.8])
        
        with cols[0]:
            st.markdown(f"**{idx + 1}**")
        
        with cols[1]:
            st.text_input("SKU", value=item['sku_name'], disabled=True, key=f"sku_{idx}", label_visibility="collapsed")
        
        with cols[2]:
            # STREAMLIT WIDGET STATE PATTERN:
            # Selectboxes with a 'key' store their value in st.session_state[key].
            # We do NOT use the 'index' parameter because it conflicts with session state
            # and causes a warning: "widget created with default value but also had value set via Session State API"
            # Instead, we:
            #   1. Initialize st.session_state[key] when SKU data is created
            #   2. Update st.session_state[key] when programmatically setting values (e.g., GPT results)
            #   3. Let the selectbox read its value from session state automatically via 'key'
            #   4. Sync the selected value back to sku_data for export
            
            # Ensure widget state is initialized
            if f"cat_{idx}" not in st.session_state:
                st.session_state[f"cat_{idx}"] = item['category']
            
            # Dynamically check if the current basic type is mapped to multiple categories
            current_bt_for_review = st.session_state.get(f"bt_select_{idx}", item.get('basic_type', ''))
            needs_review = current_bt_for_review in st.session_state.multi_cat_bts
            if needs_review:
                # Hidden marker div - CSS :has() selector will highlight the selectbox
                st.markdown(
                    '<div class="cat-needs-review" style="display:none;"></div>',
                    unsafe_allow_html=True
                )
            
            selected_category = st.selectbox(
                "Cat",
                options=category_options,
                key=f"cat_{idx}",
                label_visibility="collapsed"
            )
            
            if needs_review:
                possible_cats_str = ', '.join(st.session_state.multi_cat_bts.get(current_bt_for_review, []))
                st.markdown(
                    f'<small style="color: #ff4b4b;">⚠️ {current_bt_for_review} in: {possible_cats_str}</small>',
                    unsafe_allow_html=True
                )
            
            # Sync selectbox value back to sku_data
            if selected_category != item['category']:
                st.session_state.sku_data[idx]['category'] = selected_category
        
        with cols[3]:
            # Filter basic types based on selected category for suggestions
            if item['category'] and st.session_state.mapping_cat_bt_df is not None:
                # Category is in column 1 (Category Tag Type), Basic Types in column 0 (Basic Tag Type)
                filtered_bt = st.session_state.mapping_cat_bt_df.loc[
                    st.session_state.mapping_cat_bt_df.iloc[:, 1] == item['category'],
                    st.session_state.mapping_cat_bt_df.columns[0]
                ].tolist()
                if filtered_bt and len(filtered_bt) > 0:
                    if isinstance(filtered_bt[0], list):
                        filtered_bt = filtered_bt[0]
                    bt_suggestions = [''] + filtered_bt + ['➕ Type new...']
                else:
                    bt_suggestions = bt_options + ['➕ Type new...']
            else:
                bt_suggestions = bt_options + ['➕ Type new...']
            
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
                    
                    # Note: Logging to BT_Update_Log is deferred until CSV export to prevent UI freezing
                    
                    # Remove from suggestions
                    del st.session_state.suggested_new_bts[idx]
                
                st.session_state[accepted_suggestion_key] = False
            
            # Build options list - include current value if it's custom (not in standard list)
            current_bt = item['basic_type']
            dropdown_options = bt_suggestions.copy()
            if current_bt and current_bt not in dropdown_options and current_bt != '➕ Type new...':
                # Insert custom value before the "Type new..." option
                dropdown_options = dropdown_options[:-1] + [current_bt] + ['➕ Type new...']
            
            # Selectbox for selecting from existing basic types
            selectbox_key = f"bt_select_{idx}"

            # STREAMLIT WIDGET STATE PATTERN (same as Category):
            # Do NOT use the 'index' parameter together with Session State.
            # Instead, initialize st.session_state[selectbox_key] once, then let the
            # selectbox read and manage its value solely via this key.
            if selectbox_key not in st.session_state:
                # Use current_bt if available, otherwise default to empty option
                initial_value = current_bt if current_bt in dropdown_options else ''
                st.session_state[selectbox_key] = initial_value

            selected_bt = st.selectbox(
                "BT",
                options=dropdown_options,
                key=selectbox_key,
                label_visibility="collapsed"
            )
            
            # Check if user selected "Type new..."
            custom_bt_key = f"bt_custom_{idx}"
            if custom_bt_key not in st.session_state:
                st.session_state[custom_bt_key] = ""
            
            if selected_bt == '➕ Type new...':
                # Show text input for custom basic type
                custom_bt = st.text_input(
                    "New BT:",
                    value=st.session_state[custom_bt_key],
                    key=custom_bt_key,
                    label_visibility="collapsed",
                    placeholder="Type new basic type..."
                )
                if custom_bt and custom_bt.strip():
                    st.session_state.sku_data[idx]['basic_type'] = custom_bt.strip()
                    # Keep the Basic Type selectbox in sync with the custom value
                    st.session_state[f"bt_select_{idx}"] = custom_bt.strip()
                    # Track as new basic type
                    if custom_bt.strip() not in st.session_state.accepted_new_bts:
                        current_cat = item['category'] if item['category'] else 'Uncategorized'
                        st.session_state.accepted_new_bts[custom_bt.strip()] = {
                            'category': current_cat,
                            'generic_keywords': [],
                            'source_sku': item['sku_name']
                        }
            else:
                # Sync selection back to sku_data
                if selected_bt and selected_bt != item['basic_type']:
                    st.session_state.sku_data[idx]['basic_type'] = selected_bt
            
            # Show LLM suggested new basic type if available
            if idx in st.session_state.suggested_new_bts:
                suggestion = st.session_state.suggested_new_bts[idx]
                suggested_bt = suggestion['suggested_bt']
                
                # Show suggestion text and small "Use" button inline
                col_text, col_btn = st.columns([2, 1])
                with col_text:
                    st.markdown(f"<small style='color: #1f77b4;'>💡 <b>{suggested_bt}</b></small>", unsafe_allow_html=True)
                with col_btn:
                    def accept_suggestion(idx=idx):
                        st.session_state[f"accept_new_bt_{idx}"] = True
                    st.button("✓", key=f"accept_bt_{idx}", on_click=accept_suggestion, help="Use this suggestion")
        
        with cols[4]:
            # Render keywords in a fragment to prevent full-page reruns on rapid edits
            # This avoids WebSocket "Cached ForwardMsg MISS" errors when quickly deleting keywords
            _render_keywords_fragment(idx, gk_options)
        
        st.markdown("<div style='margin: 5px 0;'></div>", unsafe_allow_html=True)
    
    # Export results
    st.header("💾 Export Results")
    
    # Detect all new basic types (both manually entered and from suggestions)
    def detect_new_basic_types():
        """
        Detect basic types that are not in the original BT list
        
        Returns:
            dict: Dictionary with bt_name as key and info dict as value
        """
        all_existing_bts = set()
        if st.session_state.bt_df is not None:
            all_existing_bts = set(st.session_state.bt_df.iloc[:, 0].tolist())
        
        new_bts = {}
        
        for item in st.session_state.sku_data:
            basic_type = item.get('basic_type', '')
            category = item.get('category', '')
            
            if not basic_type:
                continue
            
            # Check if this BT is not in the existing list
            if basic_type not in all_existing_bts:
                if basic_type not in new_bts:
                    new_bts[basic_type] = {
                        'category': category if category else 'Uncategorized',
                        'generic_keywords': set(),
                        'source_sku': item['sku_name']
                    }
                # Collect generic keywords for this new BT
                if item.get('generic_keywords'):
                    new_bts[basic_type]['generic_keywords'].update(item['generic_keywords'])
        
        # Convert sets to lists
        for bt in new_bts:
            new_bts[bt]['generic_keywords'] = list(new_bts[bt]['generic_keywords'])
        
        return new_bts
    
    # Detect manually added generic keywords
    def detect_new_gk_mappings():
        """
        Detect generic keywords that were manually added and not in the original BT_GK mapping
        
        Returns:
            dict: Dictionary with basic_type as key and list of new keywords as value
        """
        new_mappings = {}
        
        for item in st.session_state.sku_data:
            basic_type = item.get('basic_type', '')
            current_keywords = item.get('generic_keywords', [])
            
            if not basic_type or not current_keywords:
                continue
            
            # Get existing keywords for this basic type
            existing_keywords = get_existing_gk_for_basic_type(basic_type)
            
            # Find keywords that are not in the existing mapping
            new_keywords = [kw for kw in current_keywords if kw not in existing_keywords]
            
            if new_keywords:
                if basic_type not in new_mappings:
                    new_mappings[basic_type] = set()
                new_mappings[basic_type].update(new_keywords)
        
        # Convert sets to lists for JSON serialization
        return {bt: list(keywords) for bt, keywords in new_mappings.items()}
    
    # Show detected new mappings before export
    new_gk_mappings = detect_new_gk_mappings()
    
    # Detect all new basic types (manually typed or from AI suggestions)
    new_basic_types = detect_new_basic_types()
    
    if new_gk_mappings:
        with st.expander("🆕 New Generic Keywords Detected", expanded=True):
            st.info("The following generic keywords were manually added and will be synced to Google Sheets BT_GK_mappings when you export:")
            for bt, keywords in new_gk_mappings.items():
                st.markdown(f"**{bt}:** {', '.join(keywords)}")
    
    # Show all new basic types that will be added
    if new_basic_types:
        with st.expander("🆕 New Basic Types to Add", expanded=True):
            st.info("The following new basic types will be added to Google Sheets BT_CT_mappings and BT_GK_mappings when you export:")
            for bt_name, bt_info in new_basic_types.items():
                st.markdown(f"**{bt_name}** → Category: *{bt_info['category']}*")
                if bt_info['generic_keywords']:
                    st.markdown(f"  - Generic Keywords: {', '.join(bt_info['generic_keywords'])}")
    
    if st.button("📥 Download Tagged SKUs as CSV", use_container_width=True):
        # First, add new basic types to BT_CT_mappings and BT_GK_mappings
        if new_basic_types:
            with st.spinner("Adding new basic types to Google Sheets..."):
                for bt_name, bt_info in new_basic_types.items():
                    success = add_new_bt_to_mappings(
                        bt_name, 
                        bt_info['category'], 
                        bt_info.get('generic_keywords', [])
                    )
                    if success:
                        st.success(f"✅ Added new basic type '{bt_name}' to Google Sheets!")
                        # Log to BT_Update_Log (deferred from when BT was accepted/created)
                        log_new_bt_update(bt_name, bt_info['category'], bt_info.get('source_sku', 'Unknown'), 'added')
                    else:
                        st.warning(f"⚠️ Could not add new basic type '{bt_name}' to Google Sheets.")
                
                # Clear accepted new BTs after export (for any that were tracked from AI suggestions)
                st.session_state.accepted_new_bts = {}
        
        # Sync new GK mappings to Google Sheets (only for existing basic types, new BTs already have their GKs)
        # Filter out new basic types from gk_mappings since they're already handled above
        existing_bt_gk_mappings = {bt: kws for bt, kws in new_gk_mappings.items() if bt not in new_basic_types}
        if existing_bt_gk_mappings:
            with st.spinner("Syncing new generic keywords to Google Sheets..."):
                success = update_bt_gk_mappings(existing_bt_gk_mappings)
                if success:
                    st.success(f"✅ Synced {sum(len(v) for v in existing_bt_gk_mappings.values())} new generic keywords to Google Sheets!")
                else:
                    st.warning("⚠️ Could not sync new generic keywords to Google Sheets. Check the console for details.")
        
        result_df = pd.DataFrame([
            {
                'SKU Name': item['sku_name'],
                'Category': item['category'],
                'Basic Type': item['basic_type'],
                'Generic Keywords': ', '.join(item['generic_keywords'])
            }
            for item in st.session_state.sku_data
        ])
        
        csv = result_df.to_csv(index=False)
        st.download_button(
            label="⬇️ Download CSV",
            data=csv,
            file_name="tagged_skus.csv",
            mime="text/csv",
            use_container_width=True
        )