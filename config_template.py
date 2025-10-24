# Production Configuration Template
# Copy this to config.py and update with your actual values

# Autodesk Platform Services (APS) Credentials
APS_CLIENT_ID = 'your_client_id_here'
APS_CLIENT_SECRET = 'your_client_secret_here'

# Autodesk Construction Cloud (ACC) Project Details
ACC_PROJECT_ID = 'your_project_id_here'  # Format: b.xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
ACC_HUB_ID = 'your_hub_id_here'          # Format: b.xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# Application Settings
CACHE_MAX_AGE_HOURS = 168        # Cache expires after 7 days
EXTRACTION_DELAY_SECONDS = 30    # Delay before auto-extraction starts
MAX_CONCURRENT_WORKERS = 8       # Thread pool size for file scanning
MAX_RETRIES_PER_MODEL = 150      # Extraction retry limit

# Optional: Override default Autodesk endpoints (rarely needed)
# BASE_URL = 'https://developer.api.autodesk.com'
# HTTP_TIMEOUT = 30