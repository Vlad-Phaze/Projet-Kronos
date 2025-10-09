# 🚀 KRONOS BACKTESTER - Interface React

## Installation et Démarrage

### 1. Installation des dépendances
```bash
cd front/react-app
npm install
```

### 2. Démarrage de l'interface
```bash
npm start
```

L'interface sera disponible sur `http://localhost:3000`

## Architecture

### 🎨 Style Cyberpunk
- **Thème sombre** inspiré des interfaces d'agent/hacker
- **Couleurs** : vert acide (#00ff88), bleu électrique (#58a6ff)
- **Typographie** : JetBrains Mono (monospace)
- **Animations** : effets de lueur, scan lines

### 📱 Interface en 3 Panneaux
1. **Sidebar (Gauche)** : Configuration complète
   - Paramètres Fetcheur (coin, exchanges, dates)
   - Paramètres Stratégie DCA (RSI, BB, Safety Orders)
   - Paramètres Backtester (capital, commission)
   - Code Python personnalisé

2. **Main (Centre)** : Dashboard principal
   - Métriques de performance
   - Graphiques d'équité
   - Bouton téléchargement rapport

3. **Status (Droite)** : Monitoring temps réel
   - État du système
   - Journal d'activité
   - Performances

### 🔌 API Integration
L'interface communique avec votre API Flask sur `http://localhost:5002`

### 📄 Rapport HTML
Le rapport final conserve le même style cyberpunk pour la cohérence visuelle.

## Paramètres Disponibles

### Fetcheur
- Coin : BTC, ETH, ADA, SOL, MATIC
- Exchanges : binance, coinbase, kraken, kucoin
- Période de test : dates début/fin

### Stratégie DCA
- RSI : length, entry, exit
- Bollinger Bands : length, std, trigger
- Safety Orders : max, step, volume scale, step scale
- Take Profit minimum
- Direction : long/short

### Backtester
- Capital initial
- Commission
- Code Python personnalisé pour stratégies

## Production
Pour déployer en production :
```bash
npm run build
```

Les fichiers statiques seront dans le dossier `build/`
