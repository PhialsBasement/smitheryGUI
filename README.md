# Smithery GUI

Desktop application for installing and managing Smithery MCPs.

## Features
- Browse available MCPs
- Search functionality
- Install MCPs with one click
- Advanced mode with terminal output
- Cross-platform support (Windows & Linux)

## Installation

Download the latest release from the [Releases](https://github.com/PhialsBasement/smitheryGUI/releases) page.

### Windows
1. Download `main.exe`
2. Run the executable

### Linux
1. Download `main`
2. Make executable: `chmod +x main`
3. Run: `./main`

## Development Setup

```bash
# Clone repository
git clone https://github.com/PhialsBasement/smitheryGUI.git
cd smitheryGUI

# Install dependencies
pip install -r requirements.txt

# Run application
python main.py
```

## Building from Source

```bash
pip install pyinstaller
pyinstaller --onefile main.py
```

## Contributing

1. Fork repository
2. Create feature branch: `git checkout -b feature/YourFeature`
3. Commit changes: `git commit -m 'Add YourFeature'`
4. Push branch: `git push origin feature/YourFeature`
5. Submit pull request