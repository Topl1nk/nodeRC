# NodeRC

![Screenshot](images/Screenshot.png)

[English](../README.md) | [Українська](README.uk.md) | [Español](README.es.md) | [中文](README.zh.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [日本語](README.ja.md) | [हिन्दी](README.hi.md) | [Português](README.pt.md) | [العربية](README.ar.md)

NodeRC ist eine inoffizielle visuelle Node-basierte Benutzeroberfläche und ein Editor für RealityCapture / RealityScan-CLI-Befehle. Das in Python mit PyQt5 geschriebene Projekt ermöglicht es Ihnen, Befehls-Nodes auf einer interaktiven Leinwand visuell zu verbinden und zu verwalten, wodurch eine benutzerfreundliche Oberfläche für die Workflow-Automatisierung bereitgestellt wird.

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

### Steuerung & Tastenkürzel

- **Leinwand schwenken:** Klicken und halten Sie die **mittlere Maustaste (MMB)** und ziehen Sie die Maus.
- **Zoomen:** Scrollen Sie mit dem **Mausrad**.
- **Node hinzufügen:** Drücken Sie die **Leertaste** oder machen Sie einen **Rechtsklick** auf eine freie Stelle der Leinwand, um das Suchmenü zu öffnen. Wählen Sie einen Befehls- oder Parameter-Node aus.
- **Sockets verbinden:** Ziehen Sie eine Verbindung von einem Ausgangs-Socket zu einem kompatiblen Eingangs-Socket.
  - Wenn Sie eine Verbindung von einem Socket ziehen und im leeren Raum loslassen, öffnet sich das Suchmenü, um einen neuen Node automatisch zu erstellen und zu verbinden.
- **Node/Verbindung löschen:** Wählen Sie das Element aus und drücken Sie die **Entf-Taste** (Delete).
- **Nodes gruppieren:** Wählen Sie Nodes aus und drücken Sie **Ctrl + G**, um sie in einem Rahmen zusammenzufassen.
- **Nodes duplizieren:** Wählen Sie Nodes aus und drücken Sie **Ctrl + D**.
- **Kopieren / Einfügen:** Wählen Sie Nodes aus und drücken Sie **Ctrl + C** zum Kopieren und **Ctrl + V** zum Einfügen an der Cursorposition.
- **Rückgängig / Wiederholen:** Drücken Sie **Ctrl + Z** für Rückgängig und **Ctrl + Y** (oder **Ctrl + Shift + Z**) für Wiederholen.
- **Alles auswählen:** Drücken Sie **Ctrl + A**.
- **Gitter umschalten:** Drücken Sie die Taste **G**, um die Gitterlinien ein- oder auszublenden.
- **Ansicht anpassen:** Drücken Sie die Taste **F**, um die Ansicht auf die Auswahl (oder alle Nodes, falls nichts ausgewählt ist) zu zentrieren.
- **Node umbenennen:** Wählen Sie einen Parameter-Node aus und drücken Sie **F2**.
- **Vollbild:** Drücken Sie **F11**, um den Vollbildmodus zu aktivieren/deaktivieren.

### Ausführungs-Workflow

1. **Kette initialisieren:** Der Node `> START` ist immer auf der Leinwand vorhanden.
2. **Befehls-Nodes hinzufügen:** Drücken Sie die **Leertaste** und fügen Sie Befehle hinzu (z. B. `-addFolder`, `-align` usw.).
3. **Ausführungspfad verknüpfen:** Verbinden Sie die pfeilförmigen Ausführungs-Sockets nacheinander, beginnend mit dem Ausgang des Nodes `> START`.
4. **Parameter konfigurieren:** Fügen Sie über das Suchmenü Parameter-Nodes (String, Integer, Float, File/Dir Path) hinzu und verbinden Sie deren Ausgänge mit den Eingängen der Befehls-Nodes.
5. **Ausführen:** Klicken Sie auf die Schaltfläche **> Launch** auf dem Node `> START`, um die Befehlskette in RealityCapture auszuführen.


## Projektstruktur

- `nodeRC.py` - Haupteinstiegspunkt.
- `canvas.py` - Logik des Haupteditorfensters.
- `scene.py` - Leinwandszene und Ereignisbehandlung für visuelle Elemente.
- `view.py` - Logik für Grafikansicht, Schwenken und Zoomen.
- `nodes_base.py` - Basisklassen für Nodes, Sockets und Verbindungen.
- `nodes_concrete.py` - Konkrete Implementierungen spezialisierter Nodes (Start-, Befehls- und Parameter-Nodes).
- `configuration.py` - Zentrale Quelle für Stile, UI-Einstellungen und Tastenkürzel.
- `search_menu.py` - Suchdialog mit automatischer Vervollständigung zum Erstellen von Nodes.
- `diagnostics.py` - Ausnahmebehandlung und Fehlerprotokollierung.
- `rc_documentation_extractor.py` - Dienstprogramm zum Erstellen der Befehlsdatenbank aus der lokalen RealityCapture-Dokumentation.

## Lizenz

Dieses Projekt wird "wie besehen" verteilt. Weitere Informationen finden Sie in den Projektdateien.

## Haftungsausschluss

Dieses Projekt ist ein unabhängiges, inoffizielles Open-Source-Tool und steht in keiner Verbindung zu Capturing Reality, Epic Games oder deren Tochtergesellschaften, wird nicht von diesen unterstützt, gesponsert oder ist anderweitig mit ihnen verbunden. "RealityCapture" und "RealityScan" sind Marken oder eingetragene Marken von Epic Games, Inc. oder seinen Tochtergesellschaften.
