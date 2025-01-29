#!/usr/bin/env python3
import sys
import os
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
import time
import json
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

    def __init__(self, command):
        super().__init__()
        self.command = command
        self.process = None
        self.waiting_for_input = False
            
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

    def terminate(self):
        if self.process:
            import signal
            self.process.kill(signal.SIGTERM)
            super().terminate()


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

        top_bar_layout.addWidget(self.search_input)
        top_bar_layout.addWidget(self.client_combo)
        top_bar_layout.addWidget(self.mode_switch)
        top_bar_layout.addStretch()

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
            import re
            import signal
            
            print(f"DEBUG: Raw prompt received: {repr(prompt)}")
            
            # Clean up the prompt by removing ANSI escape sequences and extra whitespace
            clean_prompt = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', prompt)
            clean_prompt = re.sub(r'\s+', ' ', clean_prompt).strip()
            
            print(f"DEBUG: Cleaned prompt: {repr(clean_prompt)}")
            
            # Handle restart prompt immediately
            if any(x in clean_prompt.lower() for x in ["would you like to restart", "(y/n)", "restart the claude app"]):
                if not hasattr(self, 'restart_handled'):
                    try:
                        self.runner.write_input("n\n")
                        self.restart_handled = True
                    except:
                        print("DEBUG: Process already closed")
                return
    
            # Remove leading "? " if present
            if clean_prompt.startswith('? '):
                clean_prompt = clean_prompt[2:]
            
            # Extract the base prompt (everything before any user input)
            base_prompt = clean_prompt.split('\n')[0].strip()
            if hasattr(self, 'last_base_prompt'):
                print(f"DEBUG: Comparing base prompts:")
                print(f"DEBUG: Current: {repr(base_prompt)}")
                print(f"DEBUG: Last: {repr(self.last_base_prompt)}")
                
                if base_prompt == self.last_base_prompt:
                    print("DEBUG: Duplicate prompt detected, ignoring")
                    return
            
            self.last_base_prompt = base_prompt
            
            # Create and style the input dialog
            dialog = QInputDialog(self)
            dialog.setWindowTitle("Input Required")
            dialog.setLabelText(base_prompt)
            dialog.setTextEchoMode(QLineEdit.EchoMode.Normal)
            
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
            
            if dialog.exec():
                text = dialog.textValue()
                try:
                    self.runner.write_input(text + '\n')
                except:
                    print("DEBUG: Process closed, cannot write input")
            else:
                # Handle cancellation
                try:
                    if self.runner and self.runner.process:
                        self.runner.process.kill(signal.SIGTERM)
                        self.runner.process = None
                        self.terminal.append("\nOperation cancelled by user")
                except Exception as e:
                    print(f"DEBUG: Error during cancellation: {e}")
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
            
            # Create horizontal layout for name and learn more link
            name_layout = QHBoxLayout()
            name_layout.setSpacing(8)
            name_layout.addWidget(name_label)
            
            learn_more = QLabel(f'<a href="https://smithery.ai/server/{qname}" style="color: #FF5722; text-decoration: none;">Learn More</a>')
            learn_more.setTextFormat(Qt.TextFormat.RichText)
            learn_more.setOpenExternalLinks(True)
            name_layout.addWidget(learn_more)
            name_layout.addStretch()

            cmd_label = QLabel(base_cmd)
            cmd_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cmd_label.setStyleSheet("""
                color: rgb(125, 211, 252);
                font-family: 'Consolas', 'Monaco', monospace;
                padding: 4px 0px;
            """)

            text_info_layout.addLayout(name_layout)
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
    def ensure_runner_dir(self):
        if not os.path.exists('/home/runner'):
            msg = QMessageBox(self)
            msg.setWindowTitle("First Run Setup")
            msg.setText("Smithery needs to create some directories. This requires sudo access and will only happen once.")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.exec()

            password, ok = QInputDialog.getText(
                self, 'Sudo Required',
                'Please enter your sudo password:',
                QLineEdit.EchoMode.Password
            )

            if ok and password:
                cmd = f'echo {password} | sudo -S mkdir -p /home/runner/.config/Claude && sudo chown -R $USER:$USER /home/runner'
                proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                _, err = proc.communicate()

                if proc.returncode != 0:
                    QMessageBox.critical(self, "Setup Failed", f"Failed to create directories: {err.decode()}")
                    return False
                return True
            return False
        return True        
    def run_command(self, base_command, name):
            # First ensure runner directory exists
            if not self.ensure_runner_dir():
                return

            selected_client = self.client_combo.currentText().lower()
            is_windows = sys.platform.startswith('win')

            try:
                if is_windows:
                    for possible_path in [
                        os.path.join(os.getenv('APPDATA', ''), 'npm', 'npx.cmd'),
                        os.path.join(os.getenv('ProgramFiles', 'C:\\Program Files'), 'nodejs', 'npx.cmd'),
                        os.path.join(os.getenv('ProgramFiles(x86)', 'C:\\Program Files (x86)'), 'nodejs', 'npx.cmd')
                    ]:
                        if os.path.exists(possible_path):
                            final_command = f'"{possible_path}" -y @smithery/cli@latest install {base_command.split()[-1]} --client {selected_client}'
                            break
                    else:
                        final_command = base_command + f" --client {selected_client}"
                else:
                    npx_path = subprocess.check_output(['which', 'npx']).decode().strip()
                    final_command = f"{npx_path} -y @smithery/cli@latest install {base_command.split()[-1]} --client {selected_client}"
            except:
                final_command = base_command + f" --client {selected_client}"

            if self.is_advanced_mode:
                self.terminal.append(f"Installing {name} with client: {selected_client}...")
                self.terminal.append(f"> {final_command}\n")

            self.runner = CommandRunner(final_command)
            self.runner.output_ready.connect(self.on_output_line)
            self.runner.input_required.connect(self.handle_input_required)
            self.runner.start()

    def ensure_config_copied(self):
        source = '/home/runner/.config/Claude/claude_desktop_config.json'
        dest = os.path.expanduser('~/.config/Claude/claude_desktop_config.json')

        try:
            if os.path.exists(source):
                # Read the new config
                with open(source) as f:
                    new_config = json.load(f)

                # Read existing config if it exists
                existing_config = {"mcpServers": {}}
                if os.path.exists(dest):
                    try:
                        with open(dest) as f:
                            existing_config = json.load(f)
                    except json.JSONDecodeError:
                        print(f"DEBUG: Invalid JSON in existing config, will overwrite")

                # Make sure mcpServers exists in both
                if "mcpServers" not in existing_config:
                    existing_config["mcpServers"] = {}
                if "mcpServers" not in new_config:
                    new_config["mcpServers"] = {}

                # Merge mcpServers entries
                for server_name, server_config in new_config["mcpServers"].items():
                    existing_config["mcpServers"][server_name] = server_config

                # Make sure destination directory exists
                os.makedirs(os.path.dirname(dest), exist_ok=True)

                # Write merged config
                with open(dest, 'w') as f:
                    json.dump(existing_config, f, indent=2)

                print(f"DEBUG: Merged new config into {dest}")
                return True

        except Exception as e:
            print(f"DEBUG: Failed to merge config: {e}")
        return False

    def on_output_line(self, line):
            import json
            print(f"DEBUG: {line}")
            if self.is_advanced_mode:
                self.terminal.append(line)
                cursor = self.terminal.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                self.terminal.setTextCursor(cursor)
            else:
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
                elif "Successfully installed" in line:
                    time.sleep(1)

                    if self.ensure_config_copied():
                        msg = QMessageBox(QMessageBox.Icon.Information, "Installation Status", 
                                        "Installation completed successfully!\n\nPlease restart Claude to use the new MCP.", parent=self)
                    else:
                        source = '/home/runner/.config/Claude/claude_desktop_config.json'
                        error_msg = "Installation completed but config setup failed.\nTry running the app with sudo once."
                        if os.path.exists(source):
                            try:
                                with open(source) as f:
                                    config = f.read()
                                error_msg += f"\n\nDebug info:\nConfig exists at {source}\nContents: {config}"
                            except Exception as e:
                                error_msg += f"\n\nDebug info: Failed to read config: {e}"
                        else:
                            error_msg += f"\n\nDebug info: Config not found at {source}"

                        msg = QMessageBox(QMessageBox.Icon.Warning, "Installation Status", error_msg, parent=self)

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