"""
Utility functions for SKU Tagging System
Contains GPT call functions and prompt generators
"""

from openai import AzureOpenAI

# Azure OpenAI Pricing (per 1K tokens) - Update these based on your deployment model
# Default prices are for GPT-4o (adjust based on your actual model)
PRICING = {
    'gpt-4o': {'input': 0.005, 'output': 0.015},
    'gpt-4o-mini': {'input': 0.00015, 'output': 0.0006},
    'gpt-4': {'input': 0.03, 'output': 0.06},
    'gpt-4-turbo': {'input': 0.01, 'output': 0.03},
    'gpt-35-turbo': {'input': 0.0005, 'output': 0.0015},
    # Google Gemini pricing (per 1K tokens) - as of 2024
    'gemini-2.0-flash': {'input': 0.0001, 'output': 0.0004},
    'gemini-1.5-flash': {'input': 0.000075, 'output': 0.0003},
    'gemini-1.5-pro': {'input': 0.00125, 'output': 0.005},
    'gemini-2.0-flash-lite': {'input': 0.000075, 'output': 0.0003},
    'gemini-3.5-flash': {'input': 0.00015, 'output': 0.0006},  # Estimate based on flash tier
    'gemini-3.1-flash-lite': {'input': 0.000075, 'output': 0.0003},  # Lite tier pricing
    'default': {'input': 0.005, 'output': 0.015}  # Default fallback pricing
}


def calculate_cost(prompt_tokens, completion_tokens, model_name='default'):
    """
    Calculate the cost of an API call based on token usage
    
    Args:
        prompt_tokens: Number of input/prompt tokens
        completion_tokens: Number of output/completion tokens
        model_name: Name of the model (to determine pricing)
    
    Returns:
        dict: Cost breakdown with input_cost, output_cost, and total_cost
    """
    # Find matching pricing tier
    pricing = PRICING.get('default')
    for key in PRICING:
        if key in model_name.lower():
            pricing = PRICING[key]
            break
    
    input_cost = (prompt_tokens / 1000) * pricing['input']
    output_cost = (completion_tokens / 1000) * pricing['output']
    total_cost = input_cost + output_cost
    
    return {
        'input_cost': input_cost,
        'output_cost': output_cost,
        'total_cost': total_cost
    }


def gpt_call(open_api_key, api_version, azure_endpoint, deployment_name, prompt):
    """
    Make a call to Azure OpenAI GPT model
    
    Args:
        open_api_key: Azure OpenAI API key
        api_version: API version
        azure_endpoint: Azure endpoint URL
        deployment_name: Deployment name
        prompt: The prompt to send to the model
    
    Returns:
        str: The model's response content
    """
    response, _ = gpt_call_with_usage(open_api_key, api_version, azure_endpoint, deployment_name, prompt)
    return response


def gpt_call_with_usage(open_api_key, api_version, azure_endpoint, deployment_name, prompt):
    """
    Make a call to Azure OpenAI GPT model and return usage statistics
    
    Args:
        open_api_key: Azure OpenAI API key
        api_version: API version
        azure_endpoint: Azure endpoint URL
        deployment_name: Deployment name
        prompt: The prompt to send to the model
    
    Returns:
        tuple: (response_content, usage_stats)
            - response_content (str): The model's response content
            - usage_stats (dict): Token counts and cost information
    """
    print("\n" + "="*80)
    print("GPT CALL REQUEST")
    print("="*80)
    print(f"Prompt (first 500 chars):\n{prompt[:500]}...")
    print("="*80)
    
    client = AzureOpenAI(
        api_key=open_api_key,
        api_version=api_version,
        azure_endpoint=azure_endpoint
    )
    
    chat_completion = client.chat.completions.create(
        model=deployment_name,
        messages=[
            {
                "role": "system",
                "content": prompt
            }
        ]
    )
    
    response = chat_completion.choices[0].message.content
    
    # Extract token usage
    usage = chat_completion.usage
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    total_tokens = usage.total_tokens if usage else 0
    
    # Calculate cost
    cost = calculate_cost(prompt_tokens, completion_tokens, deployment_name)
    
    usage_stats = {
        'prompt_tokens': prompt_tokens,
        'completion_tokens': completion_tokens,
        'total_tokens': total_tokens,
        'input_cost': cost['input_cost'],
        'output_cost': cost['output_cost'],
        'total_cost': cost['total_cost'],
        'model': deployment_name
    }
    
    print("\n" + "="*80)
    print("GPT CALL RESPONSE")
    print("="*80)
    print(f"Response: {response}")
    print(f"\n--- Token Usage ---")
    print(f"Prompt tokens: {prompt_tokens}")
    print(f"Completion tokens: {completion_tokens}")
    print(f"Total tokens: {total_tokens}")
    print(f"\n--- Cost (USD) ---")
    print(f"Input cost: ${cost['input_cost']:.6f}")
    print(f"Output cost: ${cost['output_cost']:.6f}")
    print(f"Total cost: ${cost['total_cost']:.6f}")
    print("="*80 + "\n")

    return response, usage_stats


