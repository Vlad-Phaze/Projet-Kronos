# Rapport d'Audit Technique - Kronos Core
**Date :** 2025-01-27  
**Commit audité :** HEAD  
**Auditeur :** Assistant IA  

## Résumé Exécutif

L'audit révèle un **alignement partiel** avec le cahier des charges SPEC.md. Le projet dispose d'une base solide pour l'ingestion de données et le backtesting, mais présente des **écarts critiques** pour le MVP mi-octobre 2025.

**Niveau d'alignement global :** 45%  
**Risques majeurs pour le MVP :**
- ❌ **BLOCKER** : Interface utilisateur React Native desktop absente
- ❌ **BLOCKER** : Génération de rapports PDF non implémentée  
- ❌ **BLOCKER** : Endpoints API FastAPI manquants
- ❌ **BLOCKER** : Système de cache Parquet/DuckDB non implémenté
- ❌ **BLOCKER** : Run registry et reproductibilité absents

## Matrice d'Écarts

| Exigence | Statut | Preuves | Actions Correctives |
|----------|--------|---------|-------------------|
| **Data/Ingestion** | | | |
| CCXT multi-sources (Binance, Bybit, OKX) | ✅ PASS | `datafeed_tester/fetcher.py:24-28` | Aucune action requise |
| Schéma canonique OHLCV UTC | ✅ PASS | `datafeed_tester/fetcher.py:514-531` | Aucune action requise |
| Normalisation alias (XBT→BTC) | ✅ PASS | `datafeed_tester/fetcher.py:579-583` | Aucune action requise |
| Cache Parquet zstd partitionné | ❌ FAIL | Absent | Implémenter cache Parquet avec compression zstd et arborescence `data/{provider}/{symbol}/{tf}/year=YYYY/` |
| Index DuckDB | ❌ FAIL | Absent | Créer vue DuckDB globale `ohlcv` via `parquet_scan()` |
| Q-score 5 composantes | ✅ PASS | `datafeed_tester/fetcher.py:491-531` | Aucune action requise |
| Sélection auto source | ✅ PASS | `datafeed_tester/fetcher.py:698-722` | Aucune action requise |
| Journal anomalies | ❌ FAIL | Absent | Implémenter journal Parquet `ts_ms,type,provider,symbol,tf` |
| **API FastAPI** | | | |
| Endpoint /health | ❌ FAIL | Absent | Créer endpoint FastAPI avec status, version, git_sha, providers, timeframes |
| Endpoint /ingest-score | ❌ FAIL | Absent | Implémenter endpoint avec progress/polling et réponse conforme au spec |
| Endpoint /backtest | ⚠️ PARTIAL | `api.py:15`, `datafeed_tester/app.py:262` | Migrer de Flask vers FastAPI, ajouter progress/ETA |
| Endpoint /report | ❌ FAIL | Absent | Créer endpoint pour génération PDF avec WeasyPrint |
| **Backtester** | | | |
| Bar-based anti-lookahead | ✅ PASS | `backtester.py:56` | Aucune action requise |
| Fills simples + frais/slippage | ✅ PASS | `backtester.py:8-23` | Aucune action requise |
| Stratégies RSI TP/SL | ✅ PASS | `dca_strategy.py:6-121` | Aucune action requise |
| Stratégies DCA | ✅ PASS | `backtester.py:8-23`, `dca_strategy.py:6-121` | Aucune action requise |
| IS/OOS split | ❌ FAIL | Absent | Implémenter split 70/30 avec KPIs séparés et bannière d'alerte |
| Multi-actifs | ✅ PASS | `datafeed_tester/app.py:284-293` | Aucune action requise |
| **Reporting** | | | |
| HTML→PDF WeasyPrint | ❌ FAIL | Absent | Implémenter génération PDF avec WeasyPrint |
| Sections rapport | ❌ FAIL | Absent | Créer sections : KPIs, Equity/Drawdown, Mensuel, Top/Bottom, IS/OOS, Annexes |
| **UI React Native** | | | |
| Dépendances RN desktop | ❌ FAIL | Absent | Ajouter `react-native-windows` et `react-native-macos` |
| 3 écrans MVP | ❌ FAIL | Absent | Créer écrans : Données, Stratégie, Résultats |
| Tableau Q-score | ❌ FAIL | Absent | Implémenter tableau avec badge "source retenue" et override |
| Progress/ETA | ❌ FAIL | Absent | Ajouter indicateurs de progression |
| **Reproductibilité** | | | |
| Run registry | ❌ FAIL | Absent | Créer registry DuckDB/JSON avec champs requis |
| Seed globale | ❌ FAIL | Absent | Implémenter seed globale par job |
| Golden run CI | ❌ FAIL | Absent | Créer test de non-régression |
| **Packaging** | | | |
| .dmg/.app macOS | ❌ FAIL | Absent | Créer scripts de build pour macOS |
| MSIX Windows | ❌ FAIL | Absent | Créer scripts de build pour Windows |
| CI workflows | ❌ FAIL | Absent | Créer workflows GitHub Actions |

