# Production Branch: IESViewerAudit.py

## Branch: `production-ies-viewer-audit`

This branch contains the complete production-ready deployment of IESViewerAudit.py with all necessary support files.

## 📦 Files Included

### Core Application (1 file)
- **`IESViewerAudit.py`** (2,170 lines)
  - Complete ACC Revit viewer and extraction application
  - Multi-project support
  - Enhanced 3D viewer with built-in extraction
  - Batch processing with profiles
  - Smart caching system
  - Browser-based downloads

### Dependencies (1 file)
- **`requirements.txt`**
  - Minimal production dependencies
  - `requests>=2.31.0` for HTTP API calls
  - `PySide6>=6.5.0` for Qt GUI framework

### Configuration (1 file)
- **`config_template.py`**
  - Template for production configuration
  - APS credentials setup
  - Application settings
  - Copy to `config.py` and customize

### Documentation (3 files)
- **`README_PRODUCTION.md`** - Overview and features
- **`DEPLOYMENT_GUIDE.md`** - Complete deployment guide
- **`BRANCH_SUMMARY.md`** - This file

### Launch Scripts (2 files)
- **`start_production.bat`** - Windows automated launcher
- **`start_production.sh`** - Linux/macOS automated launcher

## 🎯 Total Files: 8

This is a minimal, focused production branch containing only what's needed to run IESViewerAudit.py in production.

## 🚀 Quick Start

1. **Clone branch:**
   ```bash
   git checkout production-ies-viewer-audit
   ```

2. **Run launcher:**
   ```bash
   # Windows
   start_production.bat
   
   # Linux/macOS  
   ./start_production.sh
   ```

3. **Configure on first run:**
   - Copy `config_template.py` to `config.py`
   - Add your APS credentials
   - Add your ACC project/hub IDs

## ✅ Ready for Production

This branch is:
- ✅ Self-contained
- ✅ Fully documented  
- ✅ Cross-platform
- ✅ Automated setup
- ✅ Production tested
- ✅ Minimal dependencies

No other files from the development repository are needed.