# ============================================================================
# Google Gemini API Functions
# ============================================================================

def gemini_call(api_key, prompt, model_name='gemini-2.0-flash'):
    """
    Make a call to Google Gemini model
    
    Args:
        api_key: Google Gemini API key
        prompt: The prompt to send to the model
        model_name: Gemini model name (default: gemini-2.0-flash)
    
    Returns:
        str: The model's response content
    """
    response, _ = gemini_call_with_usage(api_key, prompt, model_name)
    return response


def gemini_call_with_usage(api_key, prompt, model_name='gemini-2.0-flash'):
    """
    Make a call to Google Gemini model and return usage statistics
    
    Args:
        api_key: Google Gemini API key
        prompt: The prompt to send to the model
        model_name: Gemini model name (default: gemini-2.0-flash)
    
    Returns:
        tuple: (response_content, usage_stats)
            - response_content (str): The model's response content
            - usage_stats (dict): Token counts and cost information
    """
    import google.genai as genai
    
    print("\n" + "="*80)
    print("GEMINI CALL REQUEST")
    print("="*80)
    print(f"Model: {model_name}")
    print(f"Prompt (first 500 chars):\n{prompt[:500]}...")
    print("="*80)
    
    client = genai.Client(api_key=api_key)
    
    response = client.models.generate_content(
        model=model_name,
        contents=prompt
    )
    
    response_text = response.text
    
    # Extract token usage from response metadata
    usage_metadata = getattr(response, 'usage_metadata', None)
    if usage_metadata:
        prompt_tokens = getattr(usage_metadata, 'prompt_token_count', 0) or 0
        completion_tokens = getattr(usage_metadata, 'candidates_token_count', 0) or 0
        total_tokens = getattr(usage_metadata, 'total_token_count', 0) or (prompt_tokens + completion_tokens)
    else:
        # Fallback: estimate tokens if metadata not available
        prompt_tokens = len(prompt) // 4  # rough estimate
        completion_tokens = len(response_text) // 4
        total_tokens = prompt_tokens + completion_tokens
    
    # Calculate cost
    cost = calculate_cost(prompt_tokens, completion_tokens, model_name)
    
    usage_stats = {
        'prompt_tokens': prompt_tokens,
        'completion_tokens': completion_tokens,
        'total_tokens': total_tokens,
        'input_cost': cost['input_cost'],
        'output_cost': cost['output_cost'],
        'total_cost': cost['total_cost'],
        'model': model_name
    }
    
    print("\n" + "="*80)
    print("GEMINI CALL RESPONSE")
    print("="*80)
    print(f"Response: {response_text}")
    print(f"\n--- Token Usage ---")
    print(f"Prompt tokens: {prompt_tokens}")
    print(f"Completion tokens: {completion_tokens}")
    print(f"Total tokens: {total_tokens}")
    print(f"\n--- Cost (USD) ---")
    print(f"Input cost: ${cost['input_cost']:.6f}")
    print(f"Output cost: ${cost['output_cost']:.6f}")
    print(f"Total cost: ${cost['total_cost']:.6f}")
    print("="*80 + "\n")

    return response_text, usage_stats


