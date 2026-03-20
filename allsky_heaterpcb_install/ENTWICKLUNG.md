# Entwicklung: `~/heater_plus` ↔ Paket `allsky_heaterpcb_install` (GitHub)

## Dein Workflow (so ist es gedacht)

1. **Bearbeiten und testen** mit den Dateien unter **`~/heater_plus/`**  
   (`heater_plus.py`, `tcs3448.py`, ggf. `allsky_heaterplussettings.py` – dort läuft dein Test.)

2. Wenn diese Dateien **auch im Install-/Paketordner** liegen (`allsky_heaterpcb_install/` im Repo), sollen sie **dort dieselbe Version** haben, damit du **`git push`** machen kannst und andere Nutzer die Änderungen ziehen.

3. **Vor Commit / Push** aus dem Paketordner ausführen:

```bash
cd ~/heater_plus/allsky_heaterpcb_install   # oder dein Pfad zum Paket
./sync_dev_to_package.sh
```

Das kopiert **`~/heater_plus/` → `allsky_heaterpcb_install/`** für:

- `heater_plus.py`
- `tcs3448.py`
- `allsky_heaterplussettings.py`

Dann: `git status`, `git commit`, `git push`.

---

## Symlinks vs. echte Kopien in `~/heater_plus`

- **Standard-Install** kann Symlinks legen, wenn das Repo unter `~/heater_plus/...` liegt – dann ist „Bearbeiten im Paket“ = Laufzeit (anderer Workflow).

- **Dein Workflow** (nur in `~/heater_plus` editieren): Install mit **echten Kopien** erzwingen:

```bash
HEATER_PLUS_USE_SYMLINKS=0 sudo ./install_allsky_heaterpcb.sh
```

Dann sind `~/heater_plus/heater_plus.py` usw. **normale Dateien**; du änderst sie dort, und **`sync_dev_to_package.sh`** schreibt sie vor dem Push ins Repo.

---

## Gegenrichtung: Paket → Laufzeit (z. B. nach `git pull`)

Wenn jemand **andere** Änderungen aus Git holt und `~/heater_plus` aktualisieren will:

```bash
./sync_heater_plus_runtime.sh
```

---

## Nicht ins Repo spiegeln (lokal bleiben)

- **`hp_settings.json` im Paket** bleibt die **öffentliche Vorlage** (Platzhalter-Token). `sync_dev_to_package.sh` kopiert **keine** `hp_settings.json` vom Pi ins Paket – sonst riskierst du ein echtes Token im Commit.
- Analyse-Hilfen (`compare_measured_vs_weather.py`, `SPEKTRUM_ANALYSE.md`, …) – siehe Root-**`.gitignore`**.

## Technik

| Skript | Richtung |
|--------|----------|
| `sync_dev_to_package.sh` | **Laufzeit** `~/heater_plus` → **Paket** `allsky_heaterpcb_install` (vor Git) |
| `sync_heater_plus_runtime.sh` | **Paket** → **Laufzeit** (nach Pull / fremde Änderungen) |
| `heater_plus_runtime_sync.inc.sh` | gemeinsame Logik für Install + Runtime-Sync |
