# IESViewerAudit.py — Enhanced ACC Revit Viewer with Browser-Based File Export
# Clean implementation with cache system and direct browser downloads

import base64, json, sys, threading, time, signal, os
from datetime import datetime
import concurrent.futures
import requests
from PySide6.QtCore import Qt, QUrl, Signal, QStandardPaths, Slot
from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QListWidget, QTextEdit, QLabel, QMessageBox, QFileDialog,
    QInputDialog, QProgressDialog, QListWidgetItem
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineDownloadRequest, QWebEnginePage

# ====== CONFIG ======
HTTP_TIMEOUT = 30
MAX_RETRIES = 3
MAX_CONCURRENT_WORKERS = 8

CLIENT_ID = 'QuwJpBozcnP3KUAZFpTbdVQwy85GhWTtqIA19PZjQbYKDpGN'
CLIENT_SECRET = '8AUhAiqEB9kOz5eMcDWEGGtMLDKKZOxEkCLyaJAIfbGwCUC1HqjQRBa4wmsygG2b'
PROJECT_ID = 'b.fd51fd8c-27ec-4d55-9572-e705effe0b95'
HUB_ID = 'b.0f682712-9953-4a8a-9c34-0ece721e7b0e'
BASE_URL = 'https://developer.api.autodesk.com'

# Session with connection pooling
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=3)
session.mount('https://', adapter)

# ===== OAuth (2-legged) =====
def get_token_2L():
    r = session.post(
        f"{BASE_URL}/authentication/v2/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "client_credentials",
            "scope": "data:read data:write viewables:read account:read"
        },
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        timeout=HTTP_TIMEOUT
    )
    r.raise_for_status()
    return r.json()["access_token"]

# ===== Helpers =====
def make_request_with_retry(func, *args, **kwargs):
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
            last = e
            time.sleep(2**attempt)
    raise last

def encode_urn(urn: str) -> str:
    return base64.urlsafe_b64encode(urn.encode()).decode().rstrip("=")

