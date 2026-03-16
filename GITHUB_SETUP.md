# Heater+ auf GitHub veröffentlichen

## 1. Repo erstellen

1. Auf [github.com](https://github.com) einloggen
2. **New repository** → Name: `heater_plus`
3. **Create repository**

## 2. install.sh anpassen

In `install.sh` **DEIN_USERNAME** durch deinen GitHub-Benutzernamen ersetzen (Zeile 15).

## 3. Dateien pushen

```bash
cd ~/heater_plus
git init
git add heater_plus.py tcs3448.py hp_settings.json install_minimal.sh install.sh update.sh README.md
git add grafana_dashboard_*.json import_grafana_dashboard.sh  # optional
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/DEIN_USERNAME/heater_plus.git
git push -u origin main
```

## 4. Link an Tester schicken

**Installation (ein Befehl):**
```bash
curl -sSL https://raw.githubusercontent.com/DEIN_USERNAME/heater_plus/main/install.sh | bash
```

**Update (wenn du Änderungen gepusht hast):**
```bash
cd ~/heater_plus && ./update.sh
```

Oder: Tester führt den Install-Befehl erneut aus – er erkennt bestehende Installationen und macht nur `git pull`.

## 5. Dein Workflow

1. Änderungen machen
2. `git add . && git commit -m "..." && git push`
3. Tester ruft `./update.sh` auf (oder den Install-Einzeiler)
