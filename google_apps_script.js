/**
 * Google Apps Script for logging GPT Token Costs
 * 
 * SETUP INSTRUCTIONS:
 * 1. Open Google Sheets: https://docs.google.com/spreadsheets/d/1-1DejLMWTf7YbUNKVa84fIiguL1XXb14wKJ-w28yOh4
 * 2. Create a new tab named "GPT Token Costs"
 * 3. Go to Extensions > Apps Script
 * 4. Delete any existing code and paste this entire script
 * 5. Save the project (Ctrl+S)
 * 6. Click "Deploy" > "New deployment"
 * 7. Select type: "Web app"
 * 8. Set "Execute as": "Me"
 * 9. Set "Who has access": "Anyone" (or "Anyone with Google account" for more security)
 * 10. Click "Deploy" and copy the Web App URL
 * 11. Add the URL to your .env file as: GOOGLE_SHEETS_WEBAPP_URL=<your-web-app-url>
 * 
 * COLUMNS IN 'GPT Token Costs' TAB:
 * A: Timestamp
 * B: Session ID
 * C: Operation
 * D: Batch Info
 * E: Model
 * F: Prompt Tokens
 * G: Completion Tokens
 * H: Total Tokens
 * I: Input Cost (USD)
 * J: Output Cost (USD)
 * K: Total Cost (USD)
 * L: SKU Count
 * M: Notes
 */

// Configuration
const SPREADSHEET_ID = '1-1DejLMWTf7YbUNKVa84fIiguL1XXb14wKJ-w28yOh4';
const SHEET_NAME = 'GPT Token Costs';

// SKU Tagging Sheet (separate spreadsheet for SKU input/output)
const SKU_TAGGING_SPREADSHEET_ID = '18ahW-0qCZToVqjyuUN_6UQGuKkZmuJBP4-W5QgRcwdA';
const SKU_TAGGING_SHEET_NAME = 'Main';

/**
 * Initialize the sheet with headers if they don't exist
 */
function initializeSheet() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  let sheet = ss.getSheetByName(SHEET_NAME);
  
  // Create the sheet if it doesn't exist
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
  }
  
  // Check if headers exist
  const firstRow = sheet.getRange(1, 1, 1, 13).getValues()[0];
  if (firstRow[0] === '' || firstRow[0] !== 'Timestamp') {
    // Set headers
    const headers = [
      'Timestamp',
      'Session ID',
      'Operation',
      'Batch Info',
      'Model',
      'Prompt Tokens',
      'Completion Tokens',
      'Total Tokens',
      'Input Cost (USD)',
      'Output Cost (USD)',
      'Total Cost (USD)',
      'SKU Count',
      'Notes'
    ];
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    
    // Format headers
    sheet.getRange(1, 1, 1, headers.length)
      .setFontWeight('bold')
      .setBackground('#4285f4')
      .setFontColor('white');
    
    // Freeze header row
    sheet.setFrozenRows(1);
    
    // Set column widths for better readability
    sheet.setColumnWidth(1, 180);  // Timestamp
    sheet.setColumnWidth(2, 100);  // Session ID
    sheet.setColumnWidth(3, 150);  // Operation
    sheet.setColumnWidth(4, 180);  // Batch Info
    sheet.setColumnWidth(5, 120);  // Model
    sheet.setColumnWidth(6, 110);  // Prompt Tokens
    sheet.setColumnWidth(7, 130);  // Completion Tokens
    sheet.setColumnWidth(8, 100);  // Total Tokens
    sheet.setColumnWidth(9, 120);  // Input Cost
    sheet.setColumnWidth(10, 120); // Output Cost
    sheet.setColumnWidth(11, 120); // Total Cost
    sheet.setColumnWidth(12, 90);  // SKU Count
    sheet.setColumnWidth(13, 300); // Notes
    
    // Format cost columns as currency
    const lastRow = sheet.getLastRow();
    if (lastRow > 1) {
      sheet.getRange(2, 9, lastRow - 1, 3).setNumberFormat('$0.000000');
    }
  }
  
  return sheet;
}

