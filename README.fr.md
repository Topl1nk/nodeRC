# NodeRC

[English](README.md) | [Русский](README.ru.md) | [Español](README.es.md) | [中文](README.zh.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [日本語](README.ja.md) | [हिन्दी](README.hi.md) | [Português](README.pt.md) | [العربية](README.ar.md)

NodeRC est un éditeur visuel basé sur des nœuds, écrit en Python avec PyQt5. Le projet vous permet de créer, connecter et gérer des nœuds sur un canevas interactif, offrant une interface conviviale pour la programmation visuelle ou la construction de graphes logiques.

## Fonctionnalités
- **Canevas interactif :** Un espace de travail infini avec prise en charge du panoramique et du zoom.
- **Architecture des nœuds :** Différents types de nœuds prenant en charge les connexions entrantes et sortantes (sockets).
- **Connexions dynamiques :** Liaison visuelle des ports d'exécution et des ports de données.
- **Système de configuration :** Couleurs, tailles et styles personnalisables via un fichier de configuration centralisé.
- **Menu de recherche :** Un menu pratique pour ajouter rapidement de nouveaux nœuds au canevas.

## Exigences
- Python 3.7+
- PyQt5

## Installation

1. Clonez le dépôt :
   ```bash
   git clone <URL_du_dépôt>
   cd nodeRC
   ```

2. Installez les dépendances :
   ```bash
   pip install -r requirements.txt
   ```

## Utilisation
Pour lancer l'éditeur, exécutez :
```bash
python nodeRC.py
```

## Structure du projet
- `nodeRC.py` - Point d'entrée principal.
- `canvas.py` - Logique du canevas interactif et gestion du graphe.
- `nodes.py` - Classes de base et spécialisées pour les nœuds et les sockets.
- `configuration.py` - Fichier de configuration (couleurs, styles, paramètres d'interface).
- `search_menu.py` - Boîte de dialogue pour rechercher et ajouter des nœuds.
- `diagnostics.py` - Journalisation et gestion des exceptions.
- `rc_documentation_extractor.py` - Utilitaire pour extraire la documentation des commandes.

## Licence
Ce projet est distribué "tel quel". Consultez les fichiers du projet pour plus d'informations.
