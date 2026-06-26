# NodeRC

![Screenshot](images/Screenshot.png)

[English](../README.md) | [Українська](README.uk.md) | [Español](README.es.md) | [中文](README.zh.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [日本語](README.ja.md) | [हिन्दी](README.hi.md) | [Português](README.pt.md) | [العربية](README.ar.md)

NodeRC est une interface visuelle et un éditeur non officiel basé sur des nœuds pour les commandes CLI de RealityCapture / RealityScan. Écrit en Python avec PyQt5, le projet vous permet de connecter et de gérer visuellement les nœuds de commande sur un canevas interactif, offrant une interface conviviale pour l'automatisation des flux de travail.

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

## Clause de non-responsabilité

Ce projet est un outil open-source indépendant et non officiel, et n'est pas affilié, approuvé, parrainé ou associé à Capturing Reality, Epic Games ou l'une de leurs filiales. "RealityCapture" et "RealityScan" sont des marques commerciales ou des marques déposées d'Epic Games, Inc. ou de ses filiales.
