# 🏷️ SKU Tagging System

An interactive Streamlit application for automatically tagging SKUs with Categories, Basic Types, and Generic Keywords using Azure OpenAI GPT models.

## Features

- 📤 **CSV Upload**: Upload SKU lists via CSV file
- 🎯 **Automated Category Tagging**: AI-powered category selection
- 📋 **Basic Type Mapping**: Hierarchical filtering of basic types based on categories
- 🏷️ **Generic Keyword Tagging**: Multiple keyword assignment with pill-based UI
- ✏️ **Manual Editing**: Edit any field manually with dropdown selections
- 💾 **Export Results**: Download tagged data as CSV

## Prerequisites

- Python 3.8 or higher
- Azure OpenAI API access
- Required mapping files (see below)

## Environment Variables

Create a `.env` file in the `streamlit_app` directory with the following variables:

```env
# Azure OpenAI Configuration (Required)
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment-name
AZURE_OPENAI_API_VERSION=2024-02-01

# Google Sheets GPT Cost Logging (Optional)
GOOGLE_SHEETS_WEBAPP_URL=https://script.google.com/macros/s/your-script-id/exec
```

## GPT Token Cost Logging

The application can log all GPT API calls to a Google Sheet for cost tracking.

### Setup Instructions:

1. Open your Google Sheet: [Sheet Link](https://docs.google.com/spreadsheets/d/1-1DejLMWTf7YbUNKVa84fIiguL1XXb14wKJ-w28yOh4)
2. Go to **Extensions > Apps Script**
3. Delete any existing code and paste the contents of `google_apps_script.js`
4. Save the project (Ctrl+S)
5. Click **Deploy > New deployment**
6. Select type: **Web app**
7. Set "Execute as": **Me**
8. Set "Who has access": **Anyone**
9. Click **Deploy** and copy the Web App URL
10. Add the URL to your `.env` file as `GOOGLE_SHEETS_WEBAPP_URL`

### Logged Data:

Each GPT call logs:
- Timestamp
- Session ID
- Operation (Find Categories, Find Basic Types, Find Generic Keywords)
- Batch Info
- Model Name
- Token counts (prompt, completion, total)
- Costs (input, output, total in USD)
- SKU Count
- Notes

## Installation

1. Navigate to the streamlit_app directory:
```powershell
cd "c:\Code\AI Tagging\streamlit_app"
```

2. Install dependencies:
```powershell
pip install -r requirements.txt
```

## Required Files

Before running the application, prepare the following mapping files:

1. **Category-BasicType Mapping** (`CT - BT mappings.xlsx` or `.csv`)
   - Columns: `Categories`, `basictype`
   - Maps categories to their associated basic types

2. **BasicType-GenericKeywords Mapping** (`BT_GK mappings - by LLM.xlsx` or `.csv`)
   - Columns: `basictype`, `Generic keywords`
   - Maps basic types to their generic keywords

3. **Categories File** (`category_type.xlsx` or `.csv`)
   - Single column with all available categories

4. **Basic Types File** (`basic_type.xlsx` or `.csv`)
   - Single column with all available basic types

5. **Generic Keywords File** (`generic_keywords.xlsx` or `.csv`)
   - Single column with all available generic keywords

## Usage

### 1. Start the Application

```powershell
streamlit run app.py
```

The app will open in your default browser at `http://localhost:8501`

### 2. Configure Azure OpenAI (Sidebar)

Enter your Azure OpenAI credentials:
- API Key
- API Version (e.g., `2024-02-01`)
- Azure Endpoint URL
- Deployment Name

### 3. Load Mapping Files (Sidebar)

Upload all five mapping files using the file uploaders in the sidebar:
- Category-BasicType Mapping
- BasicType-GenericKeywords Mapping
- Categories File
- Basic Types File
- Generic Keywords File

### 4. Upload SKU File

- Click "Upload CSV file with SKU names"
- The CSV should have SKU names starting from line 2 (first data row)
- The app will automatically detect the column containing SKU names

### 5. Auto-Tag SKUs

Use the three action buttons:

**🎯 Find Categories**
- Analyzes each SKU name using GPT
- Selects the most appropriate category from your category list
- Shows progress bar during processing

**📋 Find Basic Types**
- Uses the category-to-basic-type mapping to filter relevant options
- Analyzes SKU name and category to select the best basic type
- Only processes SKUs with assigned categories

**🏷️ Find Generic Keywords**
- Uses the basic-type-to-generic-keywords mapping
- Selects multiple relevant keywords for each SKU
- Only processes SKUs with assigned basic types

### 6. Manual Editing

For each SKU, you can:
- **Category**: Select from dropdown (automatically filtered)
- **Basic Type**: Select from dropdown (filtered by selected category)
- **Generic Keywords**: 
  - View existing keywords as removable pills (❌ click to remove)
  - Add new keywords using the dropdown and ➕ Add button

### 7. Export Results

Click "📥 Download Tagged SKUs as CSV" to export your tagged data.

## File Structure

```
streamlit_app/
├── app.py              # Main Streamlit application
├── utils.py            # Helper functions (GPT calls and prompts)
├── requirements.txt    # Python dependencies
└── README.md          # This file
```

## SKU CSV Format

Your SKU CSV file should look like:

```csv
name
Product Name 1
Product Name 2
Product Name 3
```

Or with any column name containing SKU names:

```csv
sku_name,other_column
Product A,value1
Product B,value2
```

## Mapping File Formats

### Category-BasicType Mapping

```csv
Categories,basictype
Dairy,"['Milk', 'Cheese', 'Yogurt']"
Beverages,"['Juice', 'Soft Drink', 'Water']"
```

### BasicType-GenericKeywords Mapping

```csv
basictype,Generic keywords
Milk,"['Full Cream', 'Low Fat', 'Skim', 'Fresh']"
Cheese,"['Cheddar', 'Mozzarella', 'Parmesan', 'Grated']"
```

## Troubleshooting

**Issue**: "Please upload all mapping files"
- Solution: Ensure all 5 mapping files are uploaded in the sidebar

**Issue**: API errors during auto-tagging
- Solution: Check Azure OpenAI credentials and ensure API key is valid

**Issue**: Empty dropdown lists
- Solution: Verify mapping files contain data in the expected columns

**Issue**: Basic Type dropdown is empty
- Solution: First select a Category; Basic Types are filtered based on the selected Category

## Tips

- Process SKUs in batches if you have many (to manage API costs)
- Review and manually adjust AI suggestions for accuracy
- Save intermediate results frequently using the export feature
- Keep mapping files up-to-date for best results

## Support

For issues or questions, refer to the main project documentation or contact your team lead.
