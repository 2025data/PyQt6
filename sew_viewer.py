import sys
import json
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QListWidget, QLabel,
                             QMessageBox, QFileDialog)
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush
import pystitch

class EmbroideryCanvas(QWidget):
    """Widget to display the embroidery preview"""
    def __init__(self):
        super().__init__()
        self.drawing_data = None
        self.setMinimumSize(600, 600)
        
    def load_drawing(self, data):
        """Load drawing data from JSON"""
        self.drawing_data = data
        self.update()
        
    def paintEvent(self, event):
        """Paint the drawing preview"""
        if not self.drawing_data:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Fill background
        painter.fillRect(self.rect(), QColor(255, 255, 255))
        
        # Calculate scaling to fit widget
        if self.drawing_data.get('width') and self.drawing_data.get('height'):
            scale_x = self.width() / self.drawing_data['width']
            scale_y = self.height() / self.drawing_data['height']
            scale = min(scale_x, scale_y, 1.0)  # Don't scale up, only down
        else:
            scale = 1.0
            
        # Draw each stroke
        for stroke in self.drawing_data.get('strokes', []):
            color = QColor(stroke['color'])
            width = stroke['width'] * scale
            coords = stroke['coordinates']
            
            pen = QPen(color, width, Qt.PenStyle.SolidLine, 
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            
            if stroke.get('type') == 'dot':
                # Draw dot
                if coords:
                    x, y = coords[0]
                    painter.setBrush(QBrush(color))
                    painter.drawEllipse(QPointF(x * scale, y * scale), 
                                      width / 2, width / 2)
            else:
                # Draw line
                if len(coords) > 1:
                    for i in range(len(coords) - 1):
                        x1, y1 = coords[i]
                        x2, y2 = coords[i + 1]
                        painter.drawLine(QPointF(x1 * scale, y1 * scale),
                                       QPointF(x2 * scale, y2 * scale))

class SewViewer(QMainWindow):
    """Main application window"""
    def __init__(self):
        super().__init__()
        self.current_file = None
        self.sew_folder = os.path.join(os.path.dirname(__file__), 'SewCustom')
        os.makedirs(self.sew_folder, exist_ok=True)
        
        self.init_ui()
        self.load_file_list()
        
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle('Embroidery Viewer & Converter')
        self.setGeometry(100, 100, 1000, 700)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        # Main layout
        main_layout = QHBoxLayout(central)
        
        # Left panel - file list
        left_panel = QVBoxLayout()
        
        left_panel.addWidget(QLabel('Saved Drawings:'))
        
        self.file_list = QListWidget()
        self.file_list.itemClicked.connect(self.load_drawing)
        left_panel.addWidget(self.file_list)
        
        refresh_btn = QPushButton('🔄 Refresh List')
        refresh_btn.clicked.connect(self.load_file_list)
        left_panel.addWidget(refresh_btn)
        
        main_layout.addLayout(left_panel, 1)
        
        # Right panel - preview and controls
        right_panel = QVBoxLayout()
        
        right_panel.addWidget(QLabel('Preview:'))
        
        self.canvas = EmbroideryCanvas()
        right_panel.addWidget(self.canvas)
        
        # Button panel
        button_layout = QHBoxLayout()
        
        self.convert_btn = QPushButton('🧵 Convert to PES')
        self.convert_btn.clicked.connect(self.convert_to_pes)
        self.convert_btn.setEnabled(False)
        button_layout.addWidget(self.convert_btn)
        
        self.export_svg_btn = QPushButton('📄 Export SVG')
        self.export_svg_btn.clicked.connect(self.export_svg)
        self.export_svg_btn.setEnabled(False)
        button_layout.addWidget(self.export_svg_btn)
        
        right_panel.addLayout(button_layout)
        
        # Info label
        self.info_label = QLabel('Select a drawing file to preview')
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_panel.addWidget(self.info_label)
        
        main_layout.addLayout(right_panel, 2)
        
    def load_file_list(self):
        """Load list of JSON files from SewCustom folder"""
        self.file_list.clear()
        
        if not os.path.exists(self.sew_folder):
            return
            
        files = [f for f in os.listdir(self.sew_folder) if f.endswith('.json')]
        files.sort(reverse=True)  # Most recent first
        
        for filename in files:
            self.file_list.addItem(filename)
            
        self.info_label.setText(f'Found {len(files)} drawing(s)')
        
    def load_drawing(self, item):
        """Load and display selected drawing"""
        filename = item.text()
        filepath = os.path.join(self.sew_folder, filename)
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                
            self.canvas.load_drawing(data)
            self.current_file = filepath
            self.convert_btn.setEnabled(True)
            self.export_svg_btn.setEnabled(True)
            
            # Update info
            num_strokes = len(data.get('strokes', []))
            timestamp = data.get('timestamp', 'Unknown')
            self.info_label.setText(f'{filename}\n{num_strokes} strokes | {timestamp}')
            
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to load file:\n{e}')
            
    def convert_to_pes(self):
        """Convert current drawing to PES embroidery format"""
        if not self.current_file:
            return
            
        try:
            # Load JSON data
            with open(self.current_file, 'r') as f:
                data = json.load(f)
                
            # Create embroidery pattern
            pattern = pystitch.EmbPattern()
            
            # Scaling factor (divide by 4 for reasonable embroidery size)
            # 1 unit in pystitch = 0.1mm
            scale = 0.25
            
            # Convert each stroke
            for stroke in data.get('strokes', []):
                coords = stroke['coordinates']
                color = stroke['color']
                
                if len(coords) < 2:
                    continue  # Skip single points
                    
                # Scale coordinates
                scaled_coords = [(x * scale, y * scale) for x, y in coords]
                
                # Add to pattern
                pattern.add_block(scaled_coords, color)
            
            # Generate output filename
            base_name = os.path.splitext(os.path.basename(self.current_file))[0]
            default_name = f'{base_name}.pes'
            
            # Save dialog
            output_file, _ = QFileDialog.getSaveFileName(
                self, 'Save PES File', default_name, 'PES Files (*.pes)'
            )
            
            if output_file:
                # Write PES file with settings
                pystitch.write_pes(pattern, output_file, {
                    'max_stitch': 120,
                    'tie_on': True,
                    'tie_off': True
                })
                
                QMessageBox.information(
                    self, 'Success', 
                    f'Successfully converted to PES!\n\nSaved to:\n{output_file}'
                )
                
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to convert:\n{e}')
            
    def export_svg(self):
        """Export current drawing to SVG format"""
        if not self.current_file:
            return
            
        try:
            # Load JSON data
            with open(self.current_file, 'r') as f:
                data = json.load(f)
                
            # Create embroidery pattern
            pattern = pystitch.EmbPattern()
            
            scale = 0.25
            
            # Convert each stroke
            for stroke in data.get('strokes', []):
                coords = stroke['coordinates']
                color = stroke['color']
                
                if len(coords) < 2:
                    continue
                    
                scaled_coords = [(x * scale, y * scale) for x, y in coords]
                pattern.add_block(scaled_coords, color)
            
            # Generate output filename
            base_name = os.path.splitext(os.path.basename(self.current_file))[0]
            default_name = f'{base_name}.svg'
            
            # Save dialog
            output_file, _ = QFileDialog.getSaveFileName(
                self, 'Save SVG File', default_name, 'SVG Files (*.svg)'
            )
            
            if output_file:
                pystitch.write_svg(pattern, output_file)
                
                QMessageBox.information(
                    self, 'Success', 
                    f'Successfully exported to SVG!\n\nSaved to:\n{output_file}'
                )
                
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to export:\n{e}')

def main():
    app = QApplication(sys.argv)
    viewer = SewViewer()
    viewer.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