# ===== Multi-Project API Functions =====
def get_hubs(token):
    """Fetch all accessible hubs"""
    try:
        response = make_request_with_retry(
            session.get,
            f"{BASE_URL}/project/v1/hubs",
            headers={'Authorization': f'Bearer {token}'},
            timeout=HTTP_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        hubs = []
        for hub in data.get('data', []):
            hubs.append({
                'id': hub['id'],
                'name': hub['attributes']['name'],
                'region': hub['attributes'].get('region', 'US')
            })
        return hubs
    except Exception as e:
        print(f"Error fetching hubs: {e}")
        return []

def get_projects(token, hub_id):
    """Fetch all projects in a hub"""
    try:
        response = make_request_with_retry(
            session.get,
            f"{BASE_URL}/project/v1/hubs/{hub_id}/projects",
            headers={'Authorization': f'Bearer {token}'},
            timeout=HTTP_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        projects = []
        for project in data.get('data', []):
            projects.append({
                'id': project['id'],
                'name': project['attributes']['name'],
                'hub_id': hub_id
            })
        return projects
    except Exception as e:
        print(f"Error fetching projects for hub {hub_id}: {e}")
        return []

def get_all_projects(token):
    """Fetch all projects across all hubs"""
    all_projects = []
    hubs = get_hubs(token)
    
    print(f"Found {len(hubs)} hub(s)")
    for hub in hubs:
        print(f"  Fetching projects from hub: {hub['name']}")
        projects = get_projects(token, hub['id'])
        for project in projects:
            project['hub_name'] = hub['name']
        all_projects.extend(projects)
    
    print(f"Total projects found: {len(all_projects)}")
    return all_projects

def get_project_files(token, project_id, folder_id=None):
    """Fetch files/folders in a project (used for model enumeration)"""
    try:
        # If no folder_id, get the project's top folders
        if not folder_id:
            response = make_request_with_retry(
                session.get,
                f"{BASE_URL}/project/v1/hubs/{HUB_ID}/projects/{project_id}/topFolders",
                headers={'Authorization': f'Bearer {token}'},
                timeout=HTTP_TIMEOUT
            )
        else:
            response = make_request_with_retry(
                session.get,
                f"{BASE_URL}/data/v1/projects/{project_id}/folders/{folder_id}/contents",
                headers={'Authorization': f'Bearer {token}'},
                timeout=HTTP_TIMEOUT
            )
        
        response.raise_for_status()
        return response.json().get('data', [])
    except Exception as e:
        print(f"Error fetching project files: {e}")
        return []

# ===== Custom WebEnginePage to capture console messages =====
class ConsoleLoggingPage(QWebEnginePage):
    console_message = Signal(str)
    
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # Filter verbose element logs unless verbose mode is enabled
        # Element logs look like "Element 1 name: ..." or "Element 1 properties: ..."
        if message.startswith('Element ') and ('name:' in message or 'properties:' in message):
            # This is a verbose element debug log - only forward if verbose logging is enabled
            # Note: We can't access self.verbose_logging here, so we check the message content
            # The verbose flag is passed to JavaScript, so verbose logs will only appear if enabled
            pass  # Let it through - JavaScript already filters based on window.verboseLogging
        
        # Detect fatal CORS errors from Autodesk CDN
        if 'CORS policy' in message or 'blocked by CORS' in message:
            # Set a JavaScript flag so extraction can detect this fatal error
            self.runJavaScript(
                "window.extractionError = 'CORS policy error - model resources blocked'; "
                "window.extractionComplete = true;"
            )
        
        # Forward console messages to Qt signal
        self.console_message.emit(f"[JS Console] {message}")

def get_root_folder(hub_id, project_id, token):
    def _req():
        r = session.get(
            f"{BASE_URL}/project/v1/hubs/{hub_id}/projects/{project_id}",
            headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT
        )
        r.raise_for_status()
        return r.json()["data"]["relationships"]["rootFolder"]["data"]["id"]
    return make_request_with_retry(_req)

def get_latest_version_urn(project_id, item_id, token):
    def _req():
        r = session.get(
            f"{BASE_URL}/data/v1/projects/{project_id}/items/{item_id}/versions",
            headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT
        )
        r.raise_for_status()
        vs = r.json().get("data", [])
        return vs[0]["id"] if vs else None
    return make_request_with_retry(_req)

def is_revit_file(name): 
    return name and name.lower().endswith(".rvt")

def is_likely_revit_folder(folder_name):
    skip = ['temp','backup','archive','old','deleted','admin','logs','cache','trash']
    return not any(p in folder_name.lower() for p in skip)

def find_revit_files_concurrent(token, project_id, folder_id, current_path="", progress_callback=None):
    results = []
    def scan_folder(fid, fpath):
        local, subs = [], []
        def _get_contents():
            r = session.get(
                f"{BASE_URL}/data/v1/projects/{project_id}/folders/{fid}/contents",
                headers={'Authorization': f'Bearer {token}'}, timeout=HTTP_TIMEOUT
            )
            r.raise_for_status()
            return r.json()
        try:
            js = make_request_with_retry(_get_contents)
            for item in js.get('data', []):
                if item['type'] == 'folders':
                    name = item['attributes']['name']
                    if is_likely_revit_folder(name):
                        subs.append((item['id'], f"{fpath}/{name}" if fpath else name))
                elif item['type'] == 'items':
                    fname = item['attributes'].get('displayName') or item['attributes'].get('name')
                    if is_revit_file(fname):
                        if progress_callback: progress_callback(f"✅ Found: {fname}")
                        results.append({
                            'name': fname,
                            'path': fpath,
                            'full_path': f"{fpath}/{fname}" if fpath else fname,
                            'item_id': item['id'],
                            'version_urn': get_latest_version_urn(project_id, item['id'], token)
                        })
            return subs
        except Exception as e:
            if progress_callback: progress_callback(f"❌ Error scanning {fpath}: {e}")
            return []
    folders = [(folder_id, current_path)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_WORKERS) as ex:
        while folders:
            futures = {ex.submit(scan_folder, fid, fp): (fid, fp) for fid, fp in folders}
            folders = []
            for f in concurrent.futures.as_completed(futures):
                folders.extend(f.result())
    return results

# ===== Enhanced Viewer HTML with Browser Downloads =====
def build_enhanced_viewer_html(encoded_urn, access_token, filename, verbose_logging=False, extraction_delay_seconds=2):
    """Enhanced viewer with Model Hierarchy extraction and browser-based file downloads"""
    # Sanitize filename for JavaScript (escape quotes and backslashes)
    js_safe_filename = filename.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
    
    # Convert delay to milliseconds for JavaScript
    delay_ms = extraction_delay_seconds * 1000
    print(f"DEBUG: build_enhanced_viewer_html called with extraction_delay_seconds={extraction_delay_seconds}, delay_ms={delay_ms}")
    
    return f"""<!doctype html>
<html><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Enhanced Viewer - {filename}</title>
<script src="https://developer.api.autodesk.com/modelderivative/v2/viewers/7.*/viewer3D.min.js"></script>
<link rel="stylesheet" href="https://developer.api.autodesk.com/modelderivative/v2/viewers/7.*/style.min.css"/>
<style>
html,body{{height:100%;margin:0;background:#000;font-family:Arial,sans-serif;}}
#v{{width:100%;height:100vh;}}
#extractPanel{{
  position:fixed;top:20px;right:20px;width:320px;
  background:rgba(255,255,255,0.95);border:2px solid #007acc;border-radius:8px;
  padding:15px;box-shadow:0 4px 15px rgba(0,0,0,0.3);z-index:1000;
  display:none;
}}
.extract-btn{{
  display:block;width:100%;padding:10px;margin:6px 0;
  background:#007acc;color:white;border:none;border-radius:4px;
  cursor:pointer;font-size:13px;font-weight:bold;
}}
.extract-btn:hover{{background:#005a9e;}}
.extract-btn:disabled{{background:#ccc;cursor:not-allowed;}}
#extractStatus{{
  padding:10px;background:#f0f8ff;margin:6px 0;border-radius:4px;
  border-left:3px solid #007acc;font-size:11px;
}}
#extractResults{{
  background:#f8f8f8;padding:10px;margin:6px 0;border-radius:4px;
  max-height:200px;overflow-y:auto;font-size:10px;border:1px solid #ddd;
}}
.success{{color:#28a745;}}
.error{{color:#dc3545;}}
.processing{{color:#ffc107;}}
</style>
</head><body>
<div id="v"></div>

<div id="extractPanel">
  <div style="font-weight:bold;color:#007acc;margin-bottom:10px;text-align:center;">
    ⚡ Model Hierarchy Extraction
  </div>
  
  <button id="extractBtn" class="extract-btn" onclick="performExtraction()">
    🚀 Extract All Elements
  </button>
  
  <button class="extract-btn" onclick="showDetailedData()">
    📝 Show Detailed Data
  </button>
  
  <button class="extract-btn" onclick="downloadCSV()">
    💾 Download CSV File
  </button>
  
  <button class="extract-btn" onclick="downloadExcel()">
    📊 Download Excel File
  </button>
  
  <button class="extract-btn" onclick="hidePanel()">
    ❌ Hide Panel
  </button>
  
  <div id="extractStatus">Ready for extraction...</div>
  <div id="extractResults">Click "Extract All Elements" to begin...</div>
</div>

<script>
// Configuration values injected from Python
var EXTRACTION_DELAY_MS = {delay_ms};
var EXTRACTION_DELAY_SECONDS = {extraction_delay_seconds};
console.log('⚙️ Configuration loaded: extraction delay = ' + EXTRACTION_DELAY_SECONDS + 's (' + EXTRACTION_DELAY_MS + 'ms)');

var viewer;
var extractionResults = [];
var modelFileName = "{js_safe_filename}";
window.verboseLogging = {'true' if verbose_logging else 'false'};
window.extractionError = null; // Track extraction errors
window.extractionComplete = false;

function updateStatus(message, className = '') {{
  document.getElementById('extractStatus').innerHTML = message;
  document.getElementById('extractStatus').className = className;
  console.log('[EXTRACT] ' + message);
}}

function performExtraction() {{
  if (!viewer || !viewer.model) {{
    alert('Model not ready yet. Please wait for model to finish loading.');
    return;
  }}
  
  const extractBtn = document.getElementById('extractBtn');
  extractBtn.disabled = true;
  extractBtn.innerHTML = '⏳ Extracting...';
  
  updateStatus('🎯 Starting Model Hierarchy extraction...', 'processing');
  
  try {{
    const model = viewer.model;
    const instanceTree = model.getInstanceTree();
    
    if (!instanceTree) {{
      throw new Error('Instance tree not available');
    }}
    
    updateStatus('📊 Getting all element nodes...', 'processing');
    
    const rootId = instanceTree.getRootId();
    const allNodeIds = [];
    
    instanceTree.enumNodeChildren(rootId, function(nodeId) {{
      allNodeIds.push(nodeId);
    }}, true);
    
    updateStatus(`⚡ Found ${{allNodeIds.length}} nodes. Extracting properties...`, 'processing');
    
    if (allNodeIds.length === 0) {{
      throw new Error('No nodes found in model');
    }}
    
    model.getBulkProperties(allNodeIds, {{}}, function(results) {{
      updateStatus('🔄 Processing element data...', 'processing');
      
      try {{
        const processedElements = results.map((result) => {{
          const props = {{}};
          if (result.properties && Array.isArray(result.properties)) {{
            result.properties.forEach(prop => {{
              props[prop.displayName] = prop.displayValue;
            }});
          }}
          
          // Debug: Log first 100 elements' properties when verbose mode is enabled
          if (window.verboseLogging && results.indexOf(result) < 100) {{
            console.log(`Element ${{results.indexOf(result) + 1}} name: "${{result.name}}"`);
            console.log(`Element ${{results.indexOf(result) + 1}} properties:`, JSON.stringify(props, null, 2));
          }}
          
          // Only extract actual Revit elements (must have ElementId property)
          const elementId = props['ElementId'] || '';
          if (!elementId) {{
            return null; // Skip containers and groups - only process real elements
          }}
          
          // Get category - actual elements use full category name like "Revit Conduits"
          let category = props['Category'] || 'Unknown Category';
          // Remove "Revit " prefix if present
          if (category.startsWith('Revit ')) {{
            category = category.substring(6);
          }}
          
          // Also check _RC for category name
          if (props['_RC']) {{
            category = props['_RC'];
          }}
          
          // Extract Family and Type
          let type = props['Type Name'] || props['Type'] || props['_RFT'] || '';
          let extractedName = '';
          
          // Check if Type contains comma (indicating Type,Name format)
          if (type && type.includes(',')) {{
            const commaParts = type.split(',');
            type = commaParts[0].trim().replace(/^"|"$/g, '');  // First part is Type, remove surrounding quotes
            extractedName = commaParts.slice(1).join(',').trim().replace(/^"|"$/g, '');  // Rest is Name, remove surrounding quotes
          }}
          
          // If Type not in properties, try parsing from element name
          // Format is typically "FamilyName : TypeName" or "FamilyName [ElementId]"
          if (!type) {{
            // Remove [ElementId] suffix if present (regex pattern for whitespace and digits in brackets)
            let cleanName = result.name ? result.name.replace(/\\s*\\[\\d+\\]\\s*$/, '') : '';
            const nameParts = cleanName.split(' : ');
            if (nameParts.length === 2) {{
              // Format: "Family : Type" - use the Type part
              type = nameParts[1].trim();
            }} else if (nameParts.length === 1 && cleanName) {{
              // Only one part, use Type Name property or the name itself
              type = props['Type Name'] || cleanName.trim();
            }}
          }}
          
          // If Type is still empty, use placeholder to prevent CSV column shift
          if (!type || type.trim() === '') {{
            type = '-';
          }}
          
          // Extract additional properties
          const nominalDiameter = parseFloat(props['Nominal Diameter'] || 0);
          const buildingId = props['Building Identification'] || '';
          const sector = props['Sector'] || '';
          
          // Extract Discipline from filename - delimited by hyphens
          // Example: "XOHWT1-AAA-670-T0-A0P00-IES-CM.rvt" -> Discipline = "T0" (4th segment)
          // Example: "XOHF27-2SA-630-H0-ABBB0-IES-DM.rvt" -> Discipline = "H0" (4th segment)
          let discipline = '';
          const filenameParts = modelFileName.split('-');
          if (filenameParts.length >= 4) {{
            // Discipline code is the 4th segment (index 3)
            discipline = filenameParts[3].trim();
          }}
          
          // Extract additional 8 columns
          const panelRack = props['Panel/Rack'] || '';
          const equipmentTrayTo = props['Equipment/Tray To'] || '';
          const workset = props['Workset'] || '';
          const conduitExcess = parseFloat(props['Conduit excess'] || 0);
          const centerToEnd = parseFloat(props['Center to End'] || 0);
          const bendRadius = parseFloat(props['Bend Radius'] || 0);
          const angle = parseFloat(props['Angle'] || 0);
          const size = props['Size'] || '';
          
          // Extract additional 2 columns (HSM and AH)
          const hsm = parseFloat(props['HSM'] || 0);
          const ah = parseFloat(props['AH'] || 0);
          
          return {{
            fileName: modelFileName,
            elementId: elementId,
            discipline: discipline,
            svf2Id: result.dbId,
            lmvName: extractedName || result.name || props['Name'] || 'Unknown Element',
            revitCategory: category,
            revitType: type || '',
            nominalDiameter: nominalDiameter,
            buildingId: buildingId,
            sector: sector,
            Count: 1,
            TotalLength: parseFloat(props['Length'] || props['Area'] || props['Volume'] || 0),
            panelRack: panelRack,
            equipmentTrayTo: equipmentTrayTo,
            workset: workset,
            conduitExcess: conduitExcess,
            centerToEnd: centerToEnd,
            bendRadius: bendRadius,
            angle: angle,
            size: size,
            hsm: hsm,
            ah: ah
          }};
        }}).filter(element => element !== null); // Remove null entries (skipped containers)
        
        extractionResults = processedElements;
        displayResults(processedElements);
        updateStatus(`🎉 SUCCESS! Extracted ${{processedElements.length}} actual Revit elements`, 'success');
        
        window.extractionComplete = true;
        window.getExtractionResults = function() {{ return extractionResults; }};
        
      }} catch (error) {{
        throw new Error('Error processing properties: ' + error.message);
      }}
      
    }}, function(error) {{
      throw new Error('getBulkProperties failed: ' + error);
    }});
    
  }} catch (error) {{
    updateStatus(`❌ Extraction failed: ${{error.message}}`, 'error');
    document.getElementById('extractResults').innerHTML = 
      `<p style="color:red;">❌ Error: ${{error.message}}</p>`;
    
    // Store error for Python to check
    window.extractionError = error.message;
    window.extractionComplete = true; // Mark as complete (with error)
    console.error('Extraction error:', error.message);
  }} finally {{
    extractBtn.disabled = false;
    extractBtn.innerHTML = '🚀 Extract All Elements';
  }}
}}

function displayResults(elements) {{
  if (!elements || elements.length === 0) {{
    document.getElementById('extractResults').innerHTML = '<p>No elements found</p>';
    return;
  }}
  
  const byCategory = {{}};
  elements.forEach(element => {{
    const cat = element.revitCategory;
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(element);
  }});
  
  let html = `<div style="font-weight:bold;margin-bottom:8px;">📊 ${{elements.length}} Elements</div>`;
  
  for (const [category, catElements] of Object.entries(byCategory)) {{
    html += `<div style="margin:3px 0;padding:4px;background:#e8f4fd;border-radius:3px;font-size:9px;">`;
    html += `<strong>${{category}}: ${{catElements.length}}</strong>`;
    html += `</div>`;
    
    if (catElements.length > 0) {{
      const first = catElements[0];
      html += `<div style="margin-left:10px;color:#666;font-size:8px;">`;
      html += `• ${{first.revitFamily}} - ${{first.lmvName}}`;
      if (catElements.length > 1) {{
        html += ` (+${{catElements.length-1}} more)`;
      }}
      html += `</div>`;
    }}
  }}
  
  html += `<div style="margin-top:8px;padding:6px;background:#d4edda;border-radius:3px;font-size:9px;">`;
  html += `<strong>✅ Extraction Complete!</strong><br>`;
  html += `Using viewer.model.getBulkProperties() - same as Model Hierarchy`;
  html += `</div>`;
  
  document.getElementById('extractResults').innerHTML = html;
}}

function showDetailedData() {{
  if (!extractionResults || extractionResults.length === 0) {{
    alert('No extraction results to show. Run extraction first.');
    return;
  }}
  
  let html = `<div style="font-weight:bold;margin-bottom:8px;">📋 Detailed CSV Data (${{extractionResults.length}} elements)</div>`;
  html += `<div style="font-size:5px;color:#666;margin-bottom:6px;">FileName | ElementId | Disc | Category | Type | Name | NomDia | Bldg | Sector | Count | Length | Panel | EquipTo | Workset | CondExcess | CenterEnd | BendRad | Angle | Size | HSM | AH</div>`;
  
  extractionResults.slice(0, 10).forEach((element, index) => {{
    html += `<div style="font-size:4px;margin:1px 0;padding:2px;background:#f8f8f8;border-left:2px solid #007acc;">`;
    html += `${{element.fileName}} | ${{element.elementId}} | ${{element.discipline}} | ${{element.revitCategory}} | ${{element.revitType}} | ${{element.lmvName}} | ${{element.nominalDiameter}} | ${{element.buildingId}} | ${{element.sector}} | ${{element.Count}} | ${{element.TotalLength}} | ${{element.panelRack}} | ${{element.equipmentTrayTo}} | ${{element.workset}} | ${{element.conduitExcess}} | ${{element.centerToEnd}} | ${{element.bendRadius}} | ${{element.angle}} | ${{element.size}} | ${{element.hsm}} | ${{element.ah}}`;
    html += `</div>`;
  }});
  
  if (extractionResults.length > 10) {{
    html += `<div style="font-size:8px;color:#666;margin-top:4px;">... and ${{extractionResults.length - 10}} more elements</div>`;
  }}
  
  html += `<div style="margin-top:6px;padding:4px;background:#e8f4fd;border-radius:3px;font-size:8px;">`;
  html += `Click "Download CSV" to save all ${{extractionResults.length}} elements`;
  html += `</div>`;
  
  document.getElementById('extractResults').innerHTML = html;
}}

function downloadCSV() {{
  if (!extractionResults || extractionResults.length === 0) {{
    alert('No extraction results to download. Run extraction first.');
    return;
  }}
  
  updateStatus('💾 Generating CSV file...', 'processing');
  
  try {{
    // Helper function to escape CSV fields (remove newlines/tabs, double quotes, wrap in quotes)
    const escapeCsv = (val) => {{
      if (val === null || val === undefined) return '""';  // Return quoted empty string, not empty
      const str = String(val);
      // Remove newlines, carriage returns, tabs, then escape quotes by doubling them
      const cleaned = str.replace(/[\\n\\r\\t]/g, ' ').trim();
      return `"${{cleaned.replace(/"/g, '""')}}"`;
    }};
    
    // Generate CSV content - Column order: FileName, ElementId, Discipline, Category, Type, Name, NominalDiameter, BuildingId, Sector, Count, TotalLength, Panel/Rack, Equipment/Tray To, Workset, Conduit excess, Center to End, Bend Radius, Angle, Size, HSM, AH
    // Add UTF-8 BOM for Excel compatibility
    let csv = '\\uFEFF';  // UTF-8 BOM
    csv += 'FileName,ElementId,Discipline,Category,Type,Name,NominalDiameter,BuildingId,Sector,Count,TotalLength,Panel/Rack,Equipment/Tray To,Workset,Conduit excess,Center to End,Bend Radius,Angle,Size,HSM,AH\\n';
    extractionResults.forEach((element) => {{
      csv += `${{escapeCsv(element.fileName)}},${{escapeCsv(element.elementId)}},${{escapeCsv(element.discipline)}},${{escapeCsv(element.revitCategory)}},${{escapeCsv(element.revitType)}},${{escapeCsv(element.lmvName)}},${{element.nominalDiameter}},${{escapeCsv(element.buildingId)}},${{escapeCsv(element.sector)}},${{element.Count}},${{element.TotalLength}},${{escapeCsv(element.panelRack)}},${{escapeCsv(element.equipmentTrayTo)}},${{escapeCsv(element.workset)}},${{element.conduitExcess}},${{element.centerToEnd}},${{element.bendRadius}},${{element.angle}},${{escapeCsv(element.size)}},${{element.hsm}},${{element.ah}}\\n`;
    }});
    
    // Create blob and download
    const blob = new Blob([csv], {{ type: 'text/csv;charset=utf-8;' }});
    const link = document.createElement('a');
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const filename = `revit_extract_${{timestamp}}.csv`;
    
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', filename);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    
    updateStatus(`✅ CSV downloaded: ${{filename}} (${{extractionResults.length}} elements)`, 'success');
    console.log('CSV downloaded successfully:', filename);
  }} catch (error) {{
    updateStatus(`❌ Download failed: ${{error.message}}`, 'error');
    console.error('Download error:', error);
  }}
}}

function downloadExcel() {{
  if (!extractionResults || extractionResults.length === 0) {{
    alert('No extraction results to download. Run extraction first.');
    return;
  }}
  
  updateStatus('📊 Generating Excel file...', 'processing');
  
  try {{
    // Helper function to escape CSV fields (remove newlines/tabs, double quotes, wrap in quotes)
    const escapeCsv = (val) => {{
      if (val === null || val === undefined) return '""';  // Return quoted empty string, not empty
      const str = String(val);
      // Remove newlines, carriage returns, tabs, then escape quotes by doubling them
      const cleaned = str.replace(/[\\n\\r\\t]/g, ' ').trim();
      return `"${{cleaned.replace(/"/g, '""')}}"`;
    }};
    
    // Generate CSV (Excel can open CSV files) - Column order: FileName, ElementId, Discipline, Category, Type, Name, NominalDiameter, BuildingId, Sector, Count, TotalLength, Panel/Rack, Equipment/Tray To, Workset, Conduit excess, Center to End, Bend Radius, Angle, Size, HSM, AH
    // Add UTF-8 BOM for Excel compatibility
    let csv = '\\uFEFF';  // UTF-8 BOM
    csv += 'FileName,ElementId,Discipline,Category,Type,Name,NominalDiameter,BuildingId,Sector,Count,TotalLength,Panel/Rack,Equipment/Tray To,Workset,Conduit excess,Center to End,Bend Radius,Angle,Size,HSM,AH\\n';
    extractionResults.forEach((element) => {{
      csv += `${{escapeCsv(element.fileName)}},${{escapeCsv(element.elementId)}},${{escapeCsv(element.discipline)}},${{escapeCsv(element.revitCategory)}},${{escapeCsv(element.revitType)}},${{escapeCsv(element.lmvName)}},${{element.nominalDiameter}},${{escapeCsv(element.buildingId)}},${{escapeCsv(element.sector)}},${{element.Count}},${{element.TotalLength}},${{escapeCsv(element.panelRack)}},${{escapeCsv(element.equipmentTrayTo)}},${{escapeCsv(element.workset)}},${{element.conduitExcess}},${{element.centerToEnd}},${{element.bendRadius}},${{element.angle}},${{escapeCsv(element.size)}},${{element.hsm}},${{element.ah}}\\n`;
    }});
    
    // Create blob and download
    const blob = new Blob([csv], {{ type: 'application/vnd.ms-excel;charset=utf-8;' }});
    const link = document.createElement('a');
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const filename = `revit_extract_${{timestamp}}.csv`;
    
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', filename);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    
    updateStatus(`✅ Excel file downloaded: ${{filename}} (${{extractionResults.length}} elements)`, 'success');
    alert('✅ File downloaded! Right-click → Open with → Microsoft Excel for best experience.');
    console.log('Excel-format file downloaded successfully:', filename);
  }} catch (error) {{
    updateStatus(`❌ Download failed: ${{error.message}}`, 'error');
    console.error('Download error:', error);
  }}
}}

function hidePanel() {{
  document.getElementById('extractPanel').style.display = 'none';
}}

function showExtractionPanel() {{
  document.getElementById('extractPanel').style.display = 'block';
  console.log('🎨 EXTRACTION PANEL DISPLAYED - Buttons now visible in top-right corner');
  window.panelVisible = true;
}}

const options={{ env:'AutodeskProduction', api:'derivativeV2',
  getAccessToken:(cb)=>cb('{access_token}',3600) }};

Autodesk.Viewing.Initializer(options,function(){{
  viewer=new Autodesk.Viewing.GuiViewer3D(document.getElementById('v'));
  
  viewer.addEventListener(Autodesk.Viewing.GEOMETRY_LOADED_EVENT, function() {{
    console.log('✅ GEOMETRY_LOADED_EVENT fired - Model is ready!');
    showExtractionPanel();
    updateStatus('✅ Model Ready! Extraction available.', 'success');
    
    // Auto-extraction mode: start extraction shortly after geometry loads
    if (window.autoExtractMode) {{
      console.log('🤖 Auto-extract mode enabled - waiting ' + EXTRACTION_DELAY_SECONDS + ' seconds for stability...');
      updateStatus('⏳ Model loaded - starting extraction in ' + EXTRACTION_DELAY_SECONDS + ' seconds...', 'processing');
      setTimeout(function() {{
        console.log('🚀 Starting auto-extraction now (waited ' + EXTRACTION_DELAY_SECONDS + 's)...');
        performExtraction();
        // Wait for extraction to complete
        const checkExtraction = setInterval(function() {{
          if (window.extractionComplete && window.getExtractionResults) {{
            clearInterval(checkExtraction);
            console.log('✅ Auto-extraction complete!');
            // Results ready - Qt will retrieve via JavaScript execution
          }}
        }}, 500);
      }}, EXTRACTION_DELAY_MS); // Configurable delay AFTER geometry loads
    }}
  }});
  
  if(viewer.start()>0){{console.error('WebGL not supported');return;}}
  Autodesk.Viewing.Document.load('urn:{encoded_urn}',function(doc){{
    const geom=doc.getRoot().getDefaultGeometry();
    viewer.loadDocumentNode(doc,geom).then(function(){{
      viewer.fitToView();
      console.log('Model ready for extraction!');
    }}).catch(function(error){{
      console.error('Model load error:', error);
    }});
  }},function(err){{console.error('Doc load failure',err);}});
}});

window.performExtraction = performExtraction;
window.getExtractionResults = function() {{ return extractionResults; }};
window.extractionComplete = false;
</script></body></html>"""

# ===== Multi-Project Selection Dialog =====
class ProjectSelectorDialog(QWidget):
    """Dialog for selecting multiple projects to include in a profile"""
    
    def __init__(self, token, parent=None):
        super().__init__(parent)
        self.token = token
        self.setWindowTitle("Select Projects")
        self.resize(600, 500)
        self.selected_projects = []
        
        layout = QVBoxLayout(self)
        
        # Instructions
        instructions = QLabel("Select projects to include in this profile:")
        instructions.setStyleSheet("font-weight: bold; font-size: 11pt;")
        layout.addWidget(instructions)
        
        # Project tree widget
        from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Project Name", "Hub"])
        self.tree.setColumnWidth(0, 350)
        layout.addWidget(self.tree)
        
        # Status label
        self.status_label = QLabel("Loading projects...")
        layout.addWidget(self.status_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.btn_select_all = QPushButton("Select All")
        self.btn_deselect_all = QPushButton("Deselect All")
        self.btn_ok = QPushButton("OK")
        self.btn_cancel = QPushButton("Cancel")
        
        self.btn_select_all.clicked.connect(self.select_all_projects)
        self.btn_deselect_all.clicked.connect(self.deselect_all_projects)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        
        button_layout.addWidget(self.btn_select_all)
        button_layout.addWidget(self.btn_deselect_all)
        button_layout.addStretch()
        button_layout.addWidget(self.btn_ok)
        button_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(button_layout)
        
        # Load projects in background
        threading.Thread(target=self.load_projects, daemon=True).start()
    
    def load_projects(self):
        """Fetch all projects from APS"""
        try:
            projects = get_all_projects(self.token)
            
            # Update UI on main thread
            self.update_project_list(projects)
            
        except Exception as e:
            print(f"Error loading projects: {e}")
            self.status_label.setText(f"❌ Error loading projects: {e}")
    
    def update_project_list(self, projects):
        """Update the project tree with fetched projects"""
        from PySide6.QtWidgets import QTreeWidgetItem
        from PySide6.QtCore import Qt
        
        self.tree.clear()
        self.projects_data = projects
        
        # Group by hub
        hubs = {}
        for project in projects:
            hub_name = project.get('hub_name', 'Unknown Hub')
            if hub_name not in hubs:
                hubs[hub_name] = []
            hubs[hub_name].append(project)
        
        # Add to tree
        for hub_name, hub_projects in sorted(hubs.items()):
            hub_item = QTreeWidgetItem(self.tree, [hub_name, f"({len(hub_projects)} projects)"])
            hub_item.setFlags(hub_item.flags() | Qt.ItemIsUserCheckable)
            hub_item.setCheckState(0, Qt.Unchecked)
            
            for project in sorted(hub_projects, key=lambda p: p['name']):
                project_item = QTreeWidgetItem(hub_item, [project['name'], ''])
                project_item.setFlags(project_item.flags() | Qt.ItemIsUserCheckable)
                project_item.setCheckState(0, Qt.Unchecked)
                project_item.setData(0, Qt.UserRole, project)  # Store project data
        
        self.tree.expandAll()
        self.status_label.setText(f"✅ Loaded {len(projects)} projects from {len(hubs)} hub(s)")
    
    def select_all_projects(self):
        """Check all projects"""
        from PySide6.QtCore import Qt
        for i in range(self.tree.topLevelItemCount()):
            hub_item = self.tree.topLevelItem(i)
            for j in range(hub_item.childCount()):
                project_item = hub_item.child(j)
                project_item.setCheckState(0, Qt.Checked)
    
    def deselect_all_projects(self):
        """Uncheck all projects"""
        from PySide6.QtCore import Qt
        for i in range(self.tree.topLevelItemCount()):
            hub_item = self.tree.topLevelItem(i)
            for j in range(hub_item.childCount()):
                project_item = hub_item.child(j)
                project_item.setCheckState(0, Qt.Unchecked)
    
    def get_selected_projects(self):
        """Get list of checked projects"""
        from PySide6.QtCore import Qt
        selected = []
        for i in range(self.tree.topLevelItemCount()):
            hub_item = self.tree.topLevelItem(i)
            for j in range(hub_item.childCount()):
                project_item = hub_item.child(j)
                if project_item.checkState(0) == Qt.Checked:
                    project_data = project_item.data(0, Qt.UserRole)
                    if project_data:
                        selected.append(project_data)
        return selected
    
    def accept(self):
        """OK button clicked"""
        self.selected_projects = self.get_selected_projects()
        if not self.selected_projects:
            QMessageBox.warning(self, "No Selection", "Please select at least one project.")
            return
        self.close()
    
    def reject(self):
        """Cancel button clicked"""
        self.selected_projects = []
        self.close()

# ===== Qt App with Cache =====
class App(QWidget):
    files_found = Signal(list)
    log_message = Signal(str)

    def __init__(self, token):
        super().__init__()
        self.setWindowTitle("Enhanced ACC Revit Viewer with Extraction")
        self.resize(1400, 800)
        self.token = token
        self.revits=[]; self.selected=None
        
        # Cache settings
        self.cache_file = "revit_files_cache.json"
        self.cache_max_age_hours = 168
        
        # Extraction timing settings
        self.extraction_delay_seconds = 30  # Delay after GEOMETRY_LOADED_EVENT before extraction starts
        self.max_retries = 150  # Maximum retries per model
        
        # Profile settings
        self.profiles_dir = "extraction_profiles"
        self.current_profile = None
        self.batch_extraction_results = []
        self.verbose_logging = False  # Debug output toggle
        
        # Create profiles directory if it doesn't exist
        if not os.path.exists(self.profiles_dir):
            os.makedirs(self.profiles_dir)

        self.files_found.connect(self._update_files)
        self.log_message.connect(self._log)

        root = QHBoxLayout(self)
        left = QVBoxLayout(); right = QVBoxLayout()
        root.addLayout(left, 1); root.addLayout(right, 2)

        # Buttons
        self.btn_refresh = QPushButton("🔍 Search Revit files (F5)")
        self.btn_clear_cache = QPushButton("🗑️ Clear Cache & Refresh")
        self.btn_open = QPushButton("🚀 Open Enhanced Viewer (F7)")
        self.btn_verbose = QPushButton("🐛 Debug Logging: OFF")
        self.btn_test_projects = QPushButton("🔍 Test Multi-Project Access")
        
        # Profile management buttons
        self.btn_save_profile = QPushButton("💾 Save Selection as Profile")
        self.btn_load_profile = QPushButton("📂 Load Profile")
        self.btn_extract_profile = QPushButton("⚡ Extract Profile")
        self.btn_discover_projects = QPushButton("🔍 Discover Multi-Project Files")
        
        # Style buttons
        button_style = """
            QPushButton {
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
                border-radius: 4px;
                border: 1px solid #007acc;
                background-color: #007acc;
                color: white;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                border-color: #cccccc;
            }
        """
        
        cache_button_style = """
            QPushButton {
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
                border-radius: 4px;
                border: 1px solid #dc3545;
                background-color: #dc3545;
                color: white;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """
        
        profile_button_style = """
            QPushButton {
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
                border-radius: 4px;
                border: 1px solid #28a745;
                background-color: #28a745;
                color: white;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                border-color: #cccccc;
            }
        """
        
        verbose_button_style = """
            QPushButton {
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
                border-radius: 4px;
                border: 1px solid #6c757d;
                background-color: #6c757d;
                color: white;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """
        
        self.btn_refresh.setStyleSheet(button_style)
        self.btn_open.setStyleSheet(button_style)
        self.btn_clear_cache.setStyleSheet(cache_button_style)
        self.btn_verbose.setStyleSheet(verbose_button_style)
        self.btn_test_projects.setStyleSheet(verbose_button_style)
        self.btn_save_profile.setStyleSheet(profile_button_style)
        self.btn_load_profile.setStyleSheet(profile_button_style)
        self.btn_extract_profile.setStyleSheet(profile_button_style)
        self.btn_discover_projects.setStyleSheet(profile_button_style)
        
        left.addWidget(self.btn_refresh)
        left.addWidget(self.btn_clear_cache)
        left.addWidget(self.btn_verbose)
        left.addWidget(self.btn_test_projects)
        
        # Add separator label
        profile_label = QLabel("📋 Extraction Profiles")
        profile_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        left.addWidget(profile_label)
        
        left.addWidget(self.btn_save_profile)
        left.addWidget(self.btn_load_profile)
        left.addWidget(self.btn_extract_profile)
        left.addWidget(self.btn_discover_projects)
        
        left.addWidget(self.btn_open)

        left.addWidget(QLabel("📐 Revit files (ACC)"))
        self.listbox = QListWidget()
        self.listbox.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        left.addWidget(self.listbox, 1)
        left.addWidget(QLabel("📋 Log"))
        self.log = QTextEdit(); self.log.setReadOnly(True); left.addWidget(self.log, 2)

        self.viewer = QWebEngineView()
        
        # Use custom page to capture console messages
        custom_page = ConsoleLoggingPage(self.viewer)
        custom_page.console_message.connect(self._log)
        self.viewer.setPage(custom_page)
        
        # Setup download handling
        profile = self.viewer.page().profile()
        profile.downloadRequested.connect(self._handle_download)
        
        right.addWidget(self.viewer, 1)

        self.btn_refresh.clicked.connect(self.refresh_revits)
        self.btn_clear_cache.clicked.connect(self.clear_cache_and_refresh)
        self.btn_open.clicked.connect(self.open_viewer)
        self.btn_verbose.clicked.connect(self.toggle_verbose)
        self.btn_test_projects.clicked.connect(self.test_multi_project_access)
        self.btn_save_profile.clicked.connect(self.save_profile)
        self.btn_load_profile.clicked.connect(self.load_profile)
        self.btn_extract_profile.clicked.connect(self.extract_profile)
        self.btn_discover_projects.clicked.connect(self.discover_multi_project_files)
        self.listbox.currentRowChanged.connect(self._on_select)

        self.btn_refresh.setShortcut("F5")
        self.btn_open.setShortcut("F7")

        self._log("🎯 Enhanced Revit Viewer Ready!")
        self._log("✨ Features: Cached Search → Enhanced Viewer → Browser Downloads → Extraction Profiles")
        self._log(f"💾 Cache: F5 uses cache ({self.cache_max_age_hours}h), Clear Cache forces fresh search")
        self._log("📥 Files: Browser downloads go to your Downloads folder")
        self._log("📋 Profiles: Save/Load extraction profiles for recurring audits")
        self._log(f"⚙️  Settings: Extraction delay = {self.extraction_delay_seconds}s, Max retries = {self.max_retries}")
        self._log("")
        self._log("💡 Quick Start:")
        self._log("   1. Search for files (F5) OR Discover Multi-Project Files")
        self._log("   2. Select specific files (Ctrl+Click)")
        self._log("   3. Save Selection as Profile")
        self._log("   4. Load Profile or Extract directly")
        self._log("   🔍 Use 'Test Multi-Project Access' button to debug project access")
        
        # Load cache on startup
        self._load_cache_if_valid()

    def test_multi_project_access(self):
        """Test access to multiple projects - debug function"""
        self._log("🔍 Testing multi-project access...")
        try:
            hubs = get_hubs(self.token)
            self._log(f"✅ Found {len(hubs)} hubs")
            
            for hub in hubs:
                self._log(f"  Hub: {hub['name']} ({hub['id']})")
                projects = get_projects(self.token, hub['id'])
                self._log(f"    Projects: {len(projects)}")
                
                for i, project in enumerate(projects[:3]):  # Test first 3 projects
                    self._log(f"    {i+1}. {project['name']} ({project['id']})")
                    # Test if we can access the project
                    try:
                        test_files = self._fetch_project_revit_files(project['id'], hub['id'])
                        self._log(f"       Access: ✅ ({len(test_files)} files)")
                    except Exception as e:
                        self._log(f"       Access: ❌ {e}")
                        
                if len(projects) > 3:
                    self._log(f"    ... and {len(projects) - 3} more projects")
                    
        except Exception as e:
            self._log(f"❌ Multi-project test failed: {e}")
            import traceback
            self._log(f"Full traceback: {traceback.format_exc()}")

    def _update_files(self, revits):
        self.revits = revits; self.listbox.clear()
        for f in revits: self.listbox.addItem(f"📐 {f['full_path']}")
        
        # Show cache status
        cache_status = ""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                cache_time = datetime.fromisoformat(cache_data['timestamp'])
                age_hours = (datetime.now() - cache_time).total_seconds() / 3600
                cache_status = f" (cached {age_hours:.1f}h ago)"
            except:
                cache_status = " (cache error)"
        
        self._log(f"🎯 Found {len(revits)} file(s){cache_status}. Select one to view.")

    def _log(self, s): 
        self.log.append(s)
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def toggle_verbose(self):
        """Toggle verbose debug logging"""
        self.verbose_logging = not self.verbose_logging
        if self.verbose_logging:
            self.btn_verbose.setText("🐛 Debug Logging: ON")
            self._log("✅ Verbose logging enabled - will show first 100 elements during extraction")
        else:
            self.btn_verbose.setText("🐛 Debug Logging: OFF")
            self._log("🔇 Verbose logging disabled - minimal output during extraction")

    def refresh_revits(self):
        # Try loading from cache first
        if self._load_cache_if_valid():
            return
        
        # Cache not available or expired, do fresh search
        self._log("⏳ Cache expired or not found. Searching for Revit files...")
        self.btn_refresh.setEnabled(False)
        self.btn_clear_cache.setEnabled(False)
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def clear_cache_and_refresh(self):
        """Clear cache and force fresh search"""
        self._log("🗑️ Clearing cache and forcing fresh search...")
        try:
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
                self._log("✅ Cache cleared")
        except Exception as e:
            self._log(f"⚠️ Cache clear error: {e}")
        
        # Force fresh search
        self.btn_refresh.setEnabled(False)
        self.btn_clear_cache.setEnabled(False)
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            root = get_root_folder(HUB_ID, PROJECT_ID, self.token)
            revits = find_revit_files_concurrent(self.token, PROJECT_ID, root, progress_callback=self.log_message.emit)
            
            # Save to cache
            self._save_cache(revits)
            
            self.files_found.emit(revits)
        except Exception as e:
            self.log_message.emit(f"❌ Search Error: {e}")
        finally:
            self.btn_refresh.setEnabled(True)
            self.btn_clear_cache.setEnabled(True)

    def _load_cache_if_valid(self):
        """Load files from cache if available and not expired"""
        try:
            if not os.path.exists(self.cache_file):
                self._log("📂 No cache file found")
                return False
                
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                
            # Check cache age
            cache_time = datetime.fromisoformat(cache_data['timestamp'])
            age_hours = (datetime.now() - cache_time).total_seconds() / 3600
            
            if age_hours > self.cache_max_age_hours:
                self._log(f"⏰ Cache expired ({age_hours:.1f} hours old, max {self.cache_max_age_hours})")
                return False
                
            # Cache is valid, load it
            revits = cache_data['files']
            self._log(f"💾 Loaded {len(revits)} files from cache ({age_hours:.1f}h old)")
            self.files_found.emit(revits)
            return True
            
        except Exception as e:
            self._log(f"⚠️ Cache load error: {e}")
            return False
            
    def _save_cache(self, revits):
        """Save search results to cache"""
        try:
            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'project_id': PROJECT_ID,
                'hub_id': HUB_ID,
                'files': revits,
                'count': len(revits)
            }
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
                
            self._log(f"💾 Cached {len(revits)} files to {self.cache_file}")
            
        except Exception as e:
            self._log(f"⚠️ Cache save error: {e}")

    def _on_select(self, row):
        self.selected = self.revits[row] if 0 <= row < len(self.revits) else None
        if self.selected:
            self._log(f"📂 Selected: {self.selected['name']}")

    def _handle_download(self, download: QWebEngineDownloadRequest):
        """Handle browser download requests from the viewer"""
        try:
            suggested_name = download.downloadFileName()
            
            # Get Downloads folder
            downloads_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            if not downloads_path:
                downloads_path = os.path.expanduser("~/Downloads")
            
            # Full path for the file
            save_path = os.path.join(downloads_path, suggested_name)
            
            # If file exists, add number
            base, ext = os.path.splitext(save_path)
            counter = 1
            while os.path.exists(save_path):
                save_path = f"{base}_{counter}{ext}"
                counter += 1
            
            download.setDownloadFileName(save_path)
            download.accept()
            
            self._log(f"💾 Downloading: {suggested_name}")
            self._log(f"📁 Save location: {save_path}")
            
            # Connect to finished signal
            download.isFinishedChanged.connect(
                lambda: self._download_finished(download, save_path)
            )
            
        except Exception as e:
            self._log(f"❌ Download setup error: {e}")
    
    def _download_finished(self, download: QWebEngineDownloadRequest, path: str):
        """Called when download completes"""
        if download.isFinished():
            if download.state() == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
                self._log(f"✅ Download complete: {os.path.basename(path)}")
                self._log(f"📂 Open folder: {os.path.dirname(path)}")
                
                # Ask if user wants to open the folder
                reply = QMessageBox.question(
                    self,
                    "Download Complete",
                    f"File saved successfully!\n\n{os.path.basename(path)}\n\nOpen Downloads folder?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    # Open Downloads folder in file explorer
                    if sys.platform == 'win32':
                        os.startfile(os.path.dirname(path))
                    elif sys.platform == 'darwin':
                        os.system(f'open "{os.path.dirname(path)}"')
                    else:
                        os.system(f'xdg-open "{os.path.dirname(path)}"')
            else:
                self._log(f"❌ Download failed: {os.path.basename(path)}")
                QMessageBox.warning(self, "Download Failed", f"Failed to download {os.path.basename(path)}")

    def open_viewer(self):
        if not self.selected:
            QMessageBox.warning(self, "Select File", "Please select a Revit file first."); return
        
        self._log("🚀 Loading enhanced viewer with extraction capabilities...")
        try:
            enc = encode_urn(self.selected['version_urn'])
            html = build_enhanced_viewer_html(enc, self.token, self.selected['name'], self.verbose_logging, self.extraction_delay_seconds)
            self.viewer.setHtml(html, QUrl("https://developer.api.autodesk.com/"))
            self._log("✅ Enhanced viewer loaded! Watch for extraction panel after model loads.")
            self._log("💡 Panel appears in top-right corner with extraction buttons.")
            self._log("📥 Downloaded files will appear in your browser's Downloads folder.")
            
        except Exception as e:
            self._log(f"❌ Viewer error: {e}")
    
    # ===== PROFILE MANAGEMENT =====
    
    def save_profile(self):
        """Save currently selected files as an extraction profile"""
        # Get currently selected files
        selected_indices = [i for i in range(self.listbox.count()) 
                           if self.listbox.item(i).isSelected()]
        
        if not selected_indices:
            QMessageBox.warning(self, "No Selection", "Please select at least one file to save as a profile.")
            return
        
        selected_files = [self.revits[i] for i in selected_indices]
        
        # Check if files are from multiple projects
        projects_in_selection = set()
        for file_info in selected_files:
            if 'project_id' in file_info:
                projects_in_selection.add((file_info['project_id'], file_info.get('project_name', 'Unknown')))
        
        if len(projects_in_selection) > 1:
            # Multi-project selection
            self._save_multi_project_selection_profile(selected_files, projects_in_selection)
        else:
            # Single project selection
            self._save_single_project_selection_profile(selected_files)
    
    def _save_single_project_selection_profile(self, selected_files):
        """Save selected files from single project"""
        # Get profile name from user
        profile_name, ok = QInputDialog.getText(
            self, 
            "Save Extraction Profile",
            f"Enter profile name ({len(selected_files)} files selected):"
        )
        
        if not ok or not profile_name:
            return
        
        # Build profile data with single project
        profile_data = {
            'name': profile_name,
            'created': datetime.now().isoformat(),
            'version': 2,  # Version 2 supports multi-project
            'projects': [{
                'project_id': selected_files[0].get('project_id', PROJECT_ID),
                'project_name': selected_files[0].get('project_name', 'Current Project'),
                'hub_id': selected_files[0].get('hub_id', HUB_ID),
                'enabled': True,
                'files': selected_files
            }]
        }
        
        # Save to file
        self._save_profile_to_file(profile_name, profile_data)
    
    def _save_multi_project_selection_profile(self, selected_files, projects_in_selection):
        """Save selected files from multiple projects"""
        # Get profile name from user
        profile_name, ok = QInputDialog.getText(
            self, 
            "Save Multi-Project Profile",
            f"Enter profile name ({len(selected_files)} files from {len(projects_in_selection)} projects):"
        )
        
        if not ok or not profile_name:
            return
        
        # Group selected files by project
        files_by_project = {}
        for file_info in selected_files:
            project_id = file_info.get('project_id', PROJECT_ID)
            if project_id not in files_by_project:
                files_by_project[project_id] = {
                    'project_id': project_id,
                    'project_name': file_info.get('project_name', 'Unknown Project'),
                    'hub_id': file_info.get('hub_id', HUB_ID),
                    'enabled': True,
                    'files': []
                }
            files_by_project[project_id]['files'].append(file_info)
        
        # Build profile data
        profile_data = {
            'name': profile_name,
            'created': datetime.now().isoformat(),
            'version': 2,  # Multi-project version
            'projects': list(files_by_project.values())
        }
        
        # Save to file
        self._save_profile_to_file(profile_name, profile_data)
        
        # Log summary
        project_summary = "\n".join(
            f"  • {p['project_name']}: {len(p['files'])} files"
            for p in profile_data['projects']
        )
        self._log(f"✅ Multi-project profile created from selection:")
        self._log(project_summary)
    
    def discover_multi_project_files(self):
        """Discover and display files from multiple projects (does not save profile)"""
        # Show project selector dialog
        dialog = ProjectSelectorDialog(self.token, self)
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.show()
        
        # Wait for dialog to close
        while dialog.isVisible():
            QApplication.processEvents()
            time.sleep(0.1)
        
        selected_projects = dialog.selected_projects
        
        if not selected_projects:
            self._log("❌ No projects selected")
            return
        
        self._log(f"✅ {len(selected_projects)} project(s) selected for file discovery")
        
        # Build multi-project file list (but don't save as profile yet)
        self._log("📥 Fetching files from selected projects...")
        all_discovered_files = []
        
        progress = QProgressDialog("Discovering project files...", "Cancel", 0, len(selected_projects), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        
        for idx, project in enumerate(selected_projects):
            progress.setValue(idx)
            progress.setLabelText(f"Discovering: {project['name']}...\n(Project {idx+1} of {len(selected_projects)})")
            QApplication.processEvents()
            
            if progress.wasCanceled():
                self._log("⚠️ File discovery cancelled by user")
                break
            
            self._log(f"📂 Scanning project: {project['name']}")
            self._log(f"   Project ID: {project['id']}")
            self._log(f"   Hub ID: {project['hub_id']}")
            
            # Fetch Revit files for this project
            try:
                project_files = self._fetch_project_revit_files(project['id'], project['hub_id'], progress)
                
                # Add project context to each file
                for file_info in project_files:
                    file_info['project_name'] = project['name']
                    file_info['project_id'] = project['id']
                    file_info['hub_id'] = project['hub_id']
                
                all_discovered_files.extend(project_files)
                
                self._log(f"  ✓ {project['name']}: {len(project_files)} Revit files")
                if len(project_files) > 0:
                    # Log first few files as examples
                    for i, file_info in enumerate(project_files[:3]):
                        self._log(f"    - {file_info['name']}")
                    if len(project_files) > 3:
                        self._log(f"    ... and {len(project_files) - 3} more files")
                        
            except Exception as e:
                self._log(f"  ❌ {project['name']}: Error - {e}")
                import traceback
                self._log(f"  Full error: {traceback.format_exc()}")
        
        progress.setValue(len(selected_projects))
        progress.close()
        
        # Update the main file list with discovered files
        self.revits = all_discovered_files
        self.listbox.clear()
        
        # Populate the listbox with discovered files (but don't select them)
        for file_info in all_discovered_files:
            project_prefix = f"[{file_info['project_name']}] " if 'project_name' in file_info else ""
            display_text = f"📐 {project_prefix}{file_info.get('full_path', file_info['name'])}"
            self.listbox.addItem(display_text)
        
        total_files = len(all_discovered_files)
        unique_projects = len(set(f.get('project_name', '') for f in all_discovered_files))
        
        self._log(f"✅ Discovery complete: {total_files} files found across {unique_projects} projects")
        self._log("💡 Now use Ctrl+Click to select specific files, then 'Save Selection as Profile'")
        
        QMessageBox.information(
            self,
            "Multi-Project Discovery Complete",
            f"Found {total_files} Revit files across {unique_projects} projects.\n\n"
            f"Files are now displayed in the list.\n\n"
            f"Next steps:\n"
            f"1. Use Ctrl+Click to select specific files you want\n"
            f"2. Click 'Save Selection as Profile' to save your selection\n"
            f"3. Or click 'Extract Profile' to process all visible files"
        )
    
    def _save_profile_to_file(self, profile_name, profile_data):
        """Save profile data to JSON file"""
        profile_filename = f"{profile_name.replace(' ', '_')}.json"
        profile_path = os.path.join(self.profiles_dir, profile_filename)
        
        try:
            with open(profile_path, 'w', encoding='utf-8') as f:
                json.dump(profile_data, f, indent=2, ensure_ascii=False)
            
            total_files = sum(len(p['files']) for p in profile_data['projects'])
            self._log(f"✅ Profile saved: {profile_name}")
            self._log(f"📁 Location: {profile_path}")
            self._log(f"📊 {len(profile_data['projects'])} projects, {total_files} files")
            
            QMessageBox.information(
                self,
                "Profile Saved",
                f"Profile '{profile_name}' saved successfully!\n\n"
                f"Projects: {len(profile_data['projects'])}\n"
                f"Total files: {total_files}"
            )
            
        except Exception as e:
            self._log(f"❌ Error saving profile: {e}")
            QMessageBox.critical(self, "Save Error", f"Failed to save profile: {e}")
    
    def _fetch_project_revit_files(self, project_id, hub_id, progress=None):
        """Fetch all Revit files from a specific project"""
        revit_files = []
        
        try:
            # Get project's top folders
            self._log(f"   Getting top folders for project {project_id}")
            self._log(f"   Hub ID: {hub_id}")
            self._log(f"   Using token: {self.token[:20]}...")
            
            url = f"{BASE_URL}/project/v1/hubs/{hub_id}/projects/{project_id}/topFolders"
            self._log(f"   API URL: {url}")
            
            response = make_request_with_retry(
                session.get,
                url,
                headers={'Authorization': f'Bearer {self.token}'},
                timeout=HTTP_TIMEOUT
            )
            
            self._log(f"   API Response Status: {response.status_code}")
            
            if response.status_code != 200:
                self._log(f"   API Response Text: {response.text}")
                
            response.raise_for_status()
            folders = response.json().get('data', [])
            
            self._log(f"   Found {len(folders)} top-level folders")
            
            # Log folder names for debugging
            if folders:
                for folder in folders:
                    folder_name = folder.get('attributes', {}).get('displayName', 'Unknown')
                    self._log(f"     - {folder_name}")
            
            # Search recursively for Revit files
            for folder in folders:
                if progress and progress.wasCanceled():
                    self._log(f"   Cancelled during folder scan")
                    break
                    
                folder_id = folder['id']
                folder_name = folder.get('attributes', {}).get('displayName', 'Unknown')
                
                # Skip non-Revit folders to speed up scanning
                if not is_likely_revit_folder(folder_name):
                    self._log(f"   Skipping folder: {folder_name} (non-Revit)")
                    continue
                    
                self._log(f"   Scanning folder: {folder_name}")
                QApplication.processEvents()  # Keep UI responsive
                
                self._search_folder_for_revits(project_id, folder_id, revit_files, progress, folder_name)
            
            self._log(f"   Total files found in project: {len(revit_files)}")
            
        except Exception as e:
            self._log(f"   ❌ Error fetching files from project {project_id}: {e}")
            # Log more details for debugging
            self._log(f"   Hub ID: {hub_id}")
            self._log(f"   Project ID: {project_id}")
            import traceback
            self._log(f"   Full traceback: {traceback.format_exc()}")
            print(f"Error fetching files from project {project_id}: {e}")
        
        return revit_files
    
    def _search_folder_for_revits(self, project_id, folder_id, results, progress=None, folder_path="", depth=0):
        """Recursively search folder for Revit files"""
        # Limit recursion depth to prevent infinite loops
        if depth > 10:
            self._log(f"     ⚠️ Max folder depth reached (10 levels) in {folder_path}")
            return
            
        try:
            if progress and progress.wasCanceled():
                return
                
            response = make_request_with_retry(
                session.get,
                f"{BASE_URL}/data/v1/projects/{project_id}/folders/{folder_id}/contents",
                headers={'Authorization': f'Bearer {self.token}'},
                timeout=HTTP_TIMEOUT
            )
            response.raise_for_status()
            items = response.json().get('data', [])
            
            # Count files found
            rvt_count = sum(1 for item in items 
                          if item.get('type') == 'items' 
                          and item.get('attributes', {}).get('displayName', '').lower().endswith('.rvt'))
            
            if rvt_count > 0:
                self._log(f"     Found {rvt_count} .rvt file(s) in {folder_path}")
                QApplication.processEvents()
            
            for item in items:
                if progress and progress.wasCanceled():
                    return
                    
                item_type = item.get('type', '')
                
                # If it's a folder, search recursively
                if item_type == 'folders':
                    sub_folder_name = item.get('attributes', {}).get('displayName', 'Unknown')
                    sub_folder_path = f"{folder_path}/{sub_folder_name}" if folder_path else sub_folder_name
                    
                    # Skip non-Revit folders
                    if is_likely_revit_folder(sub_folder_name):
                        self._search_folder_for_revits(project_id, item['id'], results, progress, sub_folder_path, depth + 1)
                
                # If it's a Revit file, add it
                elif item_type == 'items':
                    attrs = item.get('attributes', {})
                    display_name = attrs.get('displayName', '')
                    
                    if display_name.lower().endswith('.rvt'):
                        # Get version URN using the proper method
                        try:
                            version_urn = get_latest_version_urn(project_id, item['id'], self.token)
                            
                            if version_urn:
                                file_info = {
                                    'name': display_name,
                                    'path': folder_path,
                                    'full_path': f"{folder_path}/{display_name}" if folder_path else display_name,
                                    'item_id': item['id'],
                                    'version_urn': version_urn
                                }
                                results.append(file_info)
                                self._log(f"     ✅ Added: {file_info['full_path']}")
                            else:
                                self._log(f"     ⚠️ No version found for: {display_name}")
                        except Exception as e:
                            self._log(f"     ❌ Error getting version for {display_name}: {e}")
        
        except Exception as e:
            self._log(f"     ❌ Error searching folder {folder_id}: {e}")
            print(f"Error searching folder {folder_id}: {e}")
    
    def save_profile_OLD(self):
        """DEPRECATED: Old single-project save method"""
        selected_indices = [i for i in range(self.listbox.count()) 
                           if self.listbox.item(i).isSelected()]
        
        if not selected_indices:
            QMessageBox.warning(self, "No Selection", "Please select at least one file to save as a profile.")
            return
        
        # Get profile name from user
        profile_name, ok = QInputDialog.getText(
            self, 
            "Save Extraction Profile",
            f"Enter profile name ({len(selected_indices)} files selected):"
        )
        
        if not ok or not profile_name:
            return
        
        # Build profile data
        selected_files = [self.revits[i] for i in selected_indices]
        profile_data = {
            'name': profile_name,
            'created': datetime.now().isoformat(),
            'project_id': PROJECT_ID,
            'hub_id': HUB_ID,
            'file_count': len(selected_files),
            'files': selected_files
        }
        
        # Save to file
        profile_filename = f"{profile_name.replace(' ', '_')}.json"
        profile_path = os.path.join(self.profiles_dir, profile_filename)
        
        try:
            with open(profile_path, 'w', encoding='utf-8') as f:
                json.dump(profile_data, f, indent=2, ensure_ascii=False)
            
            self._log(f"✅ Profile saved: {profile_name} ({len(selected_files)} files)")
            self._log(f"📁 Location: {profile_path}")
            QMessageBox.information(
                self,
                "Profile Saved",
                f"Profile '{profile_name}' saved successfully!\n\n{len(selected_files)} files included."
            )
            
        except Exception as e:
            self._log(f"❌ Error saving profile: {e}")
            QMessageBox.critical(self, "Save Error", f"Failed to save profile: {e}")
    
    def load_profile(self):
        """Load an extraction profile and select those files"""
        # Get list of available profiles
        if not os.path.exists(self.profiles_dir):
            QMessageBox.information(self, "No Profiles", "No profiles found. Create one first by selecting files and clicking 'Save Selection as Profile'.")
            return
        
        profile_files = [f for f in os.listdir(self.profiles_dir) if f.endswith('.json')]
        
        if not profile_files:
            QMessageBox.information(self, "No Profiles", "No profiles found. Create one first by selecting files and clicking 'Save Selection as Profile'.")
            return
        
        # Let user choose profile
        profile_names = [f.replace('.json', '').replace('_', ' ') for f in profile_files]
        profile_name, ok = QInputDialog.getItem(
            self,
            "Load Extraction Profile",
            "Select a profile to load:",
            profile_names,
            0,
            False
        )
        
        if not ok:
            return
        
        # Load profile
        profile_filename = f"{profile_name.replace(' ', '_')}.json"
        profile_path = os.path.join(self.profiles_dir, profile_filename)
        
        try:
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile_data = json.load(f)
            
            self.current_profile = profile_data
            
            # Check if multi-project profile (version 2)
            if profile_data.get('version') == 2:
                self._load_multi_project_profile(profile_data)
            else:
                self._load_single_project_profile(profile_data)
            
        except Exception as e:
            self._log(f"❌ Error loading profile: {e}")
            QMessageBox.critical(self, "Load Error", f"Failed to load profile: {e}")
    
    def _load_single_project_profile(self, profile_data):
        """Load old-style single-project profile"""
        # Clear current selection
        self.listbox.clearSelection()
        
        # Select files from profile
        profile_item_ids = {item['item_id'] for item in profile_data['files']}
        selected_count = 0
        
        for i, revit_file in enumerate(self.revits):
            if revit_file['item_id'] in profile_item_ids:
                self.listbox.item(i).setSelected(True)
                selected_count += 1
        
        self._log(f"✅ Profile loaded: {profile_data['name']}")
        self._log(f"📊 Selected {selected_count} of {profile_data['file_count']} files from profile")
        
        if selected_count < profile_data['file_count']:
            self._log(f"⚠️ Note: {profile_data['file_count'] - selected_count} files from profile not found in current file list")
        
        QMessageBox.information(
            self,
            "Profile Loaded",
            f"Profile '{profile_data['name']}' loaded!\n\n{selected_count} files selected."
        )
    
    def _load_multi_project_profile(self, profile_data):
        """Load new multi-project profile"""
        total_files = sum(len(p['files']) for p in profile_data['projects'])
        enabled_projects = [p for p in profile_data['projects'] if p.get('enabled', True)]
        
        self._log(f"✅ Multi-project profile loaded: {profile_data['name']}")
        self._log(f"📊 {len(enabled_projects)} projects, {total_files} total files")
        
        # Collect all files from all enabled projects into the main file list
        all_profile_files = []
        for project in enabled_projects:
            for file_info in project['files']:
                # Add project context to the file info
                enhanced_file = file_info.copy()
                enhanced_file['project_name'] = project['project_name']
                enhanced_file['project_id'] = project['project_id']
                enhanced_file['hub_id'] = project['hub_id']
                all_profile_files.append(enhanced_file)
        
        # Update the main file list with profile files
        self.revits = all_profile_files
        self.listbox.clear()
        
        # Populate the listbox with multi-project files
        for file_info in all_profile_files:
            project_prefix = f"[{file_info['project_name']}] " if 'project_name' in file_info else ""
            display_text = f"📐 {project_prefix}{file_info.get('full_path', file_info['name'])}"
            self.listbox.addItem(display_text)
        
        # Select all files from the profile
        for i in range(self.listbox.count()):
            self.listbox.item(i).setSelected(True)
        
        self._log(f"📋 Populated file list with {len(all_profile_files)} files from {len(enabled_projects)} projects")
        
        # Show summary
        project_summary = "\n".join(
            f"  • {p['project_name']}: {len(p['files'])} files"
            for p in enabled_projects
        )
        
        QMessageBox.information(
            self,
            "Multi-Project Profile Loaded",
            f"Profile: {profile_data['name']}\n\n"
            f"Projects ({len(enabled_projects)}):\n{project_summary}\n\n"
            f"Total files: {total_files}\n\n"
            f"Files are now displayed in the list and pre-selected.\n"
            f"You can view individual files or use 'Extract Profile' for batch processing."
        )
    
    def extract_profile(self):
        """Extract all files in the current profile or selection"""
        if not self.current_profile:
            # Fall back to manual selection
            selected_indices = [i for i in range(self.listbox.count()) 
                               if self.listbox.item(i).isSelected()]
            
            if not selected_indices:
                QMessageBox.warning(
                    self, 
                    "No Selection", 
                    "Please load a profile or select files first."
                )
                return
            
            self._extract_manual_selection(selected_indices)
            return
        
        # Check if multi-project profile
        if self.current_profile.get('version') == 2:
            self._extract_multi_project_profile()
        else:
            self._extract_single_project_profile()
    
    def _extract_manual_selection(self, selected_indices):
        """Extract manually selected files from current project"""
        # Confirm extraction
        reply = QMessageBox.question(
            self,
            "Batch Extraction",
            f"Extract {len(selected_indices)} models?\n\nThis will:\n"
            f"• Load each model in the viewer\n"
            f"• Extract all elements\n"
            f"• Combine into single CSV\n\n"
            f"Estimated time: {len(selected_indices) * 40} seconds (~40s per model)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Start batch extraction
        self._log(f"⚡ Starting batch extraction of {len(selected_indices)} models...")
        self.batch_extraction_results = []
        self.batch_successful = []
        self.batch_failed = []
        self.batch_start_time = datetime.now()
        
        # Prepare file list
        files_to_extract = [self.revits[i] for i in selected_indices]
        
        self._start_batch_extraction(files_to_extract)
    
    def _extract_single_project_profile(self):
        """Extract files from old single-project profile"""
        profile_files = self.current_profile['files']
        
        reply = QMessageBox.question(
            self,
            "Extract Profile",
            f"Extract {len(profile_files)} models from profile?\n\n"
            f"Profile: {self.current_profile['name']}\n"
            f"Estimated time: {len(profile_files) * 40} seconds",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self._log(f"⚡ Starting profile extraction: {self.current_profile['name']}")
        self.batch_extraction_results = []
        self.batch_successful = []
        self.batch_failed = []
        self.batch_start_time = datetime.now()
        
        self._start_batch_extraction(profile_files)
    
    def _extract_multi_project_profile(self):
        """Extract files from multi-project profile"""
        enabled_projects = [p for p in self.current_profile['projects'] if p.get('enabled', True)]
        total_files = sum(len(p['files']) for p in enabled_projects)
        
        reply = QMessageBox.question(
            self,
            "Multi-Project Extraction",
            f"Extract from {len(enabled_projects)} projects?\n\n"
            f"Profile: {self.current_profile['name']}\n"
            f"Total models: {total_files}\n"
            f"Estimated time: {total_files * 40} seconds (~{total_files * 40 // 60} minutes)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self._log(f"⚡ Starting multi-project extraction: {self.current_profile['name']}")
        self._log(f"📦 {len(enabled_projects)} projects, {total_files} total files")
        
        self.batch_extraction_results = []
        self.batch_successful = []
        self.batch_failed = []
        self.batch_start_time = datetime.now()
        
        # Flatten all files from all enabled projects
        all_files = []
        for project in enabled_projects:
            for file in project['files']:
                # Add project context to file
                file_with_context = file.copy()
                file_with_context['project_name'] = project['project_name']
                file_with_context['project_id'] = project['project_id']
                all_files.append(file_with_context)
        
        self._start_batch_extraction(all_files)
    
    def _start_batch_extraction(self, files_to_extract):
        """Start the batch extraction process"""
        # Disable buttons during extraction
        self.btn_extract_profile.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        self.btn_open.setEnabled(False)
        
        # Create progress dialog
        self.progress_dialog = QProgressDialog(
            "Extracting models...",
            "Cancel",
            0,
            len(files_to_extract),
            self
        )
        self.progress_dialog.setWindowTitle("Batch Extraction")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.show()
        
        # Start extraction
        self.current_batch_files = files_to_extract
        self.current_batch_index = 0
        self.current_retry_count = 0
        # max_retries already defined in __init__ (self.max_retries)
        self._extract_next_model()
    
    def _extract_next_model(self):
        """Extract the next model in the batch"""
        if self.current_batch_index >= len(self.current_batch_files):
            # Batch complete
            self._finish_batch_extraction()
            return
        
        if hasattr(self, 'progress_dialog') and self.progress_dialog.wasCanceled():
            self._cancel_batch_extraction()
            return
        
        # Get next file
        file_info = self.current_batch_files[self.current_batch_index]
        
        # Add project context to log message if available
        project_context = f" [{file_info.get('project_name', '')}]" if 'project_name' in file_info else ""
        
        self._log(f"📂 Extracting model {self.current_batch_index + 1}/{len(self.current_batch_files)}: {file_info['name']}{project_context}")
        self._log(f"⏱️  Using extraction delay: {self.extraction_delay_seconds}s, max retries: {self.max_retries}")
        self.progress_dialog.setValue(self.current_batch_index)
        self.progress_dialog.setLabelText(f"Extracting: {file_info['name']}{project_context}\n({self.current_batch_index + 1} of {len(self.current_batch_files)})")
        
        # Load model in viewer and extract
        # Note: We'll use a JavaScript callback to get results
        try:
            enc = encode_urn(file_info['version_urn'])
            html = build_enhanced_viewer_html(enc, self.token, file_info['name'], self.verbose_logging, self.extraction_delay_seconds)
            
            # Inject auto-extraction flag
            auto_extract_js = """
            <script>
            window.autoExtractMode = true;
            </script>
            """
            
            html_with_auto = html.replace('</body>', auto_extract_js + '</body>')
            self.viewer.setHtml(html_with_auto, QUrl("https://developer.api.autodesk.com/"))
            
            # Set timer to check for extraction completion
            # Model load time varies, but GEOMETRY_LOADED_EVENT triggers when ready, then 2s delay before extraction
            # Start checking after a reasonable time for most models
            from PySide6.QtCore import QTimer
            self.current_retry_count = 0  # Reset retry counter for new model
            QTimer.singleShot(7000, lambda: self._check_extraction_complete(file_info))  # Check after 7 seconds (allows for slow model loads + 2s extraction delay)
            
        except Exception as e:
            self._log(f"❌ Error loading model: {e}")
            self.current_batch_index += 1
            self._extract_next_model()
    
    def _check_extraction_complete(self, file_info):
        """Check if extraction is complete and retrieve results"""
        # Execute JavaScript to check for both results and errors
        self.viewer.page().runJavaScript(
            """
            (function() {
                if (window.extractionError) {
                    return JSON.stringify({error: window.extractionError});
                }
                if (window.extractionComplete && window.getExtractionResults) {
                    return JSON.stringify({results: window.getExtractionResults()});
                }
                return null;
            })()
            """,
            lambda response: self._handle_extraction_results(response, file_info)
        )
    
    def _handle_extraction_results(self, results_json, file_info):
        """Handle extraction results from JavaScript"""
        if results_json:
            try:
                response = json.loads(results_json)
                
                # Check if there was an error
                if 'error' in response:
                    error_msg = response['error']
                    self.batch_failed.append(file_info['name'])
                    
                    # Check for fatal errors that shouldn't be retried
                    fatal_errors = [
                        'Instance tree not available',
                        'No nodes found in model',
                        'Model not ready',
                        'CORS policy',
                        'blocked by CORS',
                        'Access to XMLHttpRequest',
                        'does not have HTTP ok status'
                    ]
                    
                    is_fatal = any(fatal_error in error_msg for fatal_error in fatal_errors)
                    
                    if is_fatal:
                        self._log(f"❌ FATAL ERROR in {file_info['name']}: {error_msg}")
                        self._log(f"   Skipping retries - this error cannot be resolved by waiting")
                        # Move to next model immediately
                        self.current_batch_index += 1
                        self._extract_next_model()
                        return
                    else:
                        self._log(f"⚠️ Error in {file_info['name']}: {error_msg}")
                        # Treat as no results, will retry below
                
                # Check if there are results
                elif 'results' in response:
                    results = response['results']
                    
                    # Add project context to each element if available
                    if 'project_name' in file_info:
                        for element in results:
                            element['projectName'] = file_info['project_name']
                    
                    self.batch_extraction_results.extend(results)
                    self.batch_successful.append(file_info['name'])
                    self._log(f"✅ Extracted {len(results)} elements from {file_info['name']}")
                    # Move to next model
                    self.current_batch_index += 1
                    self._extract_next_model()
                    return
                    
            except Exception as e:
                self.batch_failed.append(file_info['name'])
                self._log(f"⚠️ Error parsing results from {file_info['name']}: {e}")
        
        # No results - check if we should retry
        if self.current_retry_count >= self.max_retries:
            self.batch_failed.append(file_info['name'])
            self._log(f"❌ Failed to extract {file_info['name']} after {self.max_retries} retries - skipping")
            self._log(f"   Possible causes: Model load failure or extraction timeout")
            # Move to next model
            self.current_batch_index += 1
            self._extract_next_model()
            return
        
        self.current_retry_count += 1
        self._log(f"⚠️ No results from {file_info['name']} - retrying ({self.current_retry_count}/{self.max_retries})...")
        # Retry after 2 more seconds
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self._check_extraction_complete(file_info))
    
    def _finish_batch_extraction(self):
        """Finish batch extraction and save results"""
        self.progress_dialog.close()
        
        # Calculate elapsed time
        elapsed_time = datetime.now() - self.batch_start_time
        total_seconds = elapsed_time.total_seconds()
        minutes, seconds = divmod(int(total_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        
        if hours > 0:
            time_str = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            time_str = f"{minutes}m {seconds}s"
        else:
            time_str = f"{seconds}s"
        
        # Calculate stats
        total_models = len(self.batch_successful) + len(self.batch_failed)
        success_count = len(self.batch_successful)
        failed_count = len(self.batch_failed)
        
        # Log summary with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._log(f"")
        self._log(f"{'='*60}")
        self._log(f"✅ Batch Complete [{timestamp}]: {success_count}/{total_models} models extracted successfully")
        self._log(f"⏱️  Total extraction time: {time_str}")
        if failed_count > 0:
            self._log(f"❌ Failed models ({failed_count}):")
            for failed_name in self.batch_failed:
                self._log(f"   • {failed_name}")
        self._log(f"📊 Total elements extracted: {len(self.batch_extraction_results)}")
        self._log(f"{'='*60}")
        self._log(f"")
        
        # Re-enable buttons
        self.btn_extract_profile.setEnabled(True)
        self.btn_refresh.setEnabled(True)
        self.btn_open.setEnabled(True)
        
        if len(self.batch_extraction_results) > 0:
            # Save combined CSV with summary dialog
            self._save_batch_csv()
        else:
            QMessageBox.warning(self, "No Results", "No elements were extracted from any models.")
    
    def _cancel_batch_extraction(self):
        """Cancel batch extraction"""
        self._log("⚠️ Batch extraction cancelled by user")
        self.btn_extract_profile.setEnabled(True)
        self.btn_refresh.setEnabled(True)
        self.btn_open.setEnabled(True)
    
    def _save_batch_csv(self):
        """Save batch extraction results to CSV with summary dialog"""
        # Calculate stats
        total_models = len(self.batch_successful) + len(self.batch_failed)
        success_count = len(self.batch_successful)
        failed_count = len(self.batch_failed)
        
        # Calculate elapsed time
        elapsed_time = datetime.now() - self.batch_start_time
        total_seconds = elapsed_time.total_seconds()
        minutes, seconds = divmod(int(total_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        
        if hours > 0:
            time_str = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            time_str = f"{minutes}m {seconds}s"
        else:
            time_str = f"{seconds}s"
        
        # Build summary message
        summary_msg = f"📊 Batch Extraction Summary\n"
        summary_msg += f"{'━' * 40}\n\n"
        summary_msg += f"✅ Successful: {success_count} models\n"
        summary_msg += f"❌ Failed: {failed_count} models\n"
        summary_msg += f"📦 Total Elements: {len(self.batch_extraction_results)}\n"
        summary_msg += f"⏱️  Extraction Time: {time_str}\n\n"
        
        if failed_count > 0:
            summary_msg += f"Failed Models:\n"
            for failed_name in self.batch_failed[:5]:  # Show first 5
                summary_msg += f"  • {failed_name}\n"
            if failed_count > 5:
                summary_msg += f"  ... and {failed_count - 5} more\n"
            summary_msg += f"\n"
        
        summary_msg += f"{'━' * 40}\n"
        summary_msg += f"Save combined CSV file?"
        
        # Show summary dialog with save option
        reply = QMessageBox.question(
            self,
            "Batch Extraction Complete",
            summary_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Get save location
        downloads_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        if not downloads_path:
            downloads_path = os.path.expanduser("~/Downloads")
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        default_filename = f"batch_extract_{timestamp}.csv"
        default_path = os.path.join(downloads_path, default_filename)
        
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Batch Extraction Results",
            default_path,
            "CSV Files (*.csv);;All Files (*.*)"
        )
        
        if not filename:
            return
        
        try:
            # Use UTF-8 with BOM for better Excel compatibility
            with open(filename, 'w', encoding='utf-8-sig', newline='') as f:
                # Write header - 22 columns total (added ProjectName)
                f.write('ProjectName,FileName,ElementId,Discipline,Category,Type,Name,NominalDiameter,BuildingId,Sector,Count,TotalLength,Panel/Rack,Equipment/Tray To,Workset,Conduit excess,Center to End,Bend Radius,Angle,Size,HSM,AH\n')
                
                # Write data
                for element in self.batch_extraction_results:
                    f.write(
                        f'"{element.get("projectName", "")}","{element.get("fileName", "")}","{element.get("elementId", "")}","{element.get("discipline", "")}",'
                        f'"{element.get("revitCategory", "")}","{element.get("revitType", "")}","{element.get("lmvName", "")}",'
                        f'{element.get("nominalDiameter", 0)},"{element.get("buildingId", "")}","{element.get("sector", "")}",'
                        f'{element.get("Count", 1)},{element.get("TotalLength", 0)},'
                        f'"{element.get("panelRack", "")}","{element.get("equipmentTrayTo", "")}","{element.get("workset", "")}",'
                        f'{element.get("conduitExcess", 0)},{element.get("centerToEnd", 0)},{element.get("bendRadius", 0)},'
                        f'{element.get("angle", 0)},"{element.get("size", "")}",'
                        f'{element.get("hsm", 0)},{element.get("ah", 0)}\n'
                    )
            
            self._log(f"✅ Batch CSV saved: {filename}")
            self._log(f"📊 {len(self.batch_extraction_results)} elements saved")
            
            # Ask to open folder
            reply = QMessageBox.question(
                self,
                "File Saved Successfully",
                f"Successfully saved {len(self.batch_extraction_results)} elements!\n\n{os.path.basename(filename)}\n\nOpen folder?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                if sys.platform == 'win32':
                    os.startfile(os.path.dirname(filename))
                elif sys.platform == 'darwin':
                    os.system(f'open "{os.path.dirname(filename)}"')
                else:
                    os.system(f'xdg-open "{os.path.dirname(filename)}"')
                    
        except Exception as e:
            self._log(f"❌ Error saving batch CSV: {e}")
            QMessageBox.critical(self, "Save Error", f"Failed to save CSV: {e}")

# ===== Main =====
def cleanup_and_exit():
    app = QApplication.instance()
    if app: app.quit()
    sys.exit(0)

def signal_handler(signum, frame):
    print(f"\nReceived signal {signum}, shutting down…"); cleanup_and_exit()

if __name__=="__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    try:
        print("=" * 60)
        print("� IES Viewer Audit - Starting with VS Code APS Integration")
        print("=" * 60)
        
        # Try to get token using VS Code credentials with fallback
        print("\n🔐 Authenticating with Autodesk Platform Services...")
        token = get_token_2L()
        
        print("\n✅ Authentication successful!")
        print("✨ Features: VS Code APS credentials, cached file search, enhanced viewer, browser-based downloads")
        print("=" * 60 + "\n")
        
        app = QApplication(sys.argv)
        w = App(token); w.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"\n❌ Startup error: {e}")
        import traceback
        traceback.print_exc()
        cleanup_and_exit()