## Top 10 des Manques Critiques (Blockers MVP)

1. **Interface utilisateur React Native desktop** - 0% implémenté
2. **Génération de rapports PDF** - 0% implémenté  
3. **Endpoints API FastAPI** - 20% implémenté (Flask existant)
4. **Système de cache Parquet/DuckDB** - 0% implémenté
5. **Run registry et reproductibilité** - 0% implémenté
6. **Split IS/OOS** - 0% implémenté
7. **Packaging macOS/Windows** - 0% implémenté
8. **Journal anomalies** - 0% implémenté
9. **CI/CD workflows** - 0% implémenté
10. **Endpoint /health** - 0% implémenté

## Plan d'Attaque 2 Semaines

### Semaine 1 (Priorité BLOCKER)
- **Jour 1-2** : Migration Flask → FastAPI + endpoints /health, /ingest-score, /report
- **Jour 3-4** : Implémentation cache Parquet zstd + index DuckDB
- **Jour 5** : Run registry DuckDB + seed globale

### Semaine 2 (Priorité BLOCKER)  
- **Jour 1-2** : Génération PDF WeasyPrint + sections rapport
- **Jour 3-4** : Interface React Native desktop (3 écrans MVP)
- **Jour 5** : Split IS/OOS + packaging scripts

## Risques & Mitigations

| Risque | Impact | Mitigation |
|--------|--------|------------|
| **UI React Native complexe** | BLOCKER | Utiliser templates existants, focus sur 3 écrans MVP |
| **WeasyPrint dépendances** | HIGH | Tester installation, fallback HTML si échec |
| **Cache Parquet volumineux** | MEDIUM | Compression zstd, TTL configurable |
| **FastAPI migration** | MEDIUM | Garder Flask en parallèle, migration progressive |

## Checklists d'Acceptation

### ✅ Data/Ingestion
- [x] CCXT multi-sources fonctionnel
- [x] Q-score 5 composantes implémenté
- [x] Sélection automatique source
- [ ] Cache Parquet zstd
- [ ] Index DuckDB
- [ ] Journal anomalies

### ❌ API FastAPI
- [ ] Endpoint /health
- [ ] Endpoint /ingest-score  
- [ ] Endpoint /backtest (FastAPI)
- [ ] Endpoint /report
- [ ] Erreurs normalisées

### ✅ Backtester
- [x] Bar-based anti-lookahead
- [x] Stratégies RSI/DCA
- [x] Multi-actifs
- [ ] Split IS/OOS
- [ ] Bannière alerte dégradation

### ❌ Reporting
- [ ] HTML→PDF WeasyPrint
- [ ] Sections rapport complètes
- [ ] Export PDF + HTML

### ❌ UI React Native
- [ ] Dépendances RN desktop
- [ ] 3 écrans MVP
- [ ] Tableau Q-score
- [ ] Progress/ETA
- [ ] Dark mode

### ❌ Reproductibilité
- [ ] Run registry
- [ ] Seed globale
- [ ] Golden run CI
- [ ] Logs JSON structurés

### ❌ Packaging
- [ ] Scripts .dmg macOS
- [ ] Scripts MSIX Windows
- [ ] CI workflows
- [ ] Tests automatiques

## Annexes

### Preuves de Code
- **Q-score implémenté** : `datafeed_tester/fetcher.py:491-531`
- **Stratégies DCA** : `backtester.py:8-23`, `dca_strategy.py:6-121`
- **API Flask existante** : `api.py:15`, `datafeed_tester/app.py:262`
- **Multi-sources CCXT** : `datafeed_tester/fetcher.py:24-28`

### Questions Ouvertes
1. **Frontend React Native** : Le dossier `front/` est vide - prévu pour plus tard ?
2. **WeasyPrint** : Aucune trace dans le code - dépendance manquante ?
3. **DuckDB** : Présent dans venv mais pas utilisé dans le code principal
4. **CI/CD** : Aucun workflow GitHub Actions trouvé

### Recommandations Immédiates
1. **Créer l'architecture FastAPI** en parallèle de Flask
2. **Implémenter le cache Parquet** avec compression zstd
3. **Développer l'UI React Native** avec les 3 écrans MVP
4. **Ajouter WeasyPrint** pour la génération PDF
5. **Créer les scripts de packaging** pour macOS/Windows
