"""
Embedding utilities for SKU Tagging System
Handles embedding generation, caching, and similarity search for basic types.

Embeddings are stored as a pickle file containing:
{
    'basic_types': List[str],           # BT names in order
    'embeddings': np.ndarray,           # shape (n, dim) - embedding vectors
    'bt_to_category': Dict[str, str],   # BT -> Category mapping
    'generated_at': str,                # ISO timestamp
    'model': str,                       # embedding model/deployment name
    'bt_hash': str                      # hash of BT list for change detection
}
"""

import os
import pickle
import hashlib
import numpy as np
from datetime import datetime
from openai import AzureOpenAI

# Default cache file path (next to this file)
DEFAULT_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bt_embeddings_cache.pkl")

# Azure OpenAI Embedding Pricing (per 1K tokens)
EMBEDDING_PRICING = {
    'text-embedding-ada-002': 0.0001,
    'text-embedding-3-small': 0.00002,
    'text-embedding-3-large': 0.00013,
    'default': 0.0001  # fallback
}

# Max batch size for embedding API calls (Azure limit is typically 2048 inputs)
EMBEDDING_BATCH_SIZE = 200


def _compute_bt_hash(basic_types):
    """Compute a hash of the basic types list to detect changes."""
    bt_str = "|".join(sorted(basic_types))
    return hashlib.md5(bt_str.encode()).hexdigest()


def _get_embedding_price(model_name):
    """Get per-1K-token price for the given embedding model."""
    for key, price in EMBEDDING_PRICING.items():
        if key in model_name.lower():
            return price
    return EMBEDDING_PRICING['default']


def calculate_embedding_cost(total_tokens, model_name='default'):
    """
    Calculate cost for an embedding API call.
    
    Returns:
        dict with 'total_tokens' and 'total_cost'
    """
    price_per_1k = _get_embedding_price(model_name)
    cost = (total_tokens / 1000) * price_per_1k
    return {
        'total_tokens': total_tokens,
        'total_cost': cost
    }


def get_embeddings_batch(client, texts, deployment_name):
    """
    Get embeddings for a list of texts using Azure OpenAI.
    
    Args:
        client: AzureOpenAI client instance
        texts: List of strings to embed
        deployment_name: Embedding model deployment name
    
    Returns:
        tuple: (embeddings_list, total_tokens_used)
    """
    all_embeddings = []
    total_tokens = 0

    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i:i + EMBEDDING_BATCH_SIZE]
        response = client.embeddings.create(
            model=deployment_name,
            input=batch
        )
        # Sort by index to maintain order
        sorted_data = sorted(response.data, key=lambda x: x.index)
        all_embeddings.extend([d.embedding for d in sorted_data])
        total_tokens += response.usage.total_tokens

    return all_embeddings, total_tokens


def load_cache(cache_path=None):
    """Load the cached embeddings from disk, or return None if not found."""
    path = cache_path or DEFAULT_CACHE_PATH
    if os.path.exists(path):
        try:
            with open(path, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            print(f"[WARN] Failed to load embedding cache: {e}")
    return None


def save_cache(cache_data, cache_path=None):
    """Save embeddings cache to disk."""
    path = cache_path or DEFAULT_CACHE_PATH
    with open(path, 'wb') as f:
        pickle.dump(cache_data, f)
    print(f"[OK] Embedding cache saved to {path} ({len(cache_data['basic_types'])} basic types)")


def build_bt_embeddings(
    api_key,
    api_version,
    azure_endpoint,
    embedding_deployment,
    basic_types,
    bt_to_category,
    cache_path=None,
    force_rebuild=False,
    progress_callback=None
):
    """
    Build (or load from cache) embeddings for all basic types.
    
    Args:
        api_key: Azure OpenAI API key
        api_version: API version
        azure_endpoint: Azure OpenAI endpoint
        embedding_deployment: Deployment name for the embedding model
        basic_types: List of basic type names
        bt_to_category: Dict mapping basic_type -> category
        cache_path: Optional custom cache file path
        force_rebuild: If True, regenerate even if cache exists
        progress_callback: Optional callable(current, total) for progress updates
    
    Returns:
        tuple: (cache_data_dict, usage_stats_list)
            - cache_data_dict: The full cache dictionary
            - usage_stats_list: List of usage stat dicts for each embedding API call
    """
    bt_hash = _compute_bt_hash(basic_types)
    usage_stats_list = []

    # Check cache
    if not force_rebuild:
        cache = load_cache(cache_path)
        if cache and cache.get('bt_hash') == bt_hash and cache.get('model') == embedding_deployment:
            print(f"[OK] Using cached embeddings ({len(cache['basic_types'])} basic types, generated {cache['generated_at']})")
            return cache, usage_stats_list  # No API calls needed

    print(f"[INFO] Building embeddings for {len(basic_types)} basic types using {embedding_deployment}...")

    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=azure_endpoint
    )

    # Compute embeddings in batches
    all_embeddings = []
    total_tokens = 0

    for i in range(0, len(basic_types), EMBEDDING_BATCH_SIZE):
        batch = basic_types[i:i + EMBEDDING_BATCH_SIZE]
        batch_embeddings, batch_tokens = get_embeddings_batch(client, batch, embedding_deployment)
        all_embeddings.extend(batch_embeddings)
        total_tokens += batch_tokens

        # Track per-batch usage
        cost = calculate_embedding_cost(batch_tokens, embedding_deployment)
        batch_stat = {
            'prompt_tokens': batch_tokens,
            'completion_tokens': 0,
            'total_tokens': batch_tokens,
            'input_cost': cost['total_cost'],
            'output_cost': 0.0,
            'total_cost': cost['total_cost'],
            'model': embedding_deployment,
            'operation': 'Embed Basic Types',
            'batch': f"BTs {i+1}-{min(i+EMBEDDING_BATCH_SIZE, len(basic_types))}"
        }
        usage_stats_list.append(batch_stat)

        if progress_callback:
            progress_callback(min(i + EMBEDDING_BATCH_SIZE, len(basic_types)), len(basic_types))

        print(f"  Embedded BTs {i+1}-{min(i+EMBEDDING_BATCH_SIZE, len(basic_types))}: {batch_tokens} tokens, ${cost['total_cost']:.6f}")

    embeddings_array = np.array(all_embeddings, dtype=np.float32)

    cache_data = {
        'basic_types': list(basic_types),
        'embeddings': embeddings_array,
        'bt_to_category': dict(bt_to_category),
        'generated_at': datetime.now().isoformat(),
        'model': embedding_deployment,
        'bt_hash': bt_hash
    }

    save_cache(cache_data, cache_path)
    print(f"[OK] Embeddings built: {embeddings_array.shape}, total tokens: {total_tokens}")
    return cache_data, usage_stats_list


