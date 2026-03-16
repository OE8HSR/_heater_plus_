# Grafana: TCS3448 Spektrumsensor – Anleitung mit Abfragen

Alle Abfragen nutzen den Bucket **`heater_plus`**.  
Measurement: **`sensor_data`**, Tag: **`sensor = "TCS3448"`**.

---

## 1. Spektrum F1–F8 über Zeit (eine Time-Series-Grafik)

**Zweck:** Alle 8 Filterkanäle F1–F8 im Zeitverlauf.

### In Grafana

1. **Dashboard** öffnen oder neu anlegen → **Add** → **Visualization** (oder **Panel** → **Add visualization**).
2. **Data source:** InfluxDB auswählen (der mit Bucket `heater_plus`).
3. **Query-Tab:** Bei **Query** auf **InfluxQL** achten – auf **Flux** umstellen (rechts oben oder in den Data-Source-Optionen).
4. **Eine** Abfrage einfügen:

```flux
from(bucket: "heater_plus")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) =>
    r._measurement == "sensor_data" and
    r.sensor == "TCS3448" and
    (r._field == "tcs_f1" or r._field == "tcs_f2" or r._field == "tcs_f3" or r._field == "tcs_f4" or r._field == "tcs_f5" or r._field == "tcs_f6" or r._field == "tcs_f7" or r._field == "tcs_f8")
  )
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> yield(name: "mean")
```

5. **Visualization:** oben **Time series** wählen.
6. **Panel-Titel:** z. B. „TCS3448 F1–F8 Spektrum“.
7. Optional in **Panel options** → **Legend**: „Legend mode“ z. B. „List“ oder „Table“, „Legend placement“ z. B. „Bottom“.  
   Optional in **Standard options** → **Unit**: „none“ (Counts) lassen.

---

## 2. Sichtbar (VIS) vs. NIR (eine Time-Series-Grafik)

**Zweck:** Helligkeit sichtbar vs. Nahinfrarot (z. B. Tag/Nacht, Lichttyp).

### In Grafana

1. Neues **Panel** → **Add visualization**.
2. **Data source:** InfluxDB (Flux).
3. **Eine** Abfrage:

```flux
from(bucket: "heater_plus")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) =>
    r._measurement == "sensor_data" and
    r.sensor == "TCS3448" and
    (r._field == "tcs_vis" or r._field == "tcs_vis2" or r._field == "tcs_vis3" or r._field == "tcs_nir")
  )
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> yield(name: "mean")
```

4. **Visualization:** **Time series**.
5. **Panel-Titel:** z. B. „TCS3448 VIS vs. NIR“.

---

## 3. Drei Grafiken: Kurzwellig / Mittel / Langwellig

### 3a) Kurzwellig (Blau/Cyan): F1, F2, FZ, F3

1. Neues Panel → **Add visualization**.
2. **Flux-Abfrage:**

```flux
from(bucket: "heater_plus")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) =>
    r._measurement == "sensor_data" and
    r.sensor == "TCS3448" and
    (r._field == "tcs_f1" or r._field == "tcs_f2" or r._field == "tcs_fz" or r._field == "tcs_f3")
  )
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> yield(name: "mean")
```

3. **Visualization:** **Time series**. **Titel:** z. B. „TCS3448 Kurzwellig (Blau/Cyan)“.

---

### 3b) Mittelwellig (Grün–Rot): F4, F5, FY, FXL, F6

1. Neues Panel.
2. **Flux-Abfrage:**

```flux
from(bucket: "heater_plus")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) =>
    r._measurement == "sensor_data" and
    r.sensor == "TCS3448" and
    (r._field == "tcs_f4" or r._field == "tcs_f5" or r._field == "tcs_fy" or r._field == "tcs_fxl" or r._field == "tcs_f6")
  )
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> yield(name: "mean")
```

3. **Visualization:** **Time series**. **Titel:** z. B. „TCS3448 Mittelwellig (Grün–Rot)“.

---

### 3c) Langwellig (Rot/NIR): F7, F8, NIR

1. Neues Panel.
2. **Flux-Abfrage:**

```flux
from(bucket: "heater_plus")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) =>
    r._measurement == "sensor_data" and
    r.sensor == "TCS3448" and
    (r._field == "tcs_f7" or r._field == "tcs_f8" or r._field == "tcs_nir")
  )
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> yield(name: "mean")
```

3. **Visualization:** **Time series**. **Titel:** z. B. „TCS3448 Langwellig (Rot/NIR)“.

---

## 4. Flicker (FD) – Time series oder Stat