def category_prompt_old(sku_name, category_list):
    """
    Generate prompt for category selection from SKU name
    
    Args:
        sku_name: Name of the SKU
        category_list: List of available categories
    
    Returns:
        str: Formatted prompt for GPT
    """
    return f"""
            You are an expert in food product classification for a large e-commerce food delivery platform.

            Your task is to analyze the given food SKU name and select the most appropriate category 
            from the provided keyword list.
            
            ### INSTRUCTIONS
            1. Carefully read the SKU name and understand the food type, brand, and product form.
            2. Compare it to the categories in the keyword list.
            3. Select only the category that best describe the SKU.
            4. If multiple categories seem related, select the most specific and accurate one.
            5. If none match perfectly, choose the closest logical category.
            6. Do not create new keywords; only select from the given list.
            7. IMPORTANT: Respond **only** with valid JSON — no Markdown, no code fences, no explanations.
            
            ### INPUTS
            **SKU Name:** {sku_name}
            
            **Keyword List:** {category_list}
            
            ### OUTPUT FORMAT
            Respond exactly like this (without code fences or additional text):
            {{"selected_keywords": "best_matching_category_1"}}

            """


def batch_category_prompt(sku_list, category_list):
    """
    Generate prompt for batch category selection from multiple SKU names
    
    Args:
        sku_list: List of SKU names
        category_list: List of available categories
    
    Returns:
        str: Formatted prompt for GPT
    """
    sku_items = "\n".join([f"{i+1}. {sku}" for i, sku in enumerate(sku_list)])
    
    return f"""
            You are an expert in food product classification for a large e-commerce food delivery platform.

            Your task is to analyze the given list of food SKU names and select the most appropriate category 
            for EACH SKU from the provided category list.
            
            ### INSTRUCTIONS
            1. Process each SKU independently.
            2. For each SKU, carefully read the name and understand the food type, brand, and product form.
            3. Compare it to the categories in the category list.
            4. Select only ONE category that best describes each SKU.
            5. If multiple categories seem related, select the most specific and accurate one.
            6. If none match perfectly, choose the closest logical category.
            7. Do not create new categories; only select from the given list.
            8. IMPORTANT: Respond **only** with valid JSON — no Markdown, no code fences, no explanations.
            
            ### INPUTS
            **SKU Names:**
            {sku_items}
            
            **Category List:** {category_list}
            
            ### OUTPUT FORMAT
            Respond exactly like this (without code fences or additional text):
            {{
                "results": [
                    {{"sku": "SKU_name_1", "category": "selected_category_1"}},
                    {{"sku": "SKU_name_2", "category": "selected_category_2"}},
                    ...
                ]
            }}

            """


def basictype_prompt_old(sku_name, category_name, basic_type_list):
    """
    Generate prompt for basic type selection from SKU name and category
    
    Args:
        sku_name: Name of the SKU
        category_name: Selected category
        basic_type_list: List of available basic types for this category
    
    Returns:
        str: Formatted prompt for GPT
    """
    return f"""
            You are an expert in food product classification for a large e-commerce food delivery platform.

            Your task is to analyze the given food SKU name and its category, then select the most appropriate basic type 
            from the provided basic type list.
            
            ### INSTRUCTIONS
            1. Carefully read the SKU name to understand the product's food type, brand, ingredients, and form.
            2. Use the given category to narrow the context and improve accuracy.
            3. Compare the SKU with each option in the basic type list.
            4. Select only the basic type that best describe the product's actual food type.
            5. If multiple options seem similar, choose the most specific and accurate one.
            6. If none match perfectly, select the closest logical basic type.
            7. Do not invent new basic types; only select from the given list.
            8. IMPORTANT: Respond **only** with valid JSON — no Markdown, no code fences, and no extra text.
            
            ### INPUTS
            **SKU Name:** {sku_name}  
            **Category:** {category_name}  
            **Basic Type List:** {basic_type_list}
            
            ### OUTPUT FORMAT
            Respond exactly like this (without code fences or additional text):
            {{"selected_basic_type": "best_matching_basic_type_1"}}

            """


