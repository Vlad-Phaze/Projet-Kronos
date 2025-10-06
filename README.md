# API Kronos - Backtesteur DCA

## Comment tester en 3 étapes

### 1. Démarrer l'API
```bash
cd datafeed_tester
conda activate kronos
python app.py
```

### 2. Ouvrir la documentation
Ouvrez dans votre navigateur : `front/index.html`

### 3. Tester les 4 routes
- **GET /health** - Vérifier le statut
- **POST /ingest-score** - Analyser la qualité des données
- **POST /backtest** - Exécuter un backtest DCA  
- **POST /report** - Générer un rapport HTML avec graphiques

## Résultats attendus

✅ **Page de docs** : Interface avec boutons de test  
✅ **4 routes** : Toutes fonctionnelles  
✅ **Rapport HTML** : Graphiques professionnels (bougies, equity, trades)  
✅ **KPIs** : Métriques de performance du backtest

L'API tourne sur **http://localhost:5002**
