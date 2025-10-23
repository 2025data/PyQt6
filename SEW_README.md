# Kindle Drawing to Embroidery Workflow

This system allows you to draw on your Kindle's browser and convert the drawings to embroidery files (PES format).

## Components

1. **draw.html** - Drawing app for Kindle browser
2. **sew_server.py** - Flask server to receive drawings from Kindle
3. **sew_viewer.py** - PyQt6 desktop app to visualize and convert to PES

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements_sew.txt
```

Or install individually:
```bash
pip install flask flask-cors pystitch PyQt6
```

### 2. Start the Server (on PC)

```bash
python sew_server.py
```

The server will:
- Run on port 5000
- Create a `SewCustom` folder for storing drawings
- Accept drawings from the Kindle app

### 3. Open Drawing App on Kindle

1. Find your PC's IP address:
   - Windows: `ipconfig` (look for IPv4 Address)
   - Mac/Linux: `ifconfig` or `ip addr`

2. On your Kindle's browser, open:
   ```
   http://YOUR_PC_IP:5000/
   ```
   For example: `http://192.168.0.41:5000/`
   
   This will load the sew.html drawing app

3. Draw something, then click the "🧵 Sew" button
   - The drawing will be saved as JSON on your PC in the `SewCustom` folder

### 4. View and Convert (on PC)

```bash
python sew_viewer.py
```

The viewer app will:
- Show all saved drawings from the `SewCustom` folder
- Display a preview of the selected drawing
- Allow conversion to PES format with the "Convert to PES" button
- Allow export to SVG format with the "Export SVG" button

## Workflow Summary

```
Kindle Browser (draw.html)
    ↓ Click "Sew" button
    ↓ HTTP POST to server
PC Server (sew_server.py)
    ↓ Saves JSON to SewCustom/
PC Viewer App (sew_viewer.py)
    ↓ Loads JSON files
    ↓ Click "Convert to PES"
    ↓ Saves .pes embroidery file
```

## Drawing Features

- **Color Selector**: Black to white in 6 grayscale steps
- **Line Weights**: 1-300px in 11 exponential steps
- **Mirror Modes**:
  - None: Normal drawing
  - Bi-lateral: Horizontal mirror
  - Radial: 8-way radial symmetry
  - Quad: 4-quadrant symmetry
- **Dot Drawing**: Tap or hold still to draw dots
- **Smooth Lines**: Automatically interpolated for e-ink displays

## File Structure

```
SewCustom/
  ├── drawing_20250122_143052.json
  ├── drawing_20250122_143115.json
  └── ...
```

Each JSON file contains:
- Canvas dimensions
- All stroke data (coordinates, colors, line widths, mirror mode)
- Timestamp

## Embroidery Conversion Settings

The PES converter uses these settings:
- **Scale**: Divides canvas pixels by 4 (adjustable in code)
- **Max Stitch**: 12mm (120 units in pystitch)
- **Tie On/Off**: Enabled for secure thread starts/ends

## Troubleshooting

### "Cannot connect to server" on Kindle
1. Make sure `sew_server.py` is running
2. Check that Kindle and PC are on the same network
3. Update the server URL in `draw.html` if needed (change `localhost` to your PC's IP)

### No files appear in viewer
1. Check that drawings are being saved to the `SewCustom` folder
2. Click "Refresh List" in the viewer

### Conversion errors
1. Make sure drawing has actual strokes (not empty)
2. Check that pystitch is installed correctly

## Customization

### Change embroidery size
Edit `sew_viewer.py`, line ~172:
```python
scale = 0.25  # Increase for larger, decrease for smaller
```

### Change server port
Edit `sew_server.py`, line ~58:
```python
app.run(host='0.0.0.0', port=5000, debug=True)  # Change 5000 to desired port
```

### Add more embroidery formats
In `sew_viewer.py`, you can add buttons for:
- DST format: `pystitch.write_dst(pattern, file)`
- EXP format: `pystitch.write_exp(pattern, file)`
- JEF format: `pystitch.write_jef(pattern, file)`

## Notes

- All drawings are stored as vector data (coordinate arrays)
- Mirror effects are baked into the coordinate data
- The system preserves color and line weight information
- JSON files can be backed up or shared
