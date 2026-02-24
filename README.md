# CarryBot

[Français](README.md) | [中文](README_CN.md)

## Présentation
CarryBot est un robot d’assistance pour le transport d’objets légers en intérieur, avec franchissement de petites marches.
Le cœur logiciel est `detect_stairs.py`, qui combine perception (caméra RealSense), décision, serveur web/API et commande moteur.

## Fonctionnalités principales
- Détection en temps réel de l’environnement : mur, montée d’escalier, descente.
- Flux vidéo MJPEG en direct via navigateur.
- API HTTP unifiée pour pilotage, télémétrie et réglage des paramètres.
- Contrôle moteur via MegaPi (roues, mécanisme Tri-Star, vérin).
- Paramètres modifiables à chaud (`/params`) avec persistance en fichier.

## Architecture technique
- `detect_stairs.py`
  - pipeline RealSense (profondeur + couleur)
  - logique de détection (ROI, filtrage, classification)
  - serveur HTTP (`http.server` + `socketserver`)
  - endpoints de contrôle et streaming vidéo
- `motor_control/motor_driver.py`
  - communication série (`pyserial`) avec MegaPi
  - commandes roues/Tri-Star/vérin
  - parsing de télémétrie (`IMU:`, `ULTRA:`)
- `motor_control/motor_control.ino`
  - contrôle bas niveau des moteurs
  - gestion IMU/ultrason
  - logique d’exécution temps réel

## API rapide
Base URL : `http://<ROBOT_IP>:8080`

- `GET /` : interface web
- `GET /video_feed` : flux MJPEG
- `GET /health` : état service / moteur / verrous
- `GET /params` : paramètres courants
- `POST /params` : mise à jour des paramètres
- `POST /drive` : actions haut niveau (`forward`, `backward`, `left`, `right`, `up`, `down`, `stop`, etc.)
- `POST /wheels` : commande roues en RPM (globale ou gauche/droite)
- `POST /tristar` : commande Tri-Star
- `POST /stop` : arrêt

Documentation API détaillée : `docs/README_APP_API.md`

## Installation
Prérequis : Python 3.11 recommandé.

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

## Lancement
```bash
python detect_stairs.py
```
Puis ouvrir : `http://<ROBOT_IP>:8080`

## Paramètres
- Fichier de configuration : `config/config.json`
- Priorité des paramètres : CLI > variables d’environnement > fichier > défauts
- Variables d’environnement : préfixe `CARRYBOT_` (ex: `CARRYBOT_ROI_H_START`)

Documentation paramètres : `docs/README_STAIR_PARAMS.md`

## Tests
```bash
pytest -q
```
Tests clés : `tests/test_config_and_api.py`, `tests/test_smoke.py`

## Outils utiles
- Console série manuelle :
```bash
python3 tools/serial_console.py --port /dev/ttyUSB0
```

## Structure du dépôt (extrait)
- `detect_stairs.py`
- `motor_control/`
- `web/templates/`
- `config/`
- `docs/`
- `tests/`
- `tools/`

## Remarques
- Le service moteur HTTP séparé n’est plus requis : les endpoints moteur sont intégrés dans `detect_stairs.py`.
- Pour un démarrage automatique au boot sur Raspberry Pi, utiliser un service `systemd`.
