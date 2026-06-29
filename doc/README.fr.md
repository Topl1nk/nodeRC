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

### Contrôles & Raccourcis

- **Déplacer le canevas :** Cliquez et maintenez le **bouton central de la souris (MMB)** et glissez.
- **Zoom :** Faites défiler la **molette de la souris**.
- **Ajouter un nœud :** Appuyez sur la touche **Espace** ou faites un **clic droit** sur un espace vide pour ouvrir le menu de recherche. Sélectionnez un nœud de commande ou de paramètre.
- **Connecter les ports (sockets) :** Glissez un lien depuis un port de sortie vers un port d'entrée compatible.
  - Glisser un lien depuis un port et le relâcher sur un espace vide ouvre le menu de recherche pour créer et connecter automatiquement un nouveau nœud.
- **Supprimer un nœud/connexion :** Sélectionnez l'élément et appuyez sur la touche **Suppr** (Delete).
- **Grouper des nœuds :** Sélectionnez les nœuds et appuyez sur **Ctrl + G** pour les encadrer.
- **Dupliquer des nœuds :** Sélectionnez les nœuds et appuyez sur **Ctrl + D**.
- **Copier / Coller :** Sélectionnez les nœuds et appuyez sur **Ctrl + C** pour copier, et **Ctrl + V** pour coller à la position du curseur.
- **Annuler / Rétablir :** Appuyez sur **Ctrl + Z** pour annuler et **Ctrl + Y** (ou **Ctrl + Shift + Z**) pour rétablir.
- **Sélectionner tout :** Appuyez sur **Ctrl + A**.
- **Afficher/Masquer la grille :** Appuyez sur la touche **G**.
- **Ajuster la vue :** Appuyez sur la touche **F** pour centrer la vue sur la sélection (ou sur tous les nœuds si rien n'est sélectionné).
- **Renommer un nœud :** Sélectionnez un nœud de paramètre et appuyez sur **F2**.
- **Plein écran :** Appuyez sur **F11** pour basculer en mode plein écran.

### Flux d'exécution

1. **Initialiser la chaîne :** Le nœud `> START` est toujours présent sur le canevas.
2. **Ajouter des nœuds de commande :** Appuyez sur **Espace** et ajoutez des commandes (ex. `-addFolder`, `-align`, etc.).
3. **Lier le chemin d'exécution :** Connectez séquentiellement les ports d'exécution (en forme de flèche) en partant de la sortie du nœud `> START`.
4. **Configurer les paramètres :** Ajoutez des nœuds de paramètres (String, Integer, Float, File/Dir Path) via le menu de recherche et connectez leur sortie aux ports d'entrée des nœuds de commande.
5. **Lancer :** Cliquez sur le bouton **> Launch** du nœud `> START` pour exécuter la chaîne dans RealityCapture.


## Structure du projet

- `nodeRC.py` - Point d'entrée principal.
- `canvas.py` - Logique de la fenêtre principale de l'éditeur.
- `scene.py` - Scène de canevas et gestion des événements des éléments visuels.
- `view.py` - Logique de vue graphique, panoramique et zoom.
- `nodes_base.py` - Classes de base pour les nœuds, les ports (sockets) et les connexions.
- `nodes_concrete.py` - Implémentations concrètes des nœuds spécialisés (nœuds Start, Command, Parameter).
- `configuration.py` - Source unique de vérité pour les styles, les paramètres d'interface et les raccourcis.
- `search_menu.py` - Boîte de dialogue de recherche avec saisie semi-automatique pour créer des nœuds.
- `diagnostics.py` - Gestionnaire d'exceptions et journalisation des erreurs.
- `rc_documentation_extractor.py` - Générateur de base de données de commandes à partir de la documentation locale de RealityCapture.

## Licence

Ce projet est distribué "tel quel". Consultez les fichiers du projet pour plus d'informations.

## Clause de non-responsabilité

Ce projet est un outil open-source indépendant et non officiel, et n'est pas affilié, approuvé, parrainé ou associé à Capturing Reality, Epic Games ou l'une de leurs filiales. "RealityCapture" et "RealityScan" sont des marques commerciales ou des marques déposées d'Epic Games, Inc. ou de ses filiales.
