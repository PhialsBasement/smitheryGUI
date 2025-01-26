#!/usr/bin/env python3
import sys
import subprocess
import requests
import pexpect
import pexpect.popen_spawn
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QTextEdit,
    QFrame,
    QSplitter,
    QScrollArea,
    QComboBox,
    QSizePolicy,
    QInputDialog,
    QMessageBox,
    QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtGui import QFont, QTextCursor


class FetchWorker(QThread):
    finished = pyqtSignal(list)
    
    def __init__(self, fetch_func, search_text=""):
        super().__init__()
        self.fetch_func = fetch_func
        self.search_text = search_text
        
    def run(self):
        results = self.fetch_func(self.search_text)
        self.finished.emit(results)


class LoadingOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        palette = self.palette()
        palette.setColor(palette.ColorRole.Window, Qt.GlobalColor.transparent)
        self.setPalette(palette)
        
        layout = QVBoxLayout(self)
        loading_label = QLabel("Loading...")
        loading_label.setStyleSheet("""
            QLabel {
                color: white;
                background-color: #1E1E1E;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
        """)
        layout.addWidget(loading_label, alignment=Qt.AlignmentFlag.AlignCenter)
        
    def showEvent(self, event):
        self.setGeometry(self.parent().rect())

class CommandRunner(QThread):
    output_ready = pyqtSignal(str)
    input_required = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smithery MCP Installer")
        self.resize(1200, 800)
        self.runner = None
        self.is_advanced_mode = False
        
        # Setup search timer for debouncing
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.do_search)

        self.init_ui()
        self.setup_styles()

    def run(self):
        try:
            self.process = pexpect.popen_spawn.PopenSpawn(self.command)
            
            while True:
                try:
                    index = self.process.expect(['.+', pexpect.EOF, pexpect.TIMEOUT], timeout=0.1)
                    
                    if index == 0:
                        output = self.process.match.group(0).decode('utf-8')
                        if '?' in output and not self.waiting_for_input:
                            self.waiting_for_input = True
                            self.input_required.emit(output)
                        self.output_ready.emit(output)
                    elif index == 1:
                        break
                    
                except Exception as e:
                    if not str(e).startswith('Timeout'):
                        self.output_ready.emit(f"Error reading output: {str(e)}")
                        break
            
            self.process.wait()
            if self.process.exitstatus == 0:
                self.output_ready.emit("\nCommand completed successfully")
            else:
                self.output_ready.emit(f"\nCommand failed with return code: {self.process.exitstatus}")
                
        except Exception as e:
            self.output_ready.emit(f"Error executing command: {str(e)}")
            
    def write_input(self, data):
        if self.process:
            self.process.write(data.encode())
            self.waiting_for_input = False