def batch_basictype_prompt(sku_category_list, basic_type_list):
    """
    Generate prompt for batch basic type selection from multiple SKU names with same category
    
    Args:
        sku_category_list: List of tuples (sku_name, category)
        basic_type_list: List of available basic types for this category
    
    Returns:
        str: Formatted prompt for GPT
    """
    sku_items = "\n".join([f"{i+1}. {sku} (Category: {cat})" for i, (sku, cat) in enumerate(sku_category_list)])
    
    return f"""
            You are an expert in food product classification for a large e-commerce food delivery platform.

            Your task is to analyze the given list of food SKU names with their categories, and select the most appropriate basic type 
            for EACH SKU from the provided basic type list.
            
            ### INSTRUCTIONS
            1. Process each SKU independently.
            2. For each SKU, carefully read the name to understand the product's food type, brand, ingredients, and form.
            3. Use the given category to narrow the context and improve accuracy.
            4. Compare each SKU with the options in the basic type list.
            5. Select only ONE basic type that best describes each product's actual food type.
            6. If multiple options seem similar, choose the most specific and accurate one.
            7. If none match perfectly, select the closest logical basic type.
            8. Do not invent new basic types; only select from the given list.
            9. IMPORTANT: Respond **only** with valid JSON — no Markdown, no code fences, and no extra text.
            
            ### INPUTS
            **SKU Names with Categories:**
            {sku_items}
            
            **Basic Type List:** {basic_type_list}
            
            ### OUTPUT FORMAT
            Respond exactly like this (without code fences or additional text):
            {{
                "results": [
                    {{"sku": "SKU_name_1", "basic_type": "selected_basic_type_1"}},
                    {{"sku": "SKU_name_2", "basic_type": "selected_basic_type_2"}},
                    ...
                ]
            }}

            """


