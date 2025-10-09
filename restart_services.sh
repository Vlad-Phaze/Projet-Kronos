#!/bin/bash

# Script pour redémarrer l'API Kronos et le serveur web
echo "🔄 Arrêt des services existants..."

# Arrêt de tous les processus Python et serveurs web
pkill -f "python app.py" 2>/dev/null
pkill -f "python -m http.server" 2>/dev/null
lsof -ti:5002 | xargs kill -9 2>/dev/null
lsof -ti:3000 | xargs kill -9 2>/dev/null

echo "⏳ Attente de 2 secondes pour libérer les ports..."
sleep 2

echo "🚀 Démarrage de l'API Kronos (port 5002)..."
cd /Users/vladimirkronos/Downloads/Projet-Kronos-main/datafeed_tester
python app.py &
API_PID=$!

echo "🌐 Démarrage du serveur web (port 3000)..."
cd /Users/vladimirkronos/Downloads/Projet-Kronos-main/front
python -m http.server 3000 &
WEB_PID=$!

echo "⏳ Attente de 3 secondes pour le démarrage des services..."
sleep 3

echo ""
echo "✅ Services démarrés:"
echo "📡 API Kronos:     http://localhost:5002 (PID: $API_PID)"
echo "🌐 Interface Web:  http://localhost:3000/kronos-client.html (PID: $WEB_PID)"
echo ""
echo "🔍 Test de connectivité:"

# Test API
if curl -s http://localhost:5002/health > /dev/null; then
    echo "✅ API Kronos: OK"
else
    echo "❌ API Kronos: Erreur"
fi

# Test serveur web
if curl -s http://localhost:3000 > /dev/null; then
    echo "✅ Serveur Web: OK"
else
    echo "❌ Serveur Web: Erreur"
fi

echo ""
echo "🎯 Interface disponible sur: http://localhost:3000/kronos-client.html"
echo "📋 Pour arrêter les services: pkill -f 'python app.py' && pkill -f 'python -m http.server'"
