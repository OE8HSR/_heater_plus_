# Grafana: TCS3448 & Heater+ Visualisierung

## 1. TCS3448 – wo die Werte herkommen

- **Bucket:** `heater_plus`
- **Measurement:** `sensor_data`
- **Tags:** `sensor=TCS3448`, `measurement=spectrum`
- **Fields:** `tcs_fz`, `tcs_fy`, `tcs_fxl`, `tcs_nir`, `tcs_vis`, `tcs_fd`, `tcs_f2`, `tcs_f3`, `tcs_f4`, `tcs_f6`, `tcs_vis2`, `tcs_fd2`, `tcs_f1`, `tcs_f7`, `tcs_f8`, `tcs_f5`, `tcs_vis3`, `tcs_fd3`

Spektralkanäle (Peak-Wellenlänge laut Datenblatt):

| Field     | Kanal | ~nm  | Bedeutung        |
|----------|--------|------|------------------|
| tcs_f1   | F1     | 407  | Violett/Blau     |
| tcs_f2   | F2     | 424  | Blau             |
| tcs_fz   | FZ     | 450  | Blau/Cyan        |
| tcs_f3   | F3     | 473  | Cyan             |
| tcs_f4   | F4     | 516  | Grün             |
| tcs_f5   | F5     | 546  | Grün/Gelb        |
| tcs_fy   | FY     | 560  | Gelb (breit)     |
| tcs_fxl  | FXL    | 596  | Orange           |
| tcs_f6   | F6     | 636  | Rot              |
| tcs_f7   | F7     | 687  | Tiefrot          |
| tcs_f8   | F8     | 748  | Nahrot           |
| tcs_nir  | NIR    | 855  | Nahes Infrarot   |
| tcs_vis  | VIS    | –    | Clear (sichtbar) |
| tcs_fd   | FD     | –    | Flicker          |

---

## 2. Empfohlene Grafana-Panels

### A) Spektrum über Zeit (eine Grafik)

**Zweck:** Alle Spektralkanäle F1–F8, FZ, FY, FXL, NIR in einem Zeitverlauf.

- **Panel-Typ:** Time series
- **Eine Query pro Kanal** (oder eine Query mit mehreren `_field`), z. B.:

```flux
from(bucket: "heater_plus")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) =>
    r._measurement == "sensor_data" and
    r.sensor == "TCS3448" and
    r._field == "tcs_fz"
  )
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> yield(name: "FZ 450nm")
```

- **Empfehlung:** Für FZ, FY, F4, NIR, VIS je eine Query; Legende „FZ 450nm“ etc. So siehst du, welche Wellenlängen wann dominieren (Tag/Nacht, Bewölkung, Kunstlicht).

### B) Sichtbar vs. NIR (eine Grafik)

**Zweck:** Helligkeit sichtbar (VIS) vs. NIR – gut für Tag/Nacht, Bewölkung, Störlicht.

- **Panel-Typ:** Time series
- **Zwei Queries:** `_field == "tcs_vis"` und `_field == "tcs_nir"` (ggf. zusätzlich `tcs_vis2`, `tcs_vis3` wenn du alle VIS-Kanäle willst).
- **Auswertung:** Verhältnis NIR/VIS steigt oft bei Sonne/NIR-reichem Licht; nachts oder bei reinem Kunstlicht sinkt es.

### C) Spektrale Bänder gruppiert (2–3 Grafiken)

Statt alle 18 Felder in eine Grafik zu packen, nach Wellenlänge gruppieren:

1. **Kurzwellig (Blau/Cyan):** F1, F2, FZ, F3  
   - Eine Time series, 4 Queries (`tcs_f1`, `tcs_f2`, `tcs_fz`, `tcs_f3`).

2. **Mittelwellig (Grün–Rot):** F4, F5, FY, FXL, F6  
   - Eine Time series, 5 Queries.

3. **Langwellig + NIR:** F7, F8, NIR  
   - Eine Time series, 3 Queries.

So erkennst du z. B. Schichtwechsel Blau → Grün → Rot über den Tag oder bei Lampenwechsel.

### D) Flicker (FD)

**Zweck:** Flicker-Kanäle (FD, FD2, FD3) getrennt oder gemittelt.

- **Panel-Typ:** Time series oder Stat (z. B. „letzter Wert“).
- **Query:** `r._field == "tcs_fd"` (evtl. zusätzlich `tcs_fd2`, `tcs_fd3`).
- **Auswertung:** Erhöhte Werte bei 50/60 Hz-Flimmern; ruhiges Licht = niedrigere/stable Werte.

### E) Einzelne Kanäle als Stat

Für Übersichtsdashboards: **Stat-Panels** mit einer Query pro Kanal, z. B. „aktueller Wert“ (last/mean über kurzes Fenster) für:

- `tcs_vis` (Helligkeit „clear“)
- `tcs_nir`
- `tcs_fy` (gelber Bereich, oft stark bei Sonne)

---

## 3. Flux: alle TCS3448-Felder in einer Abfrage

Wenn du alle Spektralfelder als mehrere Serien in einem Panel haben willst:

```flux
from(bucket: "heater_plus")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) =>
    r._measurement == "sensor_data" and
    r.sensor == "TCS3448"
  )
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> yield(name: "mean")
```

Dann erscheinen alle `tcs_*`-Felder als eigene Kurven; in der Legende kannst du umbenennen (z. B. `tcs_nir` → „NIR 855nm“).

---

## 4. Kurz-Check: Werte kommen in der DB an

- **Explorer (Influx UI):** Bucket `heater_plus` → Filter `_measurement=sensor_data`, `sensor=TCS3448` → prüfen, ob `tcs_fz`, `tcs_vis`, `tcs_nir` etc. Daten haben.
- **Grafana:** Einfaches Time-series-Panel mit der obigen „alle TCS3448“-Query; wenn Kurven sichtbar sind, werden die Werte zuverlässig geschrieben.

---

## 5. Übersicht: Welche Kanäle wofür

| Grafik / Zweck              | Kanäle (Fields)                    |
|----------------------------|-------------------------------------|
| Gesamtspektrum über Zeit   | Alle `tcs_f*`, `tcs_nir`, `tcs_vis` |
| Sichtbar vs. NIR           | `tcs_vis`, `tcs_nir`               |
| Blau/Cyan                  | `tcs_f1`, `tcs_f2`, `tcs_fz`, `tcs_f3` |
| Grün–Rot                   | `tcs_f4`, `tcs_f5`, `tcs_fy`, `tcs_fxl`, `tcs_f6` |
| Rot/NIR                    | `tcs_f7`, `tcs_f8`, `tcs_nir`      |
| Flicker                    | `tcs_fd`, `tcs_fd2`, `tcs_fd3`     |
| Einzelwerte (Stats)        | z. B. `tcs_vis`, `tcs_nir`, `tcs_fy` |

Damit kannst du in Grafana sowohl die Rohwerte sicher prüfen als auch sinnvoll nach Wellenlängen und Anwendung (Helligkeit, Spektrum, Flicker) visualisieren.