**Zweck:** Flimmererkennung (50/60 Hz).

### Variante A: Time series

1. Neues Panel.
2. **Flux-Abfrage:**

```flux
from(bucket: "heater_plus")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) =>
    r._measurement == "sensor_data" and
    r.sensor == "TCS3448" and
    (r._field == "tcs_fd" or r._field == "tcs_fd2" or r._field == "tcs_fd3")
  )
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> yield(name: "mean")
```

3. **Visualization:** **Time series**. **Titel:** z. B. „TCS3448 Flicker (FD)“.

### Variante B: Stat (aktueller Wert)

1. Neues Panel.
2. **Gleiche Abfrage** wie oben (oder nur ein Kanal, z. B. `r._field == "tcs_fd"`).
3. **Visualization:** **Stat**.
4. Unter **Standard options** → **Reduce options**: **Calculation** = „Last“ oder „Mean“ (über das angezeigte Zeitfenster).
5. **Titel:** z. B. „TCS3448 Flicker (aktuell)“.

---

## 5. Spektrum-Schnappschuss (Bar chart – alle Kanäle)

**Zweck:** Aktuelle Verteilung über alle Kanäle wie ein kleines Spektrum.

### In Grafana

1. Neues Panel → **Add visualization**.
2. **Flux-Abfrage** (holt alle TCS3448-Felder; X-Achse = Feldname, Y = Wert):

```flux
from(bucket: "heater_plus")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) =>
    r._measurement == "sensor_data" and
    r.sensor == "TCS3448"
  )
  |> last()
  |> yield(name: "last")
```

3. **Visualization:** **Bar chart** wählen.  
   Falls die Achse nicht passt: unter **Transform** ggf. „Labels to fields“ oder „Merge“ prüfen; in neueren Grafana-Versionen werden mehrere `_field`-Serien oft automatisch als Balken nebeneinander gezeichnet (X = `_field`, Y = `_value`).
4. **Titel:** z. B. „TCS3448 Spektrum (letzter Wert)“.

**Hinweis:** Wenn der Bar chart nur eine Serie oder keine Balken zeigt, in **Transform** „Series to rows“ oder „Merge series“ ausprobieren, sodass `_field` als Kategorie (X) und `_value` als Höhe genutzt wird. Alternativ **Bar gauge** mit „Last“-Reduktion pro Serie verwenden.

### Alternative: Bar gauge mit einer Abfrage

1. Neues Panel.
2. **Visualization:** **Bar gauge**.
3. **Eine** Abfrage wie in Abschnitt 1 (F1–F8) oder die „alle Kanäle“-Abfrage von oben.
4. **Reduce options:** **Calculation** = **Last**.  
   Dann zeigt die Bar gauge die letzten Werte pro Serie (jede Serie = ein Balken).

---

## Übersicht: Welches Panel mit welcher Abfrage

| Nr. | Panel-Titel (Vorschlag)     | Visualisierung | Abfrage (Kurz)        |
|-----|-----------------------------|----------------|-----------------------|
| 1   | TCS3448 F1–F8 Spektrum      | Time series    | tcs_f1 … tcs_f8       |
| 2   | TCS3448 VIS vs. NIR         | Time series    | tcs_vis, tcs_vis2, tcs_vis3, tcs_nir |
| 3a  | TCS3448 Kurzwellig          | Time series    | tcs_f1, tcs_f2, tcs_fz, tcs_f3 |
| 3b  | TCS3448 Mittelwellig        | Time series    | tcs_f4, tcs_f5, tcs_fy, tcs_fxl, tcs_f6 |
| 3c  | TCS3448 Langwellig          | Time series    | tcs_f7, tcs_f8, tcs_nir |
| 4   | TCS3448 Flicker             | Time series oder Stat | tcs_fd, tcs_fd2, tcs_fd3 |
| 5   | TCS3448 Spektrum (Snapshot) | Bar chart / Bar gauge | alle tcs_* (last) |

---

## Wichtige Einstellungen in Grafana

- **Zeitbereich** oben rechts einstellen (z. B. „Last 6 hours“), damit `v.timeRangeStart` / `v.timeRangeStop` passen.
- **Data source** muss auf die InfluxDB-Instanz zeigen, in der der Bucket **heater_plus** existiert.
- Wenn keine Daten erscheinen: Zeitbereich vergrößern und prüfen, ob Heater+-Script läuft und Daten in `heater_plus` schreibt.

Damit hast du für alle vorgeschlagenen TCS3448-Visualisierungen eine konkrete Anleitung inkl. Abfrage.
