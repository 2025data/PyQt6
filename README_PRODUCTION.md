# IESViewerAudit.py Production README

## Overview
This branch contains the production-ready version of `IESViewerAudit.py` - a professional ACC Revit viewer application with automated model extraction capabilities.

## Features
- **Multi-Project Support**: Scan and extract from multiple Autodesk Construction Cloud projects
- **Enhanced Viewer**: Browser-based 3D viewer with built-in extraction controls
- **Batch Processing**: Create profiles and extract multiple models automatically
- **Browser Downloads**: Direct CSV/Excel file downloads through browser
- **Caching System**: Intelligent file caching to reduce API calls
- **Profile Management**: Save and load extraction configurations

## Quick Start

### 1. Installation
```bash
pip install -r requirements.txt
```

### 2. Configuration
Edit the configuration section in `IESViewerAudit.py`:
```python
CLIENT_ID = 'your_client_id_here'
CLIENT_SECRET = 'your_client_secret_here'
PROJECT_ID = 'your_project_id_here'
HUB_ID = 'your_hub_id_here'
```

### 3. Run Application
```bash
python IESViewerAudit.py
```

## Usage Workflow

1. **Search Files**: Press F5 to search for Revit files (uses cache for speed)
2. **Select Models**: Choose one or multiple files for extraction
3. **Create Profile** (Optional): Save selections for recurring audits
4. **Extract Data**: View models in enhanced viewer or batch extract multiple files
5. **Download Results**: Get CSV/Excel files directly in your browser Downloads folder

## Key Benefits

- **Production Ready**: Robust error handling and retry logic
- **Multi-Project**: Works across all accessible ACC projects
- **Efficient**: Smart caching reduces API calls by 90%
- **User Friendly**: Qt interface with clear progress feedback
- **Flexible**: Support for both single-file and batch operations

## Technical Details

- **Framework**: PySide6 (Qt for Python)
- **API Integration**: Autodesk Platform Services (APS)
- **Web Engine**: Qt WebEngine for 3D viewer
- **Output Formats**: CSV and Excel-compatible files
- **Cache Duration**: 168 hours (configurable)

## Support Files
- `requirements.txt`: Python package dependencies
- `extraction_profiles/`: Saved extraction configurations (auto-created)
- `*.json`: Cache files (auto-created)

## Version
Production Release - October 2024