class MCPInstaller(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smithery MCP Installer")
        self.resize(1200, 800)
        self.runner = None
        self.is_advanced_mode = False

        # Setup search timer for debouncing
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.do_search)

        self.init_ui()
        self.setup_styles()
        
        # Start data fetch after UI is shown
        QTimer.singleShot(0, self.do_search)

    def fetch_servers(self, search_text=""):
        url = "https://your-domain.com/proxy.php"
        params = {
            'pageSize': 20
        }
        
        if search_text:
            params['q'] = search_text
            
        try:
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("servers", [])
        except Exception as e:
            print("Error fetching servers:", e)
            return []

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Top bar
        top_widget = QWidget()
        top_widget.setFixedHeight(70)
        top_bar_layout = QHBoxLayout(top_widget)
        top_bar_layout.setContentsMargins(24, 0, 24, 0)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search MCPs...")
        self.search_input.textChanged.connect(self.on_search_input_changed)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #1E1E1E;
                color: #FFFFFF;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #FF5722;
            }
        """)

        self.client_combo = QComboBox()
        self.client_combo.addItems(["Claude", "Cline", "Roo-Cline"])
        self.client_combo.setStyleSheet("""
            QComboBox {
                background-color: #1E1E1E;
                color: #FFFFFF;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px;
                min-width: 150px;
            }
            QComboBox:focus {
                border-color: #FF5722;
            }
        """)

        self.mode_switch = QCheckBox("Advanced Mode")
        self.mode_switch.setChecked(False)
        self.mode_switch.stateChanged.connect(self.toggle_mode)

        self.backlink_label = QLabel()
        self.backlink_label.setTextFormat(Qt.TextFormat.RichText)
        self.backlink_label.setOpenExternalLinks(True)
        self.backlink_label.setText(
            f'Powered by <a href="https://smithery.ai/" style="color: #FF5722; '
            'text-decoration: none;">Smithery.ai</a>'
        )

        top_bar_layout.addWidget(self.search_input)
        top_bar_layout.addWidget(self.client_combo)
        top_bar_layout.addWidget(self.mode_switch)
        top_bar_layout.addStretch()
        top_bar_layout.addWidget(self.backlink_label)

        main_layout.addWidget(top_widget)

        # Content area
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(24, 24, 24, 24)

        self.content_splitter = QSplitter(orientation=Qt.Orientation.Horizontal)

        # MCP List
        self.mcpScrollArea = QScrollArea()
        self.mcpScrollArea.setWidgetResizable(True)
        self.mcpScrollArea.setStyleSheet("""
            QScrollArea, QScrollArea > QWidget > QWidget {
                background-color: #1E1E1E;
            }
        """)

        # Create loading overlay after mcpScrollArea
        self.loading_overlay = LoadingOverlay(self.mcpScrollArea)
        self.loading_overlay.hide()

        self.mcpScrollContent = QWidget()
        self.mcpScrollContent.setStyleSheet("background-color: #1E1E1E;")
        self.mcpLayout = QVBoxLayout(self.mcpScrollContent)
        self.mcpLayout.setSpacing(12)
        self.mcpLayout.setContentsMargins(0, 0, 24, 0)
        self.mcpLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # Add placeholder message
        self.placeholder_label = QLabel("Loading MCPs...")
        self.placeholder_label.setStyleSheet("""
            QLabel {
                color: #9CA3AF;
                font-size: 16px;
                padding: 20px;
            }
        """)
        self.mcpLayout.addWidget(self.placeholder_label)
        
        self.mcpScrollArea.setWidget(self.mcpScrollContent)

        # Terminal
        self.terminal_frame = QFrame()
        terminal_layout = QVBoxLayout(self.terminal_frame)
        terminal_layout.setContentsMargins(24, 0, 0, 0)
        
        terminal_header = QLabel("Terminal Output")
        terminal_header.setStyleSheet("color: #9CA3AF; font-weight: bold;")
        terminal_layout.addWidget(terminal_header)

        self.terminal = QTextEdit()
        self.terminal.keyPressEvent = self.handle_terminal_input
        terminal_layout.addWidget(self.terminal)

        self.content_splitter.addWidget(self.mcpScrollArea)
        self.content_splitter.addWidget(self.terminal_frame)
        self.terminal_frame.setVisible(False)
        self.content_splitter.setSizes([700, 300])
        self.content_splitter.setStretchFactor(0, 7)
        self.content_splitter.setStretchFactor(1, 3)

        content_layout.addWidget(self.content_splitter)
        main_layout.addWidget(content_widget)

    def toggle_mode(self, state):
        self.is_advanced_mode = bool(state)
        self.terminal_frame.setVisible(self.is_advanced_mode)
        if not self.is_advanced_mode:
            self.content_splitter.setSizes([self.width(), 0])
        else:
            self.content_splitter.setSizes([700, 300])

    def handle_terminal_input(self, event):
        if self.runner and self.runner.process:
            if event.key() == Qt.Key.Key_Return:
                cursor = self.terminal.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                cursor.movePosition(cursor.MoveOperation.StartOfLine, cursor.MoveMode.KeepAnchor)
                line = cursor.selectedText()
                
                line = line.replace('[49D', '').replace('[49C', '')
                line = line.strip() + '\n'
                self.runner.write_input(line)
            else:
                QTextEdit.keyPressEvent(self.terminal, event)

    def handle_input_required(self, prompt):
        if not self.is_advanced_mode:
            # Clean up the prompt
            clean_prompt = prompt.replace('[49D', '').replace('[49C', '').strip()
            
            # Create and style the input dialog
            dialog = QInputDialog(self)
            dialog.setWindowTitle("Input Required")
            dialog.setLabelText(clean_prompt)
            dialog.setTextEchoMode(QLineEdit.EchoMode.Normal)
            
            # Set the stylesheet for the dialog
            dialog.setStyleSheet("""
                QInputDialog {
                    background-color: #1E1E1E;
                }
                QInputDialog QLabel {
                    color: #FFFFFF;
                    font-size: 14px;
                    padding: 10px;
                }
                QInputDialog QLineEdit {
                    background-color: #1E1E1E;
                    color: #FFFFFF;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    padding: 8px;
                    margin: 10px;
                    font-size: 14px;
                }
                QInputDialog QLineEdit:focus {
                    border-color: #FF5722;
                }
                QInputDialog QPushButton {
                    background-color: #FF5722;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                    margin: 10px;
                    font-weight: bold;
                    min-width: 80px;
                }
                QInputDialog QPushButton:hover {
                    background-color: #FF7043;
                }
                QInputDialog QPushButton:pressed {
                    background-color: #F4511E;
                }
            """)
            
            text, ok = dialog.exec(), dialog.textValue()
            if ok:
                self.runner.write_input(text + '\n')

    def fetch_servers(self, search_text=""):
        url = "https://sparkphial.com/proxgui.php"
        params = {
            'pageSize': 20
        }
        
        if search_text:
            params['q'] = search_text
            
        try:
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("servers", [])
        except Exception as e:
            print("Error fetching servers:", e)
            return []

    def on_search_input_changed(self, text):
        # Debounce search to avoid too many API calls
        self.search_timer.stop()
        self.search_timer.start(300)  # Wait 300ms before searching
        
    def do_search(self):
        search_text = self.search_input.text().strip()
        self.loading_overlay.show()
        
        # Create worker for fetching
        self.fetch_worker = FetchWorker(self.fetch_servers, search_text)
        self.fetch_worker.finished.connect(self.on_fetch_complete)
        self.fetch_worker.start()

    def on_fetch_complete(self, servers):
        self.loading_overlay.hide()
        self.populate_mcps(servers)

    def populate_mcps(self, servers):
        # Clear existing items including placeholder
        while self.mcpLayout.count():
            item = self.mcpLayout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        
        # Show placeholder if no servers
        if not servers:
            self.placeholder_label = QLabel("No MCPs found")
            self.placeholder_label.setStyleSheet("""
                QLabel {
                    color: #9CA3AF;
                    font-size: 16px;
                    padding: 20px;
                }
            """)
            self.mcpLayout.addWidget(self.placeholder_label)
            return

        for s in servers:
            name = s.get("displayName", "")
            desc = s.get("description", "")
            qname = s.get("qualifiedName", "")
            base_cmd = f"npx -y @smithery/cli@latest install {qname}"

            mcp_frame = QFrame()
            mcp_frame.setStyleSheet("#frame {border: 1px solid #333333; border-radius: 8px; background-color: #1E1E1E;}")
            mcp_frame.setObjectName("frame")
            row_layout = QHBoxLayout(mcp_frame)
            row_layout.setContentsMargins(16, 16, 16, 16)
            row_layout.setSpacing(16)

            text_info_widget = QWidget()
            text_info_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            text_info_layout = QVBoxLayout(text_info_widget)
            text_info_layout.setContentsMargins(0, 0, 0, 0)
            text_info_layout.setSpacing(8)

            name_label = QLabel(name)
            name_label.setStyleSheet("""
                color: white;
                font-size: 16px;
                font-weight: bold;
            """)

            desc_label = QLabel(desc)
            desc_label.setStyleSheet("color: rgb(156, 163, 175);")
            desc_label.setWordWrap(True)
            desc_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

            cmd_label = QLabel(base_cmd)
            cmd_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cmd_label.setStyleSheet("""
                color: rgb(125, 211, 252);
                font-family: 'Consolas', 'Monaco', monospace;
                padding: 4px 0px;
            """)

            text_info_layout.addWidget(name_label)
            text_info_layout.addWidget(desc_label)
            text_info_layout.addWidget(cmd_label)
            row_layout.addWidget(text_info_widget)

            install_btn = QPushButton("Install")
            install_btn.setFixedWidth(120)
            install_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FF5722;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #FF7043;
                }
            """)
            install_btn.clicked.connect(
                lambda _, cmd=base_cmd, n=name: self.run_command(cmd, n)
            )
            row_layout.addWidget(install_btn, alignment=Qt.AlignmentFlag.AlignRight)

            self.mcpLayout.addWidget(mcp_frame)

    def filter_mcps(self, text):
        self.populate_mcps(text)
        
    def run_command(self, base_command, name):
        selected_client = self.client_combo.currentText().lower()
        final_command = f"{base_command} --client {selected_client}"

        if self.is_advanced_mode:
            self.terminal.append(f"Installing {name} with client: {selected_client}...")
            self.terminal.append(f"> {final_command}\n")

        self.runner = CommandRunner(final_command)
        self.runner.output_ready.connect(self.on_output_line)
        self.runner.input_required.connect(self.handle_input_required)
        self.runner.start()

    def on_output_line(self, line):
        if self.is_advanced_mode:
            self.terminal.append(line)
            cursor = self.terminal.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.terminal.setTextCursor(cursor)
        else:
            # In simplified mode, only show error messages in a popup
            if "Error" in line or "failed" in line.lower():
                msg = QMessageBox(QMessageBox.Icon.Warning, "Installation Status", line, parent=self)
                msg.setStyleSheet("""
                    QMessageBox {
                        background-color: #1E1E1E;
                    }
                    QMessageBox QLabel {
                        color: #FFFFFF;
                        font-size: 14px;
                        padding: 10px;
                        min-width: 400px;
                    }
                    QMessageBox QPushButton {
                        background-color: #FF5722;
                        color: white;
                        border: none;
                        border-radius: 4px;
                        padding: 8px 16px;
                        margin: 10px;
                        font-weight: bold;
                        min-width: 80px;
                    }
                    QMessageBox QPushButton:hover {
                        background-color: #FF7043;
                    }
                    QMessageBox QPushButton:pressed {
                        background-color: #F4511E;
                    }
                """)
                msg.exec()
            elif "completed successfully" in line:
                msg = QMessageBox(QMessageBox.Icon.Information, "Installation Status", 
                                "Installation completed successfully!", parent=self)
                msg.setStyleSheet("""
                    QMessageBox {
                        background-color: #1E1E1E;
                    }
                    QMessageBox QLabel {
                        color: #FFFFFF;
                        font-size: 14px;
                        padding: 10px;
                        min-width: 400px;
                    }
                    QMessageBox QPushButton {
                        background-color: #FF5722;
                        color: white;
                        border: none;
                        border-radius: 4px;
                        padding: 8px 16px;
                        margin: 10px;
                        font-weight: bold;
                        min-width: 80px;
                    }
                    QMessageBox QPushButton:hover {
                        background-color: #FF7043;
                    }
                    QMessageBox QPushButton:pressed {
                        background-color: #F4511E;
                    }
                """)
                msg.exec()

    def setup_styles(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1E1E1E;
            }
            QLabel {
                color: #FFFFFF;
            }
            QLineEdit {
                background-color: #1E1E1E;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 8px;
                font-size: 14px;
            }
            QLineEdit:focus {
                background-color: #333333;
            }
            QFrame {
                border: none;
                background: transparent;
            }
            QPushButton {
                background-color: #FF5722;
                color: white;
                border: none;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #FF7043;
            }
            QComboBox {
                background-color: #1E1E1E;
                color: #FFFFFF;
                border: none;
                padding: 8px;
                min-width: 150px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::drop-down:button {
                background-color: #1E1E1E;
            }
            QTextEdit {
                background-color: #000000;
                color: #00FF00;
                border: none;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 13px;
                padding: 8px;
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QCheckBox {
                color: #FFFFFF;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid #FF5722;
            }
            QCheckBox::indicator:checked {
                background-color: #FF5722;
            }
            QScrollBar:vertical {
                background-color: #1E1E1E;
                width: 14px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: #333333;
                min-height: 30px;
                border-radius: 7px;
                margin: 2px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: none;
            }
        """)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MCPInstaller()
    window.show()
    sys.exit(app.exec())