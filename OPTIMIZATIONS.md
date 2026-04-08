# 🚀 Optimisations de Performance - Kronos Backtester

## Date: 2026-04-08

### Résumé

Optimisations implémentées pour améliorer significativement la vitesse d'exécution du backtester sans modifier la logique métier.

---

## ✅ Optimisations Implémentées

### **Priorité 1 (Impact max, effort min)**

#### 1. **Pré-allocation des Arrays**
**Fichier:** `backtester_exact.py`

**Problème:** 
- Les `list.append()` Python sont lents car ils réallouent la mémoire à chaque ajout
- `capital_history`, `transactions`, `individual_positions` utilisaient des listes Python

**Solution:**
- Remplacement de `capital_history` par un array NumPy pré-alloué
- Utilisation d'un index `capital_event_idx` pour suivre la position
- Allocation estimative: `max_capital_events = n * 3`

**Gain estimé:** 20-30% sur la gestion de la mémoire

```python
# AVANT
capital_history = [parametres.initial_capital]
capital_history.append(capital_disponible)

# APRÈS
capital_history_array = np.full(max_capital_events, parametres.initial_capital, dtype=float)
capital_history_array[capital_event_idx] = capital_disponible
capital_event_idx += 1
```

---

#### 2. **Index Pré-calculés pour Multi-Asset**
**Fichier:** `backtester_exact.py` (fonction `backtest_smartbot_v2_multi_portfolio`)

**Problème:**
- `df.index.get_loc(timestamp)` appelé à chaque itération de la boucle
- Recherche coûteuse répétée des milliers de fois

**Solution:**
- Création d'une map `timestamp_to_idx` lors de la préparation des assets
- Accès direct O(1) au lieu de recherche O(log n)

**Gain estimé:** 10-15%

```python
# Pré-calcul au début
timestamp_to_idx = {ts: idx for idx, ts in enumerate(df.index)}

# Utilisation dans la boucle
idx = timestamp_map[timestamp]  # Au lieu de df.index.get_loc()
```

---

#### 3. **Cache Disque des Données Téléchargées**
**Fichier:** `datafeed_tester/fetcher.py`

**Problème:**
- Données re-téléchargées à chaque exécution
- Appels API lents et répétitifs

**Solution:**
- Système de cache basique avec pickle
- Stockage dans `__datacache__/`
- Expiration automatique après 24h
- Clé de cache: hash MD5 des paramètres (exchange, base, timeframe, dates)

**Gain estimé:** 50-70% sur la récupération des données (cache hit)

```python
cache_key = _get_cache_key(exchange_id, symbol, timeframe, since_ms, until_ms)
cached_data = _load_from_cache(cache_key)
if cached_data is not None:
    return cached_data
```

---

### **Priorité 2 (Impact élevé)**

#### 4. **Parallélisation du Fetching**
**Fichier:** `datafeed_tester/fetcher.py`

**Problème:**
- Téléchargement séquentiel des données de chaque exchange
- Temps d'attente cumulé pour chaque API call

**Solution:**
- Utilisation de `ThreadPoolExecutor` avec max 5 workers
- Téléchargement concurrent de tous les exchanges
- Récupération des résultats avec `as_completed()`

**Gain estimé:** 50-70% sur la phase de fetching (sans cache)

```python
with ThreadPoolExecutor(max_workers=min(len(ex_list), 5)) as executor:
    future_to_exchange = {executor.submit(fetch_for_exchange, ex): ex for ex in ex_list}
    for future in as_completed(future_to_exchange):
        result = future.result()
```

---

#### 5. **Vectorisation des Signaux d'Entrée**
**Fichier:** `backtester_exact.py`

**Problème:**
- Calcul du signal d'entrée à chaque itération de la boucle
- Appels répétés à `evaluer_entry_signal(indicators, t, parametres)`

**Solution:**
- Nouvelle fonction `evaluer_entry_signal_vectorized()` 
- Calcul de tous les signaux en une seule passe avant la boucle
- Utilisation d'opérations NumPy vectorisées (&, |)

**Gain estimé:** 20-30% sur la détection de signaux

```python
# Pré-calcul avant la boucle
entry_signals = evaluer_entry_signal_vectorized(indicators, parametres)

# Dans la boucle
entry_signal = entry_signals[t]  # Au lieu de evaluer_entry_signal()
```

---

## 📊 Gain Total Estimé

| Optimisation | Gain |
|-------------|------|
| Pré-allocation arrays | 20-30% |
| Index pré-calculés | 10-15% |
| Cache disque | 50-70% (cache hit) |
| Parallélisation fetching | 50-70% (sans cache) |
| Vectorisation signaux | 20-30% |

**🎯 Gain cumulé attendu: 2x à 3x plus rapide**

---

## 🔧 Configuration

### Cache
- **Activation:** `CACHE_ENABLED = True` dans `fetcher.py`
- **Dossier:** `__datacache__/` (ajouté au .gitignore)
- **Expiration:** 24 heures
- **Format:** Pickle (pandas DataFrame)

### Parallélisation
- **Workers:** min(nombre_exchanges, 5)
- **Type:** ThreadPoolExecutor (I/O-bound)

---

## ⚠️ Points d'Attention

### Limitations du Cache
- Cache invalide si les paramètres changent
- Nettoyage manuel nécessaire si problème
- Peut consommer de l'espace disque

### Thread Safety
- Les compteurs globaux utilisent des locks (`_api_call_lock`)
- Le cache utilise des fichiers séparés par clé

---

## 🧪 Tests Recommandés

1. **Test de régression:** Vérifier que les résultats sont identiques
2. **Test de performance:** Comparer les temps d'exécution avant/après
3. **Test du cache:** Vérifier les cache hits/misses
4. **Test multi-asset:** Valider les index pré-calculés

---

## 📝 Notes de Développement

- Toutes les optimisations préservent la logique métier exacte
- Les résultats numériques doivent être identiques
- Les logs incluent maintenant "💾 CACHE HIT" pour traçabilité
- Les arrays pré-alloués ont une estimation large pour éviter les dépassements

---

## 🚀 Optimisations Futures (Non implémentées)

### Priorité 3 (Avancé)
1. **Remplacement pandas_ta par NumPy pur** - Gain: 30-40%
2. **Génération différée des graphiques** - Gain: 15-20%
3. **Compilation JIT avec Numba** - Gain: 50-100%
4. **Caching des indicateurs pré-calculés** - Gain: 20-30%

---

## 📚 Références

- NumPy Broadcasting: https://numpy.org/doc/stable/user/basics.broadcasting.html
- ThreadPoolExecutor: https://docs.python.org/3/library/concurrent.futures.html
- Pickle Protocol: https://docs.python.org/3/library/pickle.html