/**
 * Handle POST requests from the Streamlit app
 */
function doPost(e) {
  try {
    // Parse the incoming JSON data
    const data = JSON.parse(e.postData.contents);
    
    // Check if this is a BT_GK mapping update request
    if (data.action === 'update_bt_gk_mappings') {
      return handleBtGkMappingUpdate(data);
    }
    
    // Check if this is a BT_CT mapping update request (new basic type)
    if (data.action === 'update_bt_ct_mappings') {
      return handleBtCtMappingUpdate(data);
    }
    
    // Check if this is a new basic type addition request
    if (data.action === 'add_new_basic_type') {
      return handleAddNewBasicType(data);
    }
    
    // Check if this is a BT Update log request
    if (data.action === 'log_bt_update') {
      return handleBtUpdateLog(data);
    }
    
    // Get pending (untagged) SKUs from SKU Names sheet
    if (data.action === 'get_pending_skus') {
      return handleGetPendingSkus(data);
    }
    
    // Update SKU tags back into SKU Names sheet
    if (data.action === 'update_sku_tags') {
      return handleUpdateSkuTags(data);
    }
    
    // Get SKUs from Main sheet (new external spreadsheet) with pagination
    if (data.action === 'get_main_skus') {
      return handleGetMainSKUs(data);
    }
    
    // Update SKU tags back into Main sheet (new external spreadsheet)
    if (data.action === 'update_main_sku_tags') {
      return handleUpdateMainSKUTags(data);
    }
    
    // Otherwise, handle as GPT cost logging
    // Initialize sheet and get it
    const sheet = initializeSheet();
    
    // Format timestamp for display
    let timestamp = data.timestamp;
    if (timestamp) {
      // Convert ISO timestamp to readable format
      const date = new Date(timestamp);
      timestamp = Utilities.formatDate(date, Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss');
    } else {
      timestamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss');
    }
    
    // Prepare row data
    const rowData = [
      timestamp,
      data.session_id || 'Unknown',
      data.operation || 'Unknown',
      data.batch_info || 'N/A',
      data.model || 'Unknown',
      data.prompt_tokens || 0,
      data.completion_tokens || 0,
      data.total_tokens || 0,
      data.input_cost || 0,
      data.output_cost || 0,
      data.total_cost || 0,
      data.sku_count || 0,
      data.notes || ''
    ];
    
    // Append the data to the sheet
    sheet.appendRow(rowData);
    
    // Get the last row number to format it
    const lastRow = sheet.getLastRow();
    
    // Format the cost cells in the new row
    sheet.getRange(lastRow, 9, 1, 3).setNumberFormat('$0.000000');
    
    // Format the token cells with thousand separators
    sheet.getRange(lastRow, 6, 1, 3).setNumberFormat('#,##0');
    
    // Return success response
    return ContentService
      .createTextOutput(JSON.stringify({ 
        success: true, 
        message: 'Data logged successfully',
        row: lastRow
      }))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    // Return error response
    return ContentService
      .createTextOutput(JSON.stringify({ 
        success: false, 
        error: error.toString() 
      }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Handle BT_GK mapping updates
 * Updates the BT_GK_mappings sheet by appending new generic keywords to existing basic types
 * 
 * @param {Object} data - The request data containing:
 *   - updates: Object with basic_type as key and array of new keywords as value
 *   - timestamp: ISO timestamp
 *   - session_id: Session identifier
 */
function handleBtGkMappingUpdate(data) {
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const btGkSheet = ss.getSheetByName('BT_GK_mappings');
    
    if (!btGkSheet) {
      return ContentService
        .createTextOutput(JSON.stringify({ 
          success: false, 
          error: 'BT_GK_mappings sheet not found' 
        }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    
    const updates = data.updates || {};
    const updatedBasicTypes = [];
    const errors = [];
    
    // Get all data from the sheet
    const lastRow = btGkSheet.getLastRow();
    const dataRange = btGkSheet.getRange(1, 1, lastRow, 2);
    const allData = dataRange.getValues();
    
    // Find header row (skip it)
    const startRow = allData[0][0] === 'Basic Tag Type' || allData[0][0] === 'BasicType' ? 1 : 0;
    
    // Process each basic type update
    for (const [basicType, newKeywords] of Object.entries(updates)) {
      if (!newKeywords || newKeywords.length === 0) continue;
      
      let found = false;
      
      // Search for the basic type in the sheet
      for (let i = startRow; i < allData.length; i++) {
        const rowBasicType = allData[i][0];
        
        if (rowBasicType === basicType) {
          found = true;
          
          // Get current generic keywords
          let currentGkValue = allData[i][1];
          let currentKeywords = [];
          
          // Parse the current keywords (stored as string representation of array)
          if (currentGkValue) {
            try {
              // Handle string representation of array like "['keyword1', 'keyword2']"
              if (typeof currentGkValue === 'string') {
                // Clean up the string - remove any leading/trailing whitespace
                let cleanValue = currentGkValue.trim();
                
                // Replace single quotes with double quotes for JSON parsing
                const jsonStr = cleanValue.replace(/'/g, '"');
                const parsed = JSON.parse(jsonStr);
                
                // Ensure we got an array
                if (Array.isArray(parsed)) {
                  currentKeywords = parsed;
                } else {
                  currentKeywords = [parsed];
                }
              } else if (Array.isArray(currentGkValue)) {
                currentKeywords = currentGkValue;
              }
            } catch (parseError) {
              // If parsing fails, log the error and try a different approach
              Logger.log('Parse error for basic type ' + basicType + ': ' + parseError.toString());
              Logger.log('Original value: ' + currentGkValue);
              
              // Try to extract keywords using regex as fallback
              if (typeof currentGkValue === 'string' && currentGkValue.includes('[')) {
                // Extract content between brackets and split by comma
                const match = currentGkValue.match(/\[(.*)\]/);
                if (match && match[1]) {
                  currentKeywords = match[1].split(',').map(k => k.trim().replace(/^['"]|['"]$/g, ''));
                } else {
                  currentKeywords = [];
                }
              } else {
                currentKeywords = [];
              }
            }
          }
          
          // Add new keywords (avoid duplicates) and track which ones were actually added
          const keywordSet = new Set(currentKeywords);
          const actuallyAddedKeywords = [];
          
          for (const newKw of newKeywords) {
            if (!keywordSet.has(newKw)) {
              keywordSet.add(newKw);
              actuallyAddedKeywords.push(newKw);
            }
          }
          
          if (actuallyAddedKeywords.length > 0) {
            // Convert back to array and format as string representation
            const updatedKeywords = Array.from(keywordSet);
            const updatedValue = JSON.stringify(updatedKeywords).replace(/"/g, "'");
            
            // Update the cell (row is i+1 because sheets are 1-indexed)
            btGkSheet.getRange(i + 1, 2).setValue(updatedValue);
            
            updatedBasicTypes.push({
              basicType: basicType,
              addedKeywords: actuallyAddedKeywords,  // Only the keywords that were actually added
              totalKeywords: updatedKeywords.length
            });
          }
          
          break;
        }
      }
      
      if (!found) {
        errors.push(`Basic type '${basicType}' not found in BT_GK_mappings`);
      }
    }
    
    // Log the update action
    logBtGkUpdate(data.session_id, updatedBasicTypes, errors);
    
    return ContentService
      .createTextOutput(JSON.stringify({ 
        success: true, 
        message: 'BT_GK mappings updated successfully',
        updated: updatedBasicTypes,
        errors: errors
      }))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    return ContentService
      .createTextOutput(JSON.stringify({ 
        success: false, 
        error: error.toString() 
      }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Log BT_GK update actions to a separate log (optional)
 */
function logBtGkUpdate(sessionId, updatedBasicTypes, errors) {
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    let logSheet = ss.getSheetByName('GK_Update_Log');
    
    // Create log sheet if it doesn't exist
    if (!logSheet) {
      logSheet = ss.insertSheet('GK_Update_Log');
      logSheet.getRange(1, 1, 1, 5).setValues([['Timestamp', 'Session ID', 'Basic Type', 'Added Keywords', 'Status']]);
      logSheet.getRange(1, 1, 1, 5)
        .setFontWeight('bold')
        .setBackground('#4285f4')
        .setFontColor('white');
      logSheet.setFrozenRows(1);
    }
    
    const timestamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss');
    
    // Log each update
    for (const update of updatedBasicTypes) {
      logSheet.appendRow([
        timestamp,
        sessionId || 'Unknown',
        update.basicType,
        update.addedKeywords.join(', '),
        'Success'
      ]);
    }
    
    // Log errors
    for (const error of errors) {
      logSheet.appendRow([
        timestamp,
        sessionId || 'Unknown',
        '-',
        '-',
        'Error: ' + error
      ]);
    }
    
  } catch (e) {
    // Silently fail logging - don't affect main operation
    Logger.log('Error logging BT_GK update: ' + e.toString());
  }
}

/**
 * Handle BT_CT mapping updates (add new basic types to category mappings)
 * @param {Object} data - The request data containing updates array
 */
function handleBtCtMappingUpdate(data) {
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const btCtSheet = ss.getSheetByName('BT_CT_mappings');
    
    if (!btCtSheet) {
      return ContentService
        .createTextOutput(JSON.stringify({ 
          success: false, 
          error: 'BT_CT_mappings sheet not found' 
        }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    
    const updates = data.updates || [];
    const addedRecords = [];
    
    for (const update of updates) {
      const basicType = update.basic_type;
      const category = update.category;
      
      if (basicType && category) {
        // Append new row to BT_CT_mappings
        btCtSheet.appendRow([basicType, category]);
        addedRecords.push({ basicType, category });
      }
    }
    
    return ContentService
      .createTextOutput(JSON.stringify({ 
        success: true, 
        message: 'BT_CT mappings updated successfully',
        added: addedRecords
      }))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    return ContentService
      .createTextOutput(JSON.stringify({ 
        success: false, 
        error: error.toString() 
      }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Handle adding a new basic type to both BT_CT_mappings and BT_GK_mappings
 * @param {Object} data - The request data containing basic_type, category, and generic_keywords
 */
function handleAddNewBasicType(data) {
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const btCtSheet = ss.getSheetByName('BT_CT_mappings');
    const btGkSheet = ss.getSheetByName('BT_GK_mappings');
    
    if (!btCtSheet || !btGkSheet) {
      return ContentService
        .createTextOutput(JSON.stringify({ 
          success: false, 
          error: 'BT_CT_mappings or BT_GK_mappings sheet not found' 
        }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    
    const basicType = data.basic_type;
    const category = data.category;
    const genericKeywords = data.generic_keywords || [];
    
    if (!basicType || !category) {
      return ContentService
        .createTextOutput(JSON.stringify({ 
          success: false, 
          error: 'basic_type and category are required' 
        }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    
    // Add to BT_CT_mappings
    btCtSheet.appendRow([basicType, category]);
    
    // Add to BT_GK_mappings with generic keywords
    const keywordsStr = genericKeywords.length > 0 
      ? JSON.stringify(genericKeywords).replace(/"/g, "'")
      : "[]";
    btGkSheet.appendRow([basicType, keywordsStr]);
    
    // Log to BT_Update_Log
    logBtUpdate(data.session_id, basicType, category, 'added', genericKeywords);
    
    return ContentService
      .createTextOutput(JSON.stringify({ 
        success: true, 
        message: 'New basic type added successfully',
        basicType: basicType,
        category: category,
        genericKeywords: genericKeywords
      }))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    return ContentService
      .createTextOutput(JSON.stringify({ 
        success: false, 
        error: error.toString() 
      }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Handle BT Update Log requests
 * @param {Object} data - The request data containing basic_type, category, sku_name, update_action
 */
function handleBtUpdateLog(data) {
  try {
    logBtUpdate(
      data.session_id, 
      data.basic_type, 
      data.category, 
      data.update_action || 'logged',
      [],
      data.sku_name
    );
    
    return ContentService
      .createTextOutput(JSON.stringify({ 
        success: true, 
        message: 'BT Update logged successfully'
      }))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    return ContentService
      .createTextOutput(JSON.stringify({ 
        success: false, 
        error: error.toString() 
      }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Log BT update actions to BT_Update_Log sheet
 * @param {string} sessionId - Session ID
 * @param {string} basicType - The basic type name
 * @param {string} category - The category
 * @param {string} action - The action taken (added, accepted, suggested, etc.)
 * @param {Array} genericKeywords - Generic keywords added with this BT
 * @param {string} skuName - The SKU name that triggered the update (optional)
 */
function logBtUpdate(sessionId, basicType, category, action, genericKeywords, skuName) {
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    let logSheet = ss.getSheetByName('BT_Update_Log');
    
    // Create log sheet if it doesn't exist
    if (!logSheet) {
      logSheet = ss.insertSheet('BT_Update_Log');
      logSheet.getRange(1, 1, 1, 7).setValues([[
        'Timestamp', 
        'Session ID', 
        'Basic Type', 
        'Category', 
        'Action', 
        'Generic Keywords',
        'Source SKU'
      ]]);
      logSheet.getRange(1, 1, 1, 7)
        .setFontWeight('bold')
        .setBackground('#4285f4')
        .setFontColor('white');
      logSheet.setFrozenRows(1);
      
      // Set column widths
      logSheet.setColumnWidth(1, 180);  // Timestamp
      logSheet.setColumnWidth(2, 100);  // Session ID
      logSheet.setColumnWidth(3, 150);  // Basic Type
      logSheet.setColumnWidth(4, 150);  // Category
      logSheet.setColumnWidth(5, 100);  // Action
      logSheet.setColumnWidth(6, 250);  // Generic Keywords
      logSheet.setColumnWidth(7, 200);  // Source SKU
    }
    
    const timestamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss');
    const keywordsStr = genericKeywords && genericKeywords.length > 0 
      ? genericKeywords.join(', ') 
      : '';
    
    logSheet.appendRow([
      timestamp,
      sessionId || 'Unknown',
      basicType,
      category,
      action,
      keywordsStr,
      skuName || ''
    ]);
    
  } catch (e) {
    // Silently fail logging - don't affect main operation
    Logger.log('Error logging BT update: ' + e.toString());
  }
}

/**
 * Get pending (untagged) SKUs from the 'SKU Names' sheet.
 * Returns rows where column B (Category) is empty, starting from row 2 (skip header).
 * 
 * @param {Object} data - Request data containing:
 *   - limit: (optional) Max number of SKUs to return. Default 15.
 * @returns {Object} JSON with {skus: [{row, sku_name}, ...], total_pending}
 */
function handleGetPendingSkus(data) {
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sheet = ss.getSheetByName('SKU Names');
    
    if (!sheet) {
      return ContentService
        .createTextOutput(JSON.stringify({ success: false, error: "'SKU Names' sheet not found" }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    
    const limit = data.limit || 15;
    const lastRow = sheet.getLastRow();
    
    if (lastRow < 2) {
      return ContentService
        .createTextOutput(JSON.stringify({ success: true, skus: [], total_pending: 0 }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    
    // Read all data (cols A-D, rows 2 to last)
    const allData = sheet.getRange(2, 1, lastRow - 1, 4).getValues();
    
    const pendingSkus = [];
    let totalPending = 0;
    
    for (let i = 0; i < allData.length; i++) {
      const skuName = allData[i][0];
      const category = allData[i][1];
      
      // Skip rows with no SKU name
      if (!skuName || String(skuName).trim() === '') continue;
      
      // Check if Category (col B) is empty — means untagged
      if (!category || String(category).trim() === '') {
        totalPending++;
        if (pendingSkus.length < limit) {
          pendingSkus.push({
            row: i + 2,  // 1-indexed sheet row (accounting for header)
            sku_name: String(skuName).trim()
          });
        }
      }
    }
    
    return ContentService
      .createTextOutput(JSON.stringify({
        success: true,
        skus: pendingSkus,
        total_pending: totalPending
      }))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    return ContentService
      .createTextOutput(JSON.stringify({ success: false, error: error.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Update tagged SKU data back into the 'SKU Names' sheet.
 * Writes Category (col B), Basic Type (col C), and Generic Keywords (col D)
 * for the specified rows.
 * 
 * @param {Object} data - Request data containing:
 *   - updates: Array of {row, category, basic_type, generic_keywords}
 *     where row is the 1-indexed sheet row number
 */
function handleUpdateSkuTags(data) {
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sheet = ss.getSheetByName('SKU Names');
    
    if (!sheet) {
      return ContentService
        .createTextOutput(JSON.stringify({ success: false, error: "'SKU Names' sheet not found" }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    
    const updates = data.updates || [];
    let updatedCount = 0;
    
    for (const update of updates) {
      const row = update.row;
      const category = update.category || '';
      const basicType = update.basic_type || '';
      const gks = update.generic_keywords || '';
      
      if (!row || row < 2) continue;  // Skip invalid rows or header
      
      // Write Category (B), Basic Type (C), GKs (D) in one call per row
      sheet.getRange(row, 2, 1, 3).setValues([[category, basicType, gks]]);
      updatedCount++;
    }
    
    return ContentService
      .createTextOutput(JSON.stringify({
        success: true,
        message: updatedCount + ' SKUs updated in SKU Names sheet',
        updated_count: updatedCount
      }))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    return ContentService
      .createTextOutput(JSON.stringify({ success: false, error: error.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Handle GET requests (for testing)
 */
function doGet(e) {
  // Initialize the sheet if it doesn't exist
  initializeSheet();
  
  return ContentService
    .createTextOutput(JSON.stringify({ 
      success: true, 
      message: 'GPT Token Costs logging endpoint is active. Use POST to log data.',
      spreadsheet_id: SPREADSHEET_ID,
      sheet_name: SHEET_NAME
    }))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Function to manually initialize the sheet (run this once)
 * You can run this function directly from the Apps Script editor
 */
function setupSheet() {
  initializeSheet();
  Logger.log('Sheet initialized successfully!');
}

/**
 * Function to get summary statistics
 * Run this from Apps Script editor to see cost summary
 */
function getCostSummary() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(SHEET_NAME);
  
  if (!sheet) {
    Logger.log('Sheet not found');
    return;
  }
  
  const lastRow = sheet.getLastRow();
  if (lastRow <= 1) {
    Logger.log('No data found');
    return;
  }
  
  // Get all data
  const data = sheet.getRange(2, 1, lastRow - 1, 13).getValues();
  
  let totalCost = 0;
  let totalTokens = 0;
  let operationCounts = {};
  
  data.forEach(row => {
    totalTokens += row[7] || 0;  // Total Tokens column
    totalCost += row[10] || 0;   // Total Cost column
    
    const operation = row[2] || 'Unknown';
    operationCounts[operation] = (operationCounts[operation] || 0) + 1;
  });
  
  Logger.log('=== GPT Token Costs Summary ===');
  Logger.log('Total API Calls: ' + data.length);
  Logger.log('Total Tokens: ' + totalTokens.toLocaleString());
  Logger.log('Total Cost: $' + totalCost.toFixed(6));
  Logger.log('');
  Logger.log('Calls by Operation:');
  Object.keys(operationCounts).forEach(op => {
    Logger.log('  ' + op + ': ' + operationCounts[op]);
  });
}

/**
 * Add a summary row with formulas (optional - run once to add summary formulas)
 */
function addSummaryFormulas() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  let summarySheet = ss.getSheetByName('GPT Costs Summary');
  
  // Create summary sheet if it doesn't exist
  if (!summarySheet) {
    summarySheet = ss.insertSheet('GPT Costs Summary');
  }
  
  // Clear and set up summary
  summarySheet.clear();
  
  const summaryData = [
    ['GPT Token Costs Summary', ''],
    ['', ''],
    ['Metric', 'Value'],
    ['Total API Calls', '=COUNTA(\'GPT Token Costs\'!A:A)-1'],
    ['Total Tokens', '=SUM(\'GPT Token Costs\'!H:H)'],
    ['Total Cost (USD)', '=SUM(\'GPT Token Costs\'!K:K)'],
    ['Average Cost per Call', '=IF(B4>0,B6/B4,0)'],
    ['', ''],
    ['By Operation', ''],
    ['Find Categories', '=SUMIF(\'GPT Token Costs\'!C:C,"Find Categories",\'GPT Token Costs\'!K:K)'],
    ['Find Basic Types', '=SUMIF(\'GPT Token Costs\'!C:C,"Find Basic Types",\'GPT Token Costs\'!K:K)'],
    ['Find Generic Keywords', '=SUMIF(\'GPT Token Costs\'!C:C,"Find Generic Keywords",\'GPT Token Costs\'!K:K)']
  ];
  
  summarySheet.getRange(1, 1, summaryData.length, 2).setValues(summaryData);
  
  // Format
  summarySheet.getRange(1, 1).setFontSize(14).setFontWeight('bold');
  summarySheet.getRange(3, 1, 1, 2).setFontWeight('bold').setBackground('#e8e8e8');
  summarySheet.getRange(9, 1).setFontWeight('bold');
  
  // Format currency cells
  summarySheet.getRange(6, 2).setNumberFormat('$0.000000');
  summarySheet.getRange(7, 2).setNumberFormat('$0.000000');
  summarySheet.getRange(10, 2, 3, 1).setNumberFormat('$0.000000');
  
  // Format number cells
  summarySheet.getRange(4, 2).setNumberFormat('#,##0');
  summarySheet.getRange(5, 2).setNumberFormat('#,##0');
  
  // Set column widths
  summarySheet.setColumnWidth(1, 200);
  summarySheet.setColumnWidth(2, 150);
  
  Logger.log('Summary sheet created!');
}

// =============================================================================
// SKU Tagging Sheet (External Spreadsheet) Handlers
// =============================================================================

/**
 * Get SKUs from the Main sheet with pagination.
 * Sheet columns: A=SKU Name, B=Category, C=Basic Type, D=Generic Keywords
 * 
 * @param {Object} data - Request data containing:
 *   - offset: 0-based row offset (default 0)
 *   - limit: max number of rows to return (default 100)
 * @returns {Object} JSON with {skus: [{row, sku_name, category, basic_type, generic_keywords}, ...], total_rows}
 */
function handleGetMainSKUs(data) {
  try {
    const ss = SpreadsheetApp.openById(SKU_TAGGING_SPREADSHEET_ID);
    const sheet = ss.getSheetByName(SKU_TAGGING_SHEET_NAME);
    
    if (!sheet) {
      return ContentService
        .createTextOutput(JSON.stringify({ 
          success: false, 
          error: "'" + SKU_TAGGING_SHEET_NAME + "' sheet not found in spreadsheet " + SKU_TAGGING_SPREADSHEET_ID 
        }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    
    const offset = data.offset || 0;
    const limit = data.limit || 100;
    const lastRow = sheet.getLastRow();
    
    // Total data rows (excluding header)
    const totalRows = lastRow > 1 ? lastRow - 1 : 0;
    
    if (totalRows === 0) {
      return ContentService
        .createTextOutput(JSON.stringify({ success: true, skus: [], total_rows: 0 }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    
    // Calculate start row (1-indexed, skip header row 1)
    const startRow = 2 + offset;
    
    // Don't read past the last row
    if (startRow > lastRow) {
      return ContentService
        .createTextOutput(JSON.stringify({ success: true, skus: [], total_rows: totalRows }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    
    // Calculate how many rows to read
    const rowsToRead = Math.min(limit, lastRow - startRow + 1);
    
    if (rowsToRead <= 0) {
      return ContentService
        .createTextOutput(JSON.stringify({ success: true, skus: [], total_rows: totalRows }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    
    // Read data (cols A-D)
    const allData = sheet.getRange(startRow, 1, rowsToRead, 4).getValues();
    
    const skus = [];
    for (let i = 0; i < allData.length; i++) {
      const skuName = allData[i][0];
      const category = allData[i][1] || '';
      const basicType = allData[i][2] || '';
      const genericKeywords = allData[i][3] || '';
      
      // Skip rows with no SKU name
      if (!skuName || String(skuName).trim() === '') continue;
      
      skus.push({
        row: startRow + i,  // 1-indexed sheet row
        sku_name: String(skuName).trim(),
        category: String(category).trim(),
        basic_type: String(basicType).trim(),
        generic_keywords: String(genericKeywords).trim()
      });
    }
    
    return ContentService
      .createTextOutput(JSON.stringify({
        success: true,
        skus: skus,
        total_rows: totalRows,
        offset: offset,
        limit: limit
      }))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    return ContentService
      .createTextOutput(JSON.stringify({ success: false, error: error.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Update SKU tags in the Main sheet.
 * Writes Category (col B), Basic Type (col C), and Generic Keywords (col D).
 * 
 * @param {Object} data - Request data containing:
 *   - updates: Array of {row, category, basic_type, generic_keywords}
 *     where row is the 1-indexed sheet row number
 * @returns {Object} JSON with {success, message, updated_count}
 */
function handleUpdateMainSKUTags(data) {
  try {
    const ss = SpreadsheetApp.openById(SKU_TAGGING_SPREADSHEET_ID);
    const sheet = ss.getSheetByName(SKU_TAGGING_SHEET_NAME);
    
    if (!sheet) {
      return ContentService
        .createTextOutput(JSON.stringify({ 
          success: false, 
          error: "'" + SKU_TAGGING_SHEET_NAME + "' sheet not found" 
        }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    
    const updates = data.updates || [];
    let updatedCount = 0;
    const errors = [];
    
    for (const update of updates) {
      const row = update.row;
      const category = update.category || '';
      const basicType = update.basic_type || '';
      const gks = update.generic_keywords || '';
      
      if (!row || row < 2) {
        errors.push('Invalid row: ' + row);
        continue;
      }
      
      try {
        // Write Category (B), Basic Type (C), GKs (D) in one call per row
        sheet.getRange(row, 2, 1, 3).setValues([[category, basicType, gks]]);
        updatedCount++;
      } catch (rowError) {
        errors.push('Row ' + row + ': ' + rowError.toString());
      }
    }
    
    return ContentService
      .createTextOutput(JSON.stringify({
        success: true,
        message: updatedCount + ' SKUs updated in Main sheet',
        updated_count: updatedCount,
        errors: errors.length > 0 ? errors : undefined
      }))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    return ContentService
      .createTextOutput(JSON.stringify({ success: false, error: error.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
