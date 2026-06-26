# NodeRC

[English](README.md) | [Русский](README.ru.md) | [Español](README.es.md) | [中文](README.zh.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [日本語](README.ja.md) | [हिन्दी](README.hi.md) | [Português](README.pt.md) | [العربية](README.ar.md)

NodeRC ist ein visueller Node-basierter Editor, der in Python mit PyQt5 geschrieben wurde. Das Projekt ermöglicht es Ihnen, Nodes (Knoten) auf einer interaktiven Leinwand (Canvas) zu erstellen, zu verbinden und zu verwalten, was eine benutzerfreundliche Oberfläche für die visuelle Programmierung oder die Konstruktion von Logikgraphen bietet.

## Funktionen
- **Interaktiver Canvas:** Ein unendlicher Arbeitsbereich mit Unterstützung für Schwenken und Zoomen.
- **Node-Architektur:** Verschiedene Arten von Nodes, die eingehende und ausgehende Verbindungen (Sockets) unterstützen.
- **Dynamische Verbindungen:** Visuelle Verknüpfung von Ausführungs- und Daten-Ports.
- **Konfigurationssystem:** Anpassbare Farben, Größen und Stile über eine zentrale Konfigurationsdatei.
- **Suchmenü:** Ein praktisches Menü zum schnellen Hinzufügen neuer Nodes zum Canvas.

## Anforderungen
- Python 3.7+
- PyQt5

## Installation

1. Klonen Sie das Repository:
   ```bash
   git clone <Repository_URL>
   cd nodeRC
   ```

2. Installieren Sie die Abhängigkeiten:
   ```bash
   pip install -r requirements.txt
   ```

## Verwendung
Um den Editor zu starten, führen Sie Folgendes aus:
```bash
python nodeRC.py
```

## Projektstruktur
- `nodeRC.py` - Haupteinstiegspunkt.
- `canvas.py` - Logik für interaktiven Canvas und Graphenverwaltung.
- `nodes.py` - Basis- und spezialisierte Klassen für Nodes und Sockets.
- `configuration.py` - Konfigurationsdatei (Farben, Stile, UI-Parameter).
- `search_menu.py` - Dialog zum Suchen und Hinzufügen von Nodes.
- `diagnostics.py` - Protokollierung und Ausnahmebehandlung.
- `rc_documentation_extractor.py` - Dienstprogramm zum Extrahieren von Befehlsdokumentationen.

## Lizenz
Dieses Projekt wird "wie besehen" verteilt. Weitere Informationen finden Sie in den Projektdateien.