def batch_basictype_category_prompt(sku_list, basic_type_list, bt_to_category_mapping):
    """
    Generate prompt for batch basic type selection from multiple SKU names.
    This approach finds the Basic Type first from ALL available basic types,
    then the category is determined from the BT-to-Category mapping.
    Optimized to reduce token usage by grouping basic types by category.
    Also allows suggesting new basic types if none match well.
    
    Args:
        sku_list: List of SKU names
        basic_type_list: List of ALL available basic types
        bt_to_category_mapping: Dictionary mapping basic_type -> category
    
    Returns:
        str: Formatted prompt for GPT
    """
    sku_items = "\n".join([f"{i+1}. {sku}" for i, sku in enumerate(sku_list)])
    
    # Group basic types by category to reduce token usage
    # Instead of sending: {"Apple": "Fruits", "Banana": "Fruits", "Milk": "Dairy"}
    # We send: {"Fruits": ["Apple", "Banana"], "Dairy": ["Milk"]}
    category_to_bt = {}
    for bt, cat in bt_to_category_mapping.items():
        if cat not in category_to_bt:
            category_to_bt[cat] = []
        category_to_bt[cat].append(bt)
    
    # Format the category-grouped basic types for the prompt
    bt_by_category_str = "\n".join([f"- {cat}: {bts}" for cat, bts in category_to_bt.items()])
    
    return f"""
            You are an expert in food product classification for a large e-commerce food delivery platform.

            Your task is to analyze the given list of food SKU names and select the most appropriate basic type 
            for EACH SKU from the provided basic type list, organized by category.
            
            ### INSTRUCTIONS
            1. Process each SKU independently.
            2. For each SKU, carefully read the name to understand the product's food type, brand, ingredients, and form.
            3. Basic types are grouped by category below. A basic type can appear in multiple categories (e.g., "Cereal" can be in both "Baby Care" for baby cereals and "Groceries" for regular cereals).
            4. Select the most appropriate basic type AND its corresponding category based on the SKU context.
            5. If multiple options seem similar, choose the most specific and accurate one.
            6. **If NO existing basic type matches the product well**, suggest a new basic type name.
               - Set "is_new_bt" to true and provide a "suggested_bt" value.
               - The suggested basic type should follow naming conventions (Title Case, descriptive, concise).
               - Still select the most appropriate category from the available categories for the suggested basic type.
               - IMPORTANT: "basic_type" MUST still be set to the closest/best-fitting EXISTING basic type from the list (never the suggested new one). This serves as a fallback.
            7. If an existing basic type matches well, set "is_new_bt" to false and "suggested_bt" to null.
            8. IMPORTANT: Respond **only** with valid JSON — no Markdown, no code fences, and no extra text.
            
            ### INPUTS
            **SKU Names:**
            {sku_items}
            
            **Basic Types by Category:**
            {bt_by_category_str}
            
            ### OUTPUT FORMAT
            Respond exactly like this (without code fences or additional text):
            {{
                "results": [
                    {{"sku": "SKU_name_1", "basic_type": "selected_basic_type_1", "category": "category_1", "is_new_bt": false, "suggested_bt": null}},
                    {{"sku": "SKU_name_2", "basic_type": "closest_existing_bt", "category": "category_2", "is_new_bt": true, "suggested_bt": "Suggested New Type"}},
                    ...
                ]
            }}

            """


def generic_keyword_prompt_old(sku_name, category_name, basic_type, generic_keywords_list, extended_keywords_list):
    """
    Generate prompt for generic keywords selection from SKU name, category, and basic type
    
    Args:
        sku_name: Name of the SKU
        category_name: Selected category
        basic_type: Selected basic type
        generic_keywords_list: List of available generic keywords for this basic type
        extended_keywords_list: List of generic keywords from related basic types
    
    Returns:
        str: Formatted prompt for GPT
    """
    return f"""
            You are an expert in food product keyword classification for a large e-commerce food delivery platform.

            Your task is to analyze the given food SKU name together with its category and basic type, 
            and then select all relevant generic keywords from the provided lists with confidence levels.
            
            ### INSTRUCTIONS
            1. Read the SKU name carefully to understand the product's food type, brand, ingredients, and product form.
            2. Use the category and basic type to understand the context.
            3. From the PRIMARY keyword list (direct mappings), select **all keywords that accurately describe the product**.
               - Keywords from the primary list should be marked with **HIGH confidence**.
            4. From the EXTENDED keyword list (related mappings), select **relevant keywords that apply**.
               - Keywords from the extended list should be marked with **MEDIUM or LOW confidence** based on relevance.
            5. The number of selected keywords can vary depending on the SKU. Choose **as many keywords as are relevant**.
            6. Do not invent new keywords or alter the provided ones.
            7. Prioritize accuracy and relevance; exclude unrelated or generic words.
            8. IMPORTANT: Respond **only** with valid JSON — no Markdown, no code fences, and no extra explanations.
            
            ### INPUTS
            **SKU Name:** {sku_name}  
            **Category:** {category_name}  
            **Basic Type:** {basic_type}  
            **PRIMARY Generic Keyword List (HIGH confidence):** {generic_keywords_list}
            **EXTENDED Generic Keyword List (MED/LOW confidence):** {extended_keywords_list}
            
            ### OUTPUT FORMAT
            Respond exactly like this (without code fences or extra text):
            {{
                "selected_generic_keywords": [
                    {{"keyword": "keyword_1", "confidence": "high"}},
                    {{"keyword": "keyword_2", "confidence": "high"}},
                    {{"keyword": "keyword_3", "confidence": "medium"}},
                    {{"keyword": "keyword_4", "confidence": "low"}},
                    ...
                ]
            }}

            """

