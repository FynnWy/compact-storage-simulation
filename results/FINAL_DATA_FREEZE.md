# Final Raw Data Freeze

Einfrieren des finalen Rohdatenbestands vor dem Merge von `working_sim`.
Keine Analyse, keine Simulation, keine Datenkorrektur, keine Commits.

---

## 1. Kontext

| | |
|---|---|
| **Datum** | 2026-08-26 |
| **`git rev-parse HEAD`** | `a9f46b6c9ef728bd1ba2ac82ed89250b2aeed96c` |
| **`git branch --show-current`** | `working_sim` |
| **HEAD-Commit** | `a9f46b6` — 2026-08-24 21:20:55 +0200 — „Updated FINAL_EXPERIMENT_FREEZE_2026-08-21.md Doku" |
| **Python (Kampagne)** | 3.10.12 — CPython, pyenv `3.10.12`, Repo-venv `.venv310` |
| **Quelle** | `results/final/` |
| **Frozen Copy** | `results/final_raw/` |
| **SHA256 Manifest** | `results/FINAL_DATA_SHA256.txt` |
| **Validity Audit** | `results/FINAL_DATA_VALIDITY_AUDIT.md` |

---

## 2. Bestand

| | |
|---|---|
| Dateien | 57 (6 Datendateien + 1 Backup + 50 Lauflogs) |
| Bytes | 684 693 263 (≈ 653 MiB) |
| Struktur | `runs.csv`, `retrievals.csv`, `requests.csv`, `distribution.csv`, `run_meta.json`, `campaign_status.json`, `campaign_status.json.bak`, `logs/<run_id>.log` × 50 |

---

## 3. Campaign

```text
50/50 Runs
FINAL CAMPAIGN INTEGRITY CHECK = PASS
```

5 Policies (`baseline_reference`, `RR+RR`, `LR+NR`, `ABC+ABC`,
`POPULARITY+POPULARITY`) × 10 Seeds (1, 2, 3, 4, 7, 11, 13, 42, 99, 123),
jede Kombination genau einmal. Alle Laeufe `state = completed`,
`error` leer, `move_recovery_unresolved = 0`, `task_deadlock = 0`,
Messfenster `time_window` [20000, 30000].

---

## 4. Validity

```text
FINAL_DATA_VALIDATED          = JA
READY_FOR_SCIENTIFIC_ANALYSIS = JA
```

Vollstaendige Begruendung: `results/FINAL_DATA_VALIDITY_AUDIT.md`.

---

## 5. Verifikation der Raw-Kopie

`results/final_raw/` wurde als exakte Kopie von `results/final/` angelegt
und vollstaendig gegengeprueft:

| Kriterium | Ergebnis |
|---|---|
| gleiche Dateianzahl | 57 = 57 |
| gleiche relative Pfade | identische Menge |
| gleiche Dateigroessen | alle 57 identisch |
| gleiche SHA-256-Hashes | alle 57 identisch |
| Summe Bytes | 684 693 263 = 684 693 263 |

```text
RAW_COPY_BYTEIDENTICAL = JA
```

Zusaetzlich verifiziert das Manifest gegen **beide** Baeume fehlerfrei:

```bash
cd results/final     && sha256sum -c ../FINAL_DATA_SHA256.txt   # exit 0
cd results/final_raw && sha256sum -c ../FINAL_DATA_SHA256.txt   # exit 0
```

**Hinweis zum Kopiervorgang.** Ein erster Kopierlauf wurde vom
Werkzeug-Timeout unterbrochen und hinterliess `logs/ABC+ABC__seed99.log`
abgeschnitten (1 875 968 statt 13 162 928 Bytes). Der Fehler wurde durch den
SHA-256-Vergleich gefunden, die Datei neu kopiert und der gesamte Bestand
danach erneut vollstaendig verifiziert. `results/final/` war davon zu keinem
Zeitpunkt betroffen — der Timeout traf nur die Zielseite.

---

## 6. Schreibschutz

Auf `results/final_raw/` wurde rekursiv `chmod -R a-w` abgesetzt.