def get_sku_embeddings(
    api_key,
    api_version,
    azure_endpoint,
    embedding_deployment,
    sku_names
):
    """
    Compute embeddings for a list of SKU names.
    
    Args:
        sku_names: List of SKU name strings
    
    Returns:
        tuple: (np.ndarray of shape (n, dim), usage_stats_list)
    """
    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=azure_endpoint
    )

    all_embeddings, total_tokens = get_embeddings_batch(client, sku_names, embedding_deployment)

    cost = calculate_embedding_cost(total_tokens, embedding_deployment)
    usage_stat = {
        'prompt_tokens': total_tokens,
        'completion_tokens': 0,
        'total_tokens': total_tokens,
        'input_cost': cost['total_cost'],
        'output_cost': 0.0,
        'total_cost': cost['total_cost'],
        'model': embedding_deployment,
        'operation': 'Embed SKU Names',
        'batch': f"{len(sku_names)} SKUs"
    }

    return np.array(all_embeddings, dtype=np.float32), [usage_stat]


def cosine_similarity_matrix(a, b):
    """
    Compute cosine similarity between two sets of vectors.
    
    Args:
        a: np.ndarray of shape (m, dim)
        b: np.ndarray of shape (n, dim)
    
    Returns:
        np.ndarray of shape (m, n) with similarity scores
    """
    # Normalize
    a_norm = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-10)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-10)
    return a_norm @ b_norm.T


def find_similar_basic_types(sku_embedding, bt_cache, top_k=30):
    """
    Find the top-K most similar basic types for a single SKU embedding.
    
    Args:
        sku_embedding: 1D numpy array (embedding vector for one SKU)
        bt_cache: The cache dict from build_bt_embeddings
        top_k: Number of top matches to return
    
    Returns:
        list of dicts: [{'basic_type': str, 'category': str, 'similarity': float}, ...]
    """
    bt_embeddings = bt_cache['embeddings']
    basic_types = bt_cache['basic_types']
    bt_to_category = bt_cache['bt_to_category']

    # Compute similarities
    sim = cosine_similarity_matrix(
        sku_embedding.reshape(1, -1),
        bt_embeddings
    )[0]  # shape (n_bts,)

    # Get top-K indices
    top_indices = np.argsort(sim)[::-1][:top_k]

    results = []
    for idx in top_indices:
        bt_name = basic_types[idx]
        results.append({
            'basic_type': bt_name,
            'category': bt_to_category.get(bt_name, ''),
            'similarity': float(sim[idx])
        })

    return results


def find_similar_basic_types_batch(sku_embeddings, bt_cache, top_k=30):
    """
    Find the top-K most similar basic types for a batch of SKU embeddings.
    
    Args:
        sku_embeddings: np.ndarray of shape (n_skus, dim)
        bt_cache: The cache dict from build_bt_embeddings
        top_k: Number of top matches per SKU
    
    Returns:
        list of lists: For each SKU, a list of dicts with basic_type, category, similarity
    """
    bt_embeddings = bt_cache['embeddings']
    basic_types = bt_cache['basic_types']
    bt_to_category = bt_cache['bt_to_category']

    # Compute full similarity matrix: (n_skus, n_bts)
    sim_matrix = cosine_similarity_matrix(sku_embeddings, bt_embeddings)

    all_results = []
    for i in range(sim_matrix.shape[0]):
        sim = sim_matrix[i]
        top_indices = np.argsort(sim)[::-1][:top_k]
        results = []
        for idx in top_indices:
            bt_name = basic_types[idx]
            results.append({
                'basic_type': bt_name,
                'category': bt_to_category.get(bt_name, ''),
                'similarity': float(sim[idx])
            })
        all_results.append(results)

    return all_results
