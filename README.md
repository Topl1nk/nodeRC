# NodeRC

[English](README.md) | [Русский](README.ru.md) | [Español](README.es.md) | [中文](README.zh.md)

NodeRC is a visual node-based editor written in Python using PyQt5. The project allows you to create, connect, and manage nodes on an interactive canvas, providing a user-friendly interface for visual programming or logic graph construction.

## Features
- **Interactive Canvas:** An infinite workspace with panning and zooming support.
- **Node Architecture:** Various types of nodes supporting incoming and outgoing connections (sockets).
- **Dynamic Connections:** Visual linking of execution ports and data ports.
- **Configuration System:** Customizable colors, sizes, and styles through a centralized configuration file.
- **Search Menu:** A convenient menu for quickly adding new nodes to the canvas.

## Requirements
- Python 3.7+
- PyQt5

## Installation

1. Clone the repository:
   ```bash
   git clone <repository_URL>
   cd nodeRC
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage
To start the editor, run:
```bash
python nodeRC.py
```

## Project Structure
- `nodeRC.py` - Main entry point.
- `canvas.py` - Interactive canvas logic and graph management.
- `nodes.py` - Base and specialized classes for nodes and sockets.
- `configuration.py` - Configuration file (colors, styles, UI parameters).
- `search_menu.py` - Dialog for searching and adding nodes.
- `diagnostics.py` - Logging and exception handling.
- `rc_documentation_extractor.py` - Utility for extracting command documentation.

## License
This project is distributed "as is". See the project files for more information.