**Status: nicht abschliessend verifizierbar.** Schreibversuche werden
zuverlaessig abgewiesen (Anhaengen an eine bestehende Datei und Anlegen einer
neuen Datei scheitern beide mit `Permission denied`), aber `stat` meldet ueber
die Arbeitsumgebung weiterhin die urspruenglichen Bits (`600`/`700`). Ob der
Schutz auf der macOS-Seite tatsaechlich persistiert ist, laesst sich von hier
aus nicht feststellen.

**Bitte einmal im Terminal bestaetigen:**

```bash
cd ~/PycharmProjects/compact-storage-simulation
chmod -R a-w results/final_raw
ls -l results/final_raw/runs.csv          # erwartet: -r--r--r--
echo test >> results/final_raw/runs.csv   # erwartet: Permission denied
```

Der Schreibschutz ist eine Bequemlichkeitssicherung. Die eigentliche
Reproduzierbarkeitsgarantie liefert `FINAL_DATA_SHA256.txt`: jede spaetere
Veraenderung an `results/final/` oder `results/final_raw/` ist damit
nachweisbar.

---

## 7. Bekannte Datenhinweise

Aus `FINAL_DATA_VALIDITY_AUDIT.md` uebernommen, ohne neue Interpretation.

**F-1.** `POPULARITY+POPULARITY/seed1` besitzt einen `request_id`-Labeldefekt
ausserhalb des Messfensters; `request_id` nicht als eindeutigen Schluessel
verwenden.

**F-2.** `baseline_reference/seed99` endet technisch bei `t_end = 30003`;
Messfenster und KPIs unberuehrt.

---

## 8. Git

Im Repository existiert **keine** `.gitignore` im Wurzelverzeichnis. `results/`
ist damit **nicht** ignoriert, sondern lediglich untracked:

```text
git status --porcelain results/   ->   ?? results/
git check-ignore -v results/final/*       ->  exit != 0 (nicht ignoriert)
git check-ignore -v results/final_raw/*   ->  exit != 0 (nicht ignoriert)
```

Untracked unterhalb von `results/`: 116 Pfade, zusammen ≈ 1,3 GB
(`final/` + `final_raw/` + drei Freeze-/Audit-Dateien).

Es wurde **nichts** committet, **nichts** gepusht, **nichts** mit `git add -f`
erzwungen und **keine** `.gitignore` angelegt oder geaendert.

Bewertung der neu erzeugten Freeze-Dateien:

| Datei | Groesse | sinnvoll versionierbar |
|---|---|---|
| `results/FINAL_DATA_FREEZE.md` | wenige KB | ja |
| `results/FINAL_DATA_SHA256.txt` | 5,6 KB | ja — das Manifest gehoert in die Versionskontrolle |
| `results/FINAL_DATA_VALIDITY_AUDIT.md` | 39,6 KB | ja |
| `results/final/` | 653 MiB | **nein** |
| `results/final_raw/` | 653 MiB | **nein** |

**Offener Punkt fuer den Merge.** Ohne `.gitignore` wuerde ein
`git add .` oder ein `git add results/` die kompletten Rohdaten
(≈ 1,3 GB inkl. Kopie) stagen. Git ist nicht der Backup-Mechanismus fuer
hunderte MB Rohlogs. Das ist hier nur **berichtet**, nicht geaendert —
die Entscheidung liegt bei dir.

---

## 9. Ab hier gilt

```text
results/final/      wird nicht mehr veraendert.
results/final_raw/  wird nicht mehr veraendert.
```

Alle zukuenftigen Analyseartefakte — abgeleitete Datensaetze, Tabellen,
Abbildungen, Notebooks, Statistik-Ausgaben — gehoeren in einen **separaten**
Analyseordner und schreiben niemals in einen der beiden Rohdatenordner
zurueck.

---

## 10. Status

```text
SOURCE_DATA_UNCHANGED       = JA
RAW_COPY_CREATED            = JA
RAW_COPY_BYTEIDENTICAL      = JA
SHA256_MANIFEST_CREATED     = JA
RAW_COPY_READ_ONLY          = NEIN   (chmod abgesetzt, macOS-seitig nicht verifizierbar — siehe 6)
FREEZE_DOCUMENT_CREATED     = JA
READY_FOR_BRANCH_MERGE      = JA
```
