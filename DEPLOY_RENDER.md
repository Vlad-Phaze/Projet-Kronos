# Deploiement Render (Backend + Frontend)

Ce projet est pret pour Render avec deux services:

- `kronos-back` (Web Service Python)
- `kronos-front` (Static Site)

## 1) Preparer le repository

1. Creer un repo GitHub avec le contenu de `Projet-Kronos`.
2. Verifier que les fichiers suivants sont pushes:
   - `render.yaml`
   - `datafeed_tester/requirements.txt`
   - `datafeed_tester/app.py`
   - dossier `front/`

## 2) Deploiement automatique via Blueprint

1. Ouvre Render puis **New +** -> **Blueprint**.
2. Connecte ton repo.
3. Render detecte `render.yaml` et propose 2 services.
4. Lance le deploy.

## 3) Verification backend

Quand `kronos-back` est en ligne, teste:

- `https://kronos-back.onrender.com/health`

Tu dois voir un JSON avec `"status": "ok"`.

## 4) Verification frontend

Quand `kronos-front` est en ligne:

- Ouvre l'URL du site statique fournie par Render.
- Va sur `index.html` puis lance un test dans `configure_smartbot.html` ou `run_multi_smartbot.html`.

## 5) Important: nom de service backend

Le frontend appelle par defaut:

- `https://kronos-back.onrender.com`

Si tu choisis un autre nom de service Render, remplace cette URL dans:

- `front/configure_smartbot.html`
- `front/configure_smartbot_stocks.html`
- `front/run_multi.html`
- `front/run_multi_smartbot.html`
- `front/run_multi_smartbot_stocks.html`

## 6) Notes utiles

- Le backend lit automatiquement `PORT` (obligatoire sur Render).
- Le serveur de prod utilise `gunicorn`.
- Le CORS est actif dans Flask (`CORS(app)`), donc front et back peuvent etre sur deux domaines differents.
