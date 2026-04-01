# 🇲🇦 Mazouty — Déploiement Production

## Structure du dossier

```
mazouty-deploy/
├── main.py               # Backend FastAPI (production)
├── import_stations.py     # Import CSV → SQLite
├── requirements.txt       # Dépendances Python
├── Dockerfile             # Container Docker
├── .env.example           # Variables d'environnement
├── README.md              # Ce fichier
└── frontend/
    ├── index.html         # PWA frontend (production)
    └── manifest.json      # Manifest PWA
```

## Déploiement sur un VPS (Railway, Render, DigitalOcean...)

### Option A : Railway.app (le plus simple)

1. Crée un compte sur https://railway.app
2. Connecte ton GitHub
3. Push ce dossier sur GitHub
4. Railway détecte le Dockerfile automatiquement
5. Configure les variables d'environnement dans Railway :
   - `SECRET_KEY` = une clé aléatoire longue
   - `DOMAIN` = mazouty.site

### Option B : Render.com

1. Crée un compte sur https://render.com
2. New → Web Service → Connecte GitHub
3. Runtime : Docker
4. Configure les variables d'environnement

### Option C : VPS (DigitalOcean, Hetzner...)

```bash
# Sur le serveur
git clone TON_REPO
cd mazouty-deploy
cp .env.example .env
nano .env  # Modifier SECRET_KEY et DOMAIN

# Avec Docker
docker build -t mazouty .
docker run -d -p 8000:8000 --env-file .env -v ./data:/app/data mazouty

# Sans Docker
pip install -r requirements.txt
python -c "from main import init_db; init_db()"
python import_stations.py stations_casablanca.csv
gunicorn main:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

## Importer les stations

```bash
python import_stations.py stations_casablanca.csv
```

## Configurer le DNS (GoDaddy)

1. Va dans GoDaddy → Mes domaines → mazouty.site → DNS
2. Ajoute un enregistrement A :
   - Type : A
   - Nom : @
   - Valeur : IP de ton serveur
3. Ajoute un CNAME pour www :
   - Type : CNAME
   - Nom : www
   - Valeur : mazouty.site

## HTTPS (obligatoire)

Si tu utilises Railway/Render, HTTPS est automatique.
Si tu utilises un VPS, installe Caddy (le plus simple) :

```bash
# Installer Caddy
sudo apt install caddy

# Configurer /etc/caddy/Caddyfile
mazouty.site {
    reverse_proxy localhost:8000
}

sudo systemctl restart caddy
```

Caddy gère automatiquement le certificat SSL.

## Publier sur le Play Store

1. Va sur https://www.pwabuilder.com
2. Entre l'URL : https://mazouty.site/app
3. Clique "Package for stores" → Android
4. Télécharge l'APK/AAB
5. Va sur https://play.google.com/console
6. Crée un compte (25$)
7. Upload l'AAB et remplis les infos
