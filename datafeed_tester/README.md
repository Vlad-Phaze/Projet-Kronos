# 🚀 API Kronos - Backtesteur DCA

Une API complète pour tester et analyser des stratégies DCA (Dollar Cost Averaging) avec RSI et Bollinger Bands.

## 🎯 Fonctionnalités

- ✅ **Santé du service** : Vérification du statut de l'API
- ✅ **Ingestion de données** : Chargement et scoring automatique des données financières
- ✅ **Backtesting avancé** : Test de stratégies DCA avec séparation IS/OOS
- ✅ **Rapports HTML** : Génération de rapports complets avec graphiques
- ✅ **Interface de test** : Documentation interactive pour tester l'API

## 🚦 Démarrage rapide

### 1. Prérequis

```bash
# Activer l'environnement conda
conda activate kronos

# Vérifier les dépendances
pip list | grep -E "(flask|pandas|yfinance|backtesting)"
```

### 2. Lancer l'API

```bash
cd datafeed_tester
python app.py
```

L'API sera disponible sur : **http://localhost:5000**

### 3. Tester en 3 étapes

1. **Ouvrir la documentation** : http://localhost:5000
2. **Cliquer sur "Tester avec BTC"** pour charger des données
3. **Suivre la chaîne** : Ingest → Backtest → Rapport

## 🔌 Routes API

### GET /health
Vérifier que le service tourne
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

### POST /ingest-score
Charger et scorer des données
```json
{
  "assets": ["BTC-USD", "ETH-USD"],
  "timeframe": "1d",
  "start_date": "2023-01-01",
  "end_date": "2024-01-01"
}
```

### POST /backtest
Lancer un backtest DCA
```json
{
  "dataset_id": "uuid-from-ingest",
  "symbol": "BTC-USD",
  "strategy_params": {
    "rsi_length": 14,
    "rsi_entry": 30,
    "rsi_exit": 75,
    "so_max": 4
  }
}
```

### POST /report
Générer un rapport HTML
```json
{
  "run_id": "uuid-from-backtest"
}
```

## 📊 Exemple de workflow complet

```bash
# 1. Charger des données BTC
curl -X POST http://localhost:5000/ingest-score \
  -H "Content-Type: application/json" \
  -d '{
    "assets": ["BTC-USD"],
    "timeframe": "1d",
    "start_date": "2023-09-01",
    "end_date": "2024-09-01"
  }'

# 2. Lancer le backtest (utiliser le dataset_id retourné)
curl -X POST http://localhost:5000/backtest \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "votre-dataset-id",
    "symbol": "BTC-USD",
    "strategy_params": {
      "rsi_length": 14,
      "rsi_entry": 30,
      "rsi_exit": 75,
      "so_max": 4,
      "base_amount": 1000
    }
  }'

# 3. Générer le rapport (utiliser le run_id retourné)
curl -X POST http://localhost:5000/report \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "votre-run-id"
  }'
```

## 🎨 Contenu du rapport HTML

Le rapport généré contient :

- **📊 Résumé des métriques** : Return, Sharpe, Max Drawdown
- **📈 Graphiques** : Courbe d'equity et drawdown
- **📅 Performance mensuelle** : Tableau des returns par mois
- **🏆 Top/Worst trades** : 5 meilleurs et 5 pires trades
- **🔍 Analyse IS/OOS** : Comparaison In-Sample vs Out-Of-Sample
- **📋 Annexe technique** : Paramètres et métadonnées

## ⚙️ Configuration de la stratégie DCA

```python
{
  "rsi_length": 14,        # Période RSI
  "rsi_entry": 30,         # Seuil d'entrée RSI
  "rsi_exit": 75,          # Seuil de sortie RSI
  "bb_length": 20,         # Période Bollinger Bands
  "bb_std": 3,             # Écart-type BB
  "bbp_trigger": 0.2,      # Seuil BB% pour entrée
  "so_max": 4,             # Nombre max de Safety Orders
  "so_step": 0.0021,       # Distance entre SO (2.1%)
  "base_amount": 1000      # Montant de base ($)
}
```

## 🔧 Dépannage

### Problème de démarrage
```bash
# Vérifier l'environnement
conda list
pip install -r requirements.txt
```

### Port déjà utilisé
```bash
# Tuer le processus existant
lsof -ti:5000 | xargs kill -9
```

### Données manquantes
- Vérifier la connexion Internet pour yfinance
- Essayer avec des dates plus récentes
- Utiliser des symboles valides (BTC-USD, ETH-USD, AAPL, etc.)

## 📁 Structure des fichiers

```
datafeed_tester/
├── app.py              # API principale
├── requirements.txt    # Dépendances
├── utils_sanitize.py   # Utilitaires
└── core/
    └── types.py        # Types et interfaces
```

## 🚀 Déploiement sur Render

Pour déployer sur Render :

1. **Créer un repository Git** avec le code
2. **Connecter à Render** et choisir "Web Service"
3. **Build Command** : `pip install -r requirements.txt`
4. **Start Command** : `python app.py`
5. **Environment** : Python 3.12

Variables d'environnement suggérées :
```
FLASK_ENV=production
PORT=5000
```

## 📈 Exemples de résultats

Avec les paramètres par défaut sur BTC-USD (2023-2024) :
- **Return IS** : ~75%
- **Return OOS** : ~45%
- **Sharpe Ratio** : ~0.8
- **Max Drawdown** : ~20%

## 🆘 Support

Pour toute question ou problème :
1. Vérifier les logs dans le terminal
2. Tester les routes individuellement
3. Consulter la documentation interactive sur http://localhost:5000

---

✨ **API Kronos v0.1.0** - Backtesteur DCA professionnel