# Nimendra's promps are below

def generic_keyword_prompt(sku_name, category_name, basic_type, generic_keywords_list):
    return f"""
            You are an expert in food product keyword classification for a large e-commerce food delivery platform.

            Your task is to analyze the given food SKU name together with its category and basic type,
            and then select all relevant generic keywords from the provided generic keyword list.

            ### INSTRUCTIONS
            1. Read the SKU name carefully to understand the product’s food type, brand, ingredients, and product form.
            2. Use the category and basic type(s) to understand the context.
            3. From the generic keyword list, select **all keywords that accurately describe the product** —
               including its type, variety, style, origin, and key descriptive traits.
            4. The number of selected keywords can vary depending on the SKU.
               Choose **as many keywords as are relevant**, not just one or two.
            5. Do not invent new keywords or alter the provided ones.
            6. Prioritize accuracy and relevance; exclude unrelated or generic words.
            7. IMPORTANT: Respond **only** with valid JSON — no Markdown, no code fences, and no extra explanations.

            ### INPUTS
            **SKU Name:** {sku_name}
            **Category:** {category_name}
            **Basic Type:** {basic_type}
            **Generic Keyword List:** {generic_keywords_list}

            ### OUTPUT FORMAT
            Respond exactly like this (without code fences or extra text):
            {{"selected_generic_keywords": ["keyword_1", "keyword_2", "keyword_3", ...]}}

            """


def batch_generic_keyword_prompt(sku_names, category_name, basic_type, generic_keywords_list):
    """Prompt for selecting generic keywords for multiple SKUs sharing the same basic type."""
    sku_list_str = "\n".join(f"  {i+1}. {name}" for i, name in enumerate(sku_names))
    return f"""
            You are an expert in food product keyword classification for a large e-commerce food delivery platform.

            Your task is to analyze each of the given food SKU names together with their shared category and basic type,
            and then select all relevant generic keywords from the provided generic keyword list FOR EACH SKU.

            ### INSTRUCTIONS
            1. All SKUs below share the same category and basic type.
            2. For EACH SKU, read the name carefully and select **all keywords that accurately describe that product**.
            3. The number of selected keywords can vary per SKU. Choose **as many as are relevant**.
            4. Do not invent new keywords or alter the provided ones.
            5. Prioritize accuracy and relevance; exclude unrelated or generic words.
            6. IMPORTANT: Respond **only** with valid JSON — no Markdown, no code fences, and no extra explanations.

            ### INPUTS
            **Category:** {category_name}
            **Basic Type:** {basic_type}
            **Generic Keyword List:** {generic_keywords_list}

            **SKU Names:**
{sku_list_str}

            ### OUTPUT FORMAT
            Respond with a JSON object mapping each SKU name (exactly as given) to its selected keywords:
            {{
              "results": [
                {{"sku_name": "exact SKU name 1", "selected_generic_keywords": ["kw1", "kw2", ...]}},
                {{"sku_name": "exact SKU name 2", "selected_generic_keywords": ["kw1", "kw3", ...]}}
              ]
            }}

            """


def basictype_prompt(sku_name, category_name, basic_type_list):
    return f"""
            You are an expert in food product classification for a large e-commerce food delivery platform.

            Your task is to analyze the given food SKU name and its category, then select the most appropriate basic type
            from the provided basic type list.

            ### INSTRUCTIONS
            1. Carefully read the SKU name to understand the product’s food type, brand, ingredients, and form.
            2. Use the given category to narrow the context and improve accuracy.
            3. Compare the SKU with each option in the basic type list.
            4. Select only the basic type that best describe the product’s actual food type.
            5. If multiple options seem similar, choose the most specific and accurate one.
            6. If none match perfectly, select the closest logical basic type.
            7. Do not invent new basic types; only select from the given list.
            8. IMPORTANT: Respond **only** with valid JSON — no Markdown, no code fences, and no extra text.

            ### INPUTS
            **SKU Name:** {sku_name}
            **Category:** {category_name}
            **Basic Type List:** {basic_type_list}

            ### OUTPUT FORMAT
            Respond exactly like this (without code fences or additional text):
            {{"selected_basic_type": "best_matching_basic_type_1"}}

            """


