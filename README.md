# Advanced Car Deal Scraper

Ce projet surveille plusieurs marketplaces de voitures d'occasion et envoie des notifications Telegram lorsqu'une bonne affaire est détectée.

## Structure du projet

- `main.py` : point d'entrée principal, boucle de scrapping continue
- `scraper/` : conteneur des scrapers par site
  - `autoscout.py`
  - `mobilede.py`
  - `leboncoin.py`
- `utils/` : fonctions utilitaires
  - `filters.py`
  - `database.py`
  - `notifier.py`
  - `pricing.py`
  - `models.py`
- `requirements.txt` : dépendances Python

## Prérequis

- Python 3.10+
- `pip`
- Un bot Telegram et un identifiant de chat

## Installation

1. Créez un environnement virtuel (recommandé) :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Installez les dépendances :

```powershell
pip install -r requirements.txt
```

## Configuration Telegram

1. Ouvrez Telegram et discutez avec le bot `@BotFather`.
2. Créez un nouveau bot et récupérez le `TELEGRAM_BOT_TOKEN`.
3. Récupérez votre `TELEGRAM_CHAT_ID` :
   - Ajoutez le bot au chat ou envoyez-lui un message.
   - Utilisez une API de test comme `https://api.telegram.org/bot<token>/getUpdates` ou un bot tiers ID finder.

4. Configurez les variables d'environnement :

```powershell
$env:TELEGRAM_BOT_TOKEN = "votre_token"
$env:TELEGRAM_CHAT_ID = "votre_chat_id"
```

Sur Linux/macOS :

```bash
export TELEGRAM_BOT_TOKEN="votre_token"
export TELEGRAM_CHAT_ID="votre_chat_id"
```

## Exécution

Lancez l'application avec :

```powershell
python main.py
```

Le programme tourne en boucle et relance le scrapping toutes les ~2 heures.

## Comportement principal

- Scrape AutoScout24, Mobile.de et Leboncoin
- Filtre les annonces selon des mots-clés spécifiques
- Ne notifie qu'une seule fois chaque annonce
- Calcule un score de deal et envoie une alerte Telegram
- Stocke les annonces vues dans une base SQLite `car_alerts.db`

## Fichiers importants

- `car_alerts.db` : base SQLite utilisée pour mémoriser les annonces déjà notifiées
- `requirements.txt` : dépendances à installer

## Remarques

- Les URLs de recherche et les sélecteurs HTML peuvent évoluer selon les sites.
- Si un site change sa structure, adaptez le scraper correspondant.
- Le bot respecte des délais aléatoires et des en-têtes pour réduire les risques de blocage.
