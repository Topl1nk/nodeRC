# NodeRC

![Screenshot](doc/images/Screenshot.png)

[English](README.md) | [Українська](doc/README.uk.md) | [Español](doc/README.es.md) | [中文](doc/README.zh.md) | [Français](doc/README.fr.md) | [Deutsch](doc/README.de.md) | [日本語](doc/README.ja.md) | [हिन्दी](doc/README.hi.md) | [Português](doc/README.pt.md) | [العربية](doc/README.ar.md)

NodeRC is an unofficial node-based visual interface and editor for RealityCapture / RealityScan CLI commands. Written in Python using PyQt5, the project allows you to visually connect and manage command nodes on an interactive canvas, providing a user-friendly interface for workflow automation.

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

### Controls & Shortcuts

- **Pan Canvas:** Click and hold the **Middle Mouse Button (MMB)** and drag.
- **Zoom:** Scroll the **Mouse Wheel**.
- **Add Node:** Press **Space** or **Right-click** on empty canvas space to open the Search Menu. Select a command or parameter node to spawn it at the cursor position.
- **Connect Sockets:** Drag a line from an output socket to an input socket.
  - Dragging from a socket and releasing on an empty canvas space opens the Search Menu to select and auto-connect a new node.
- **Delete Node/Connection:** Select the item and press **Delete**.
- **Group Nodes:** Select nodes and press **Ctrl + G** to place them in a frame.
- **Duplicate Nodes:** Select nodes and press **Ctrl + D**.
- **Copy / Paste:** Select nodes and press **Ctrl + C** to copy, and **Ctrl + V** to paste at the cursor position.
- **Undo / Redo:** Press **Ctrl + Z** to undo and **Ctrl + Y** (or **Ctrl + Shift + Z**) to redo.
- **Select All:** Press **Ctrl + A**.
- **Toggle Grid:** Press **G**.
- **Fit View:** Press **F** to focus the view on the selection (or all nodes if none are selected).
- **Rename Node:** Select a parameter node and press **F2**.
- **Fullscreen:** Press **F11** to toggle.

### Execution Workflow

1. **Initialize the Chain:** The `> START` node is always present on the canvas.
2. **Add Command Nodes:** Press **Space** and add commands (e.g., `-addFolder`, `-align`, etc.).
3. **Link Execution:** Connect the execution sockets (arrow-shaped) sequentially starting from the `> START` node's output.
4. **Configure Parameters:** Add parameter nodes (String, Integer, Float, File/Dir Path) via the Search Menu and connect their output to the command nodes' input sockets.
5. **Run:** Click the **> Launch** button on the `> START` node to execute the CLI chain in RealityCapture.


## Project Structure

- `nodeRC.py` - Main entry point.
- `canvas.py` - Main editor window logic.
- `scene.py` - Canvas scene and visual item event handling.
- `view.py` - Graphic view logic, panning, and zooming.
- `nodes_base.py` - Base classes for nodes, sockets, and connections.
- `nodes_concrete.py` - Concrete implementations of specialized nodes (Start, Command, Parameter nodes).
- `configuration.py` - Single source of truth for styles, UI settings, and hotkeys.
- `search_menu.py` - Autocomplete search dialog for spawning nodes.
- `diagnostics.py` - Exception handler and error logging.
- `rc_documentation_extractor.py` - Command database builder from local RealityCapture documentation.

## License

This project is distributed "as is". See the project files for more information.

## Disclaimer

This project is an independent, unofficial open-source tool and is not affiliated with, endorsed by, sponsored by, or associated with Capturing Reality, Epic Games, or any of their affiliates. "RealityCapture" and "RealityScan" are trademarks or registered trademarks of Epic Games, Inc. or its affiliates.
