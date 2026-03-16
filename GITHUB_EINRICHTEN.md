# Heater+ zu GitHub – Schritt für Schritt

## Wichtig: Workspace in Cursor

**Cursor muss den Ordner `heater_plus` öffnen, nicht `/home/pi`.**

1. **File** → **Open Folder** (oder Strg+K, Strg+O)
2. Ordner wählen: `/home/pi/heater_plus`
3. **Open** klicken

Damit ist `heater_plus` der Workspace-Root. Sonst nimmt Cursor `/home/pi` und will alles hochladen.

---

## Schritt 1: Repo auf GitHub anlegen

1. Browser: [github.com](https://github.com) → einloggen
2. **+** (oben rechts) → **New repository**
3. **Repository name:** `heater_plus`
4. **Public** oder **Private** wählen
5. **Nicht** "Add a README" ankreuzen
6. **Create repository** klicken
7. Die URL notieren, z.B.: `https://github.com/DEIN_USERNAME/heater_plus.git`

---

## Schritt 2: Git in Cursor initialisieren

1. Sicherstellen: Workspace = `/home/pi/heater_plus` (siehe oben)
2. **Strg+Shift+G** (Source Control)
3. **Initialize Repository** klicken
4. Prüfen: Es darf nur `heater_plus`-Dateien zeigen, keine `.bashrc`, `allsky` usw.

---

## Schritt 3: Ersten Commit erstellen

1. In Source Control alle Dateien mit **+** stagen (oder auf das **+** neben "Changes" klicken)
2. Commit-Nachricht: `Initial commit`
3. **✓ Commit** klicken

---

## Schritt 4: Remote hinzufügen (Terminal)

Im Cursor-Terminal (Strg+`):

```bash
cd /home/pi/heater_plus
git remote add origin https://github.com/DEIN_USERNAME/heater_plus.git
```

`DEIN_USERNAME` durch deinen GitHub-Benutzernamen ersetzen.

---

## Schritt 5: Bei GitHub anmelden

1. Unten links auf das **Profil-Icon** klicken
2. **Sign in with GitHub** wählen
3. Im Browser autorisieren

---

## Schritt 6: Pushen

1. **Strg+Shift+G** (Source Control)
2. **Publish Branch** oder **Sync Changes** (Pfeil nach oben) klicken
3. Falls gefragt: **origin** und **main** wählen

---

## Schritt 7: Git-Identität (falls Fehlermeldung)

Falls Git nach Name/E-Mail fragt, im Terminal:

```bash
cd /home/pi/heater_plus
git config user.name "Dein GitHub-Name"
git config user.email "deine@email@github.com"
```

---

## Checkliste

- [ ] Cursor öffnet `/home/pi/heater_plus` (nicht /home/pi)
- [ ] Repo auf GitHub erstellt
- [ ] Git initialisiert (nur heater_plus-Dateien)
- [ ] Commit erstellt
- [ ] Remote `origin` gesetzt
- [ ] Bei GitHub angemeldet
- [ ] Push ausgeführt