def category_prompt(sku_name, category_list):
    return f"""
            You are an expert in food product classification for a large e-commerce food delivery platform.

            Your task is to analyze the given food SKU name and select the most appropriate category
            from the provided keyword list.

            ### INSTRUCTIONS
            1. Carefully read the SKU name and understand the food type, brand, and product form.
            2. Compare it to the categories in the keyword list.
            3. Select only the category that best describe the SKU.
            4. If multiple categories seem related, select the most specific and accurate one.
            5. If none match perfectly, choose the closest logical category.
            6. Do not create new keywords; only select from the given list.
            7. IMPORTANT: Respond **only** with valid JSON — no Markdown, no code fences, no explanations.

            ### Special Considerations
            1. If particular bakery type SKU is with a particular brand name, then the category should be 'Groceries'. Not 'Bakery'.
            ### INPUTS
            **SKU Name:** {sku_name}

            **Keyword List:** {category_list}

            ### OUTPUT FORMAT
            Respond exactly like this (without code fences or additional text):
            {{"selected_keywords": "best_matching_category_1"}}

            """


def batch_embedding_bt_category_prompt(sku_candidates_list):
    """
    Generate prompt for batch basic type + category selection using embedding-filtered candidates.
    Each SKU has its own shortlist of candidate basic types (with categories and similarity scores)
    pre-filtered via embedding similarity.
    
    Args:
        sku_candidates_list: List of dicts, each containing:
            - 'sku_name': str
            - 'candidates': list of dicts with 'basic_type', 'category', 'similarity'
    
    Returns:
        str: Formatted prompt for GPT
    """
    sku_sections = []
    for i, item in enumerate(sku_candidates_list):
        candidate_lines = ", ".join(
            [f"{c['basic_type']} ({c['category']})" for c in item['candidates']]
        )
        sku_sections.append(f"{i+1}. **{item['sku_name']}**\n   Candidates: {candidate_lines}")

    sku_text = "\n".join(sku_sections)

    return f"""
            You are an expert in food product classification for a large e-commerce food delivery platform.

            Your task is to analyze each food SKU name and select the most appropriate basic type AND category
            from its pre-filtered candidate list. Each SKU has a shortlist of the most relevant basic types
            (with their categories) already identified via embedding similarity.

            ### INSTRUCTIONS
            1. Process each SKU independently.
            2. For each SKU, carefully read the name to understand the product's food type, brand, ingredients, and form.
            3. Each SKU has its own shortlist of candidate basic types with their categories. Select the BEST match.
            4. Select exactly ONE basic type and its corresponding category for each SKU.
            5. If multiple candidates seem similar, choose the most specific and accurate one.
            6. **If NO candidate basic type matches the product well**, you may suggest a new one:
               - Set "is_new_bt" to true and provide a "suggested_bt" value.
               - Still select the most appropriate category from the candidates.
            7. If a candidate matches well, set "is_new_bt" to false and "suggested_bt" to null.
            8. IMPORTANT: Respond **only** with valid JSON — no Markdown, no code fences, and no extra text.

            ### INPUTS
            {sku_text}

            ### OUTPUT FORMAT
            Respond exactly like this (without code fences or additional text):
            {{
                "results": [
                    {{"sku": "SKU_name_1", "basic_type": "selected_basic_type_1", "category": "category_1", "is_new_bt": false, "suggested_bt": null}},
                    {{"sku": "SKU_name_2", "basic_type": "closest_existing_bt", "category": "category_2", "is_new_bt": true, "suggested_bt": "Suggested New Type"}},
                    ...
                ]
            }}

            """