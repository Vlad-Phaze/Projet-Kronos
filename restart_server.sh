#!/bin/bash
# Script pour redémarrer le serveur Flask Kronos

echo "🛑 Arrêt du serveur Flask..."

# Méthode 1: Via le port
PID_PORT=$(lsof -ti:5002)
if [ ! -z "$PID_PORT" ]; then
    echo "   Processus trouvé via port 5002: $PID_PORT"
    kill -9 $PID_PORT 2>/dev/null
    sleep 1
fi

# Méthode 2: Via le nom du processus
pkill -9 -f "python.*app.py"
sleep 2

# Vérifier si le processus est bien arrêté
if ps aux | grep "python.*app.py" | grep -v grep > /dev/null; then
    echo "   ⚠️  Processus toujours actif, tentative avec pkill -9"
    pkill -9 python
    sleep 2
fi

echo "✅ Serveur arrêté"
echo ""
echo "🚀 Démarrage du nouveau serveur..."

cd /Users/vladimirkronos/Downloads/Projet-Kronos-main
./venv312/bin/python datafeed_tester/app.py > /tmp/kronos-flask.log 2>&1 &
NEW_PID=$!

echo "✅ Serveur démarré (PID: $NEW_PID)"
echo ""
echo "📋 Attente du démarrage (3 secondes)..."
sleep 3

echo ""
echo "📊 Derniers logs:"
tail -20 /tmp/kronos-flask.log

echo ""
echo "✅ Serveur accessible sur: http://localhost:5002/upload_strategy.html"
