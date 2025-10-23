from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import json
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Create SewCustom directory if it doesn't exist
SEW_FOLDER = os.path.join(os.path.dirname(__file__), 'SewCustom')
os.makedirs(SEW_FOLDER, exist_ok=True)

@app.route('/')
def index():
    """Serve the main drawing page"""
    print(f"📱 Request from: {request.remote_addr}")
    return send_file('sew.html')

@app.route('/sew.html')
def serve_sew():
    """Serve the sew.html file"""
    print(f"📱 Request for sew.html from: {request.remote_addr}")
    return send_file('sew.html')

@app.route('/draw.html')
def serve_draw():
    """Serve the draw.html file (fallback)"""
    print(f"📱 Request for draw.html from: {request.remote_addr}")
    return send_file('draw.html')

@app.route('/test')
def test():
    """Test endpoint to verify connectivity"""
    print(f"✅ Test request from: {request.remote_addr}")
    return f"<html><body><h1>Server is working!</h1><p>Request from: {request.remote_addr}</p></body></html>"

@app.route('/save_drawing', methods=['POST'])
def save_drawing():
    """Receive drawing data from Kindle and save as JSON"""
    try:
        data = request.json
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'drawing_{timestamp}.json'
        filepath = os.path.join(SEW_FOLDER, filename)
        
        # Save JSON file
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"Saved drawing to: {filepath}")
        return jsonify({
            'success': True,
            'filename': filename,
            'path': filepath
        })
    
    except Exception as e:
        print(f"Error saving drawing: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/list_drawings', methods=['GET'])
def list_drawings():
    """List all saved drawings"""
    try:
        files = [f for f in os.listdir(SEW_FOLDER) if f.endswith('.json')]
        files.sort(reverse=True)  # Most recent first
        return jsonify({
            'success': True,
            'files': files
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    import socket
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    
    print("=" * 60)
    print("🧵 Embroidery Server Started!")
    print("=" * 60)
    print(f"Drawings will be saved to: {SEW_FOLDER}")
    print(f"\nAccess the drawing app from:")
    print(f"  • This PC:      http://localhost:8000/")
    print(f"  • Kindle:       http://{local_ip}:8000/")
    print(f"  • Other device: http://{local_ip}:8000/")
    print(f"\nTest connection first:")
    print(f"  • From Kindle, try: http://{local_ip}:8000/test")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 60)
    print("\nWatching for connections...")
    
    app.run(host='0.0.0.0', port=8000, debug=True, use_reloader=False)
