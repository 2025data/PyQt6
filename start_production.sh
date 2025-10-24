#!/bin/bash
# IESViewerAudit.py Production Launcher (Linux/macOS)
# This script starts the IES Viewer Audit application

echo ""
echo "========================================"
echo "   IES Viewer Audit - Production"
echo "========================================"
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed or not in PATH"
    echo "Please install Python 3.8+ and try again"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create virtual environment"
        exit 1
    fi
fi

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to activate virtual environment"
    exit 1
fi

# Install/update dependencies
echo "Installing dependencies..."
pip install -r requirements.txt --quiet
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install dependencies"
    exit 1
fi

# Check if config exists
if [ ! -f "config.py" ]; then
    if [ -f "config_template.py" ]; then
        echo ""
        echo "WARNING: No config.py found!"
        echo "Please copy config_template.py to config.py and update with your credentials"
        echo ""
        echo "Example:"
        echo "cp config_template.py config.py"
        echo "nano config.py  # or your preferred editor"
        echo ""
        echo "After setting up config.py, run this script again."
        exit 1
    fi
fi

# Start the application
echo ""
echo "Starting IES Viewer Audit..."
echo "Press Ctrl+C to stop the application"
echo ""
python3 IESViewerAudit.py

# Handle exit
echo ""
echo "Application stopped."