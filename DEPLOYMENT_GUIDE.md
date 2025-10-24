# IESViewerAudit.py - Production Deployment Guide

## 🚀 Quick Start (5 Minutes)

### 1. Clone or Download
```bash
git clone [repository-url]
cd PyQt6
git checkout production-ies-viewer-audit
```

### 2. Run Setup Script
**Windows:**
```cmd
start_production.bat
```

**Linux/macOS:**
```bash
chmod +x start_production.sh
./start_production.sh
```

The script will:
- Create a virtual environment
- Install dependencies
- Guide you through configuration
- Launch the application

### 3. First-Time Configuration
1. Copy `config_template.py` to `config.py`
2. Update with your Autodesk APS credentials:
   ```python
   APS_CLIENT_ID = 'your_client_id_here'
   APS_CLIENT_SECRET = 'your_client_secret_here'
   ACC_PROJECT_ID = 'b.your-project-id'
   ACC_HUB_ID = 'b.your-hub-id'
   ```

---

## 📋 Complete File List

This production branch contains only the essential files:

### Core Application
- `IESViewerAudit.py` - Main application (2,170 lines)
- `requirements.txt` - Python dependencies
- `config_template.py` - Configuration template

### Documentation
- `README_PRODUCTION.md` - Overview and features
- `DEPLOYMENT_GUIDE.md` - This file
- Inline documentation in source code

### Launch Scripts
- `start_production.bat` - Windows launcher
- `start_production.sh` - Linux/macOS launcher

### Auto-Generated (During Runtime)
- `extraction_profiles/` - Saved extraction configurations
- `revit_files_cache.json` - File cache for faster loading
- `.venv/` - Virtual environment (created by scripts)

---

## 🔧 Manual Installation

If you prefer manual setup:

### 1. Create Virtual Environment
```bash
python -m venv .venv
```

### 2. Activate Environment
**Windows:**
```cmd
.venv\Scripts\activate
```

**Linux/macOS:**
```bash
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Application
```bash
cp config_template.py config.py
# Edit config.py with your credentials
```

### 5. Run Application
```bash
python IESViewerAudit.py
```

---

## 🏢 Production Features

### Multi-Project Support
- Scan files across all accessible ACC projects
- Create profiles spanning multiple projects
- Batch extract from different hubs/projects

### Enhanced 3D Viewer
- Full Autodesk Forge viewer integration
- Interactive model exploration
- Built-in extraction controls

### Batch Processing
- Process 50+ models automatically
- Profile-based recurring audits
- Progress tracking with retry logic

### Smart Caching
- 7-day file cache (configurable)
- 90% reduction in API calls
- Cache invalidation controls

### Professional Output
- CSV and Excel-compatible exports
- Browser downloads (no file dialogs)
- Comprehensive element data

---

## 🔐 Security Configuration

### APS Credentials
Get your credentials from:
1. Visit [Autodesk Platform Services](https://aps.autodesk.com/)
2. Create an app with these scopes:
   - `data:read`
   - `data:write`
   - `viewables:read`
   - `account:read`

### Environment Variables (Alternative)
Instead of `config.py`, you can use environment variables:
```bash
export APS_CLIENT_ID="your_client_id"
export APS_CLIENT_SECRET="your_client_secret"
export ACC_PROJECT_ID="b.your-project-id"
export ACC_HUB_ID="b.your-hub-id"
```

---

## 📊 Usage Examples

### Single File Extraction
1. Launch application
2. Press F5 to search files
3. Select a file
4. Press F7 to open viewer
5. Click "Extract All Elements"
6. Download CSV/Excel

### Batch Processing
1. Search files (F5)
2. Select multiple files (Ctrl+Click)
3. Click "Save Selection as Profile"
4. Click "Extract Profile"
5. Wait for batch completion
6. Download combined results

### Multi-Project Audit
1. Click "Save Selection as Profile"
2. Choose "Multi-Project"
3. Select projects from all hubs
4. Save profile
5. Use "Extract Profile" for batch processing

---

## 🛠️ Troubleshooting

### Common Issues

**"No Python found"**
- Install Python 3.8+ from python.org
- Ensure Python is in your system PATH

**"Failed to install dependencies"**
- Check internet connection
- Try: `pip install --upgrade pip`
- For Qt issues on Linux: `apt-get install python3-dev`

**"Authentication failed"**
- Verify APS credentials in config.py
- Check app scopes in APS console
- Ensure 2-legged OAuth is enabled

**"No files found"**
- Verify PROJECT_ID and HUB_ID are correct
- Check ACC project permissions
- Try "Clear Cache & Refresh"

**"Extraction timeout"**
- Increase EXTRACTION_DELAY_SECONDS
- Increase MAX_RETRIES_PER_MODEL
- Check model file integrity

### Debug Mode
Enable verbose logging:
1. Click "Debug Logging: OFF" → "ON"
2. View detailed console output
3. Check extraction element details

---

## 📈 Performance Tips

### Large Deployments
- Use profiles for recurring audits
- Enable caching (default 7 days)
- Adjust MAX_CONCURRENT_WORKERS based on system

### Network Optimization
- Increase HTTP_TIMEOUT for slow connections
- Use cache aggressively in production
- Batch multiple extractions together

### System Requirements
- **RAM**: 4GB minimum, 8GB recommended
- **CPU**: Multi-core recommended for batch processing
- **Network**: Stable internet for Autodesk API calls
- **Display**: 1920x1080 minimum for viewer

---

## 🚢 Production Checklist

Before deploying in production:

- [ ] APS credentials configured and tested
- [ ] Project IDs verified and accessible
- [ ] Virtual environment created
- [ ] Dependencies installed successfully
- [ ] Test single file extraction
- [ ] Test batch processing
- [ ] Verify cache directory permissions
- [ ] Test profile save/load functionality
- [ ] Confirm browser downloads work
- [ ] Train users on basic workflow

---

## 📞 Support

For production support:
1. Check the troubleshooting section above
2. Review application logs and console output
3. Verify APS API status at status.autodesk.com
4. Test with verbose logging enabled

This production branch is designed for reliability and ease of deployment. The launcher scripts handle most setup automatically.