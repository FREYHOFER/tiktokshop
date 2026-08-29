# TikTok Shop × Libri Automation

Eine Python-Pipeline für den Buchhandel, die Libri-Daten für TikTok Shop aufbereitet, Bestände abgleicht und neue Bestellungen für die weitere Verarbeitung vorbereitet.

## Ziel

Das Projekt verbindet wiederkehrende Abläufe zwischen Libri und TikTok Shop. Daten werden nicht ungeprüft veröffentlicht: unvollständige oder riskante Einträge landen in separaten Prüf- und Fehlerlisten.

## 3D-Buchvideo aus einem Titel

Ein Titel reicht aus, wenn das Buch bereits im TikTok-Shop liegt und die Seller-SKU dem Schema `LIBRI-{EAN}` folgt. Das Script findet ISBN, Libri-Daten und Cover automatisch und erzeugt ein 15-sekündiges Video in `1080x1920`:

```powershell
python scripts\create_book_video.py "Lights Out"
```

Das Ergebnis liegt unter `outputs/book_videos/<titel>-<ean>/rendered/book-video.mp4`. Zusätzlich werden ein Hero-Bild, vier Kontrollbilder, die verwendete Projektdatei und eine lokale Browser-Vorschau erzeugt.

Für einen Titel, der noch nicht im TikTok-Shop liegt, kann die ISBN direkt angegeben werden:

```powershell
python scripts\create_book_video.py "Buchtitel" --isbn 9781234567890
```

Optionale Anpassungen sind `--hook`, `--feature`, `--author`, `--label`, `--cta` und `--cover <datei-oder-url>`. Mit `--no-render` wird nur das Projekt samt interaktiver Vorschau vorbereitet. Ein lokales `npm install` ist nur nötig, wenn Playwright nicht bereits verfügbar ist; FFmpeg wird über `imageio-ffmpeg` aus den Python-Abhängigkeiten bereitgestellt.

## Module

### 1. Produktimport

Aus gespeicherten Libri-Produktseiten, Bestseller-Daten oder einer manuellen CSV entstehen:

- `tiktok_upload_green.xlsx` mit freigegebenen Produkten
- `candidate_report.csv` als Gesamtprüfung
- `review_hold.csv` für manuelle Kontrolle
- `rejects.csv` für unvollständige oder ungeeignete Datensätze
- `upload_log.md` als Zusammenfassung

Die Seller-SKU folgt dem Muster `LIBRI-{EAN}`. Das originale TikTok-Template wird kopiert und nicht strukturell verändert.

### 2. Bestandsabgleich

Das Inventory-Script liest den aktuellen Libri-Bestand und aktualisiert die zugehörige TikTok-SKU. Ein Dry-Run zeigt geplante Änderungen ohne Schreibzugriff.

```powershell
.\scripts\run_inventory_update_once.ps1 -DryRun -Limit 5
```

Der Abgleich kann lokal oder täglich über GitHub Actions ausgeführt werden. Pro Lauf entsteht ein nachvollziehbares CSV-Protokoll.

### 3. Bestellvorbereitung

Neue TikTok-Bestellungen werden aus der API oder testweise aus einem Seller-Center-CSV-Export gelesen. Für jede Bestellung entstehen unter anderem:

- eine Libri-Importdatei
- eine Lieferadressdatei
- ein lokaler Audit-Snapshot
- eine Zusammenfassung des Laufs

Der Workflow verarbeitet nur neue, noch nicht bekannte Bestellungen und speichert keine Kundendaten in öffentlichen GitHub-Issues.

## Schnellstart Produktimport

```powershell
python scripts\tiktok_libri_pipeline.py --workspace .
```

Weitere Produktseiten können über einen eigenen Ordner eingelesen werden:

```powershell
python scripts\tiktok_libri_pipeline.py `
  --workspace . `
  --detail-glob "libri_product_pages\*.html" `
  --limit 100
```

## Konfiguration

Zugangsdaten gehören ausschließlich in eine lokale `.env`-Datei oder in GitHub Actions Secrets. Sie dürfen nicht committed werden.

Je nach verwendetem Modul werden unter anderem benötigt:

- `LIBRI_CUSTOMER_NUMBER`
- `LIBRI_USERNAME`
- `LIBRI_PASSWORD`
- `TIKTOK_APP_KEY`
- `TIKTOK_APP_SECRET`
- `TIKTOK_ACCESS_TOKEN`
- optional `TIKTOK_SHOP_CIPHER`
- optional `TIKTOK_WAREHOUSE_ID`

## Sicherheits- und Prüfregeln

- Keine Zugangsdaten im Repository
- Dry-Run für Bestandsänderungen
- Manuelle Prüfliste für sensible oder unvollständige Produkte
- Keine automatische Veröffentlichung bei Validierungsfehlern
- Protokolle und Artefakte für jeden Automationslauf
- Zustandsdatei gegen doppelte Bestellverarbeitung

Die produktiven Abläufe sollten erst nach einem erfolgreichen Test mit wenigen Datensätzen aktiviert werden.
## Titelrotation: alte Titel gegen Neuerscheinungen

`scripts/rotate_tiktok_catalog.py` ersetzt keine vorhandenen TikTok-Listings inhaltlich. Stattdessen wird sauber rotiert:

- neue Titel werden aus einer vorbereiteten `tiktok_upload_green.xlsx` gelesen
- bereits vorhandene `LIBRI-{EAN}`-SKUs werden übersprungen
- alte Titel werden explizit per SKU/CSV oder automatisch bei niedrigem Libri-Bestand ausgewählt
- alte SKUs werden auf TikTok-Menge `0` gesetzt
- neue Titel werden per TikTok Shop Open API als Draft oder Listing angelegt

Standard ist ein Planlauf ohne TikTok-Schreibzugriff:

```powershell
.\scripts\run_catalog_rotation_once.ps1 -ReplaceCount 10
```

Live-Lauf, aber neue Produkte nur als Draft:

```powershell
.\scripts\run_catalog_rotation_once.ps1 -Live -ReplaceCount 10
```

Live-Lauf mit direktem Listing:

```powershell
.\scripts\run_catalog_rotation_once.ps1 -Live -Listing -ReplaceCount 10
```

Eine bestimmte Neuerscheinungs-XLSX verwenden:

```powershell
.\scripts\run_catalog_rotation_once.ps1 `
  -NewWorkbook "outputs\catalog_expansion\<run>\upload_pack_final\tiktok_upload_green.xlsx" `
  -ReplaceCount 10
```

Wenn keine alten Titel gefunden werden, legt das Script standardmäßig keine neuen an. Fuer einen reinen Ausbau ohne Austausch:

```powershell
.\scripts\run_catalog_rotation_once.ps1 -Live -AllowCreateWithoutRetire -ReplaceCount 10
```

Die Protokolle liegen in `outputs/catalog_rotation/<timestamp>/catalog_rotation_log.csv`. Der Live-Lauf rotiert nur so viele alte Titel wie neue Titel erfolgreich geplant bzw. erstellt wurden, damit bei TikTok-Fehlern nicht unnötig alte Titel stillgelegt werden.

## Bestellautomation TikTok -> Libri

Neue TikTok-Bestellungen werden mit `scripts/tiktok_order_automation.py` vorbereitet. Das Script liest entweder die TikTok Shop Open API oder testweise den neuesten Seller-Center-CSV-Export `Versandbereit Bestellung*.csv` aus Downloads.

Sicherer Test ohne API:

```powershell
.\scripts\prepare_order_from_latest_tiktok_csv.ps1
```

API-Einmalabruf:

```powershell
.\scripts\run_order_automation_once.ps1
```

Codex Scheduled Task: in der ChatGPT/Codex-Desktop-App **Scheduled** öffnen und eine Aufgabe im bestehenden Chat oder als eigenständige Aufgabe für dieses Projekt anlegen. Für den täglichen Lauf um 08:30 Uhr diesen Prompt verwenden:

```text
Jeden Tag um 08:30 Uhr Europe/Berlin im Projekt C:\Users\Stipendiat3\tiktokshop laufen:

1. Pruefe TikTok-Bestellungen und reiche neue versandbereite Bestellungen bei Libri ein:
   .\scripts\run_order_automation_once.ps1 -SkipEmptyRuns

2. Pruefe danach Mein.Libri-Direktversand-Lieferscheine und synchronisiere neue DHL-Trackingnummern zu TikTok:
   .\scripts\run_libri_tracking_sync_once.ps1

Berichte im Chat:
- ob neue TikTok-Orders gefunden, bei Libri eingereicht oder uebersprungen wurden
- ob ein neuer Libri-Lieferschein/Tracking gefunden und zu TikTok synchronisiert wurde
- konkrete Fehler mit dem naechsten sinnvollen manuellen Schritt

Keine GitHub-Issues erstellen und keine Windows-Aufgabe anlegen.
```

Dauerlauf, der jeden Tag um 17:00 Uhr Berliner Zeit abruft:

```powershell
.\scripts\watch_order_automation_17uhr.ps1
```

Dauerlauf fuer neue Bestellungen: prueft regelmaessig TikTok und bereitet nur neue, noch nicht verarbeitete Orders vor. Wenn nichts Neues da ist, wird kein leerer Output-Ordner erzeugt.

```powershell
.\scripts\watch_order_automation_new_orders.ps1 -PollMinutes 5
```

Laptop-unabhaengiger Lauf ueber GitHub Actions: `.github/workflows/tiktok-order-automation.yml` ist nur noch manuell ueber den Actions-Tab oder bei relevanten Pushes startbar; der fruehere 15-Minuten-Zeitplan ist entfernt. Neue versandbereite TikTok-Orders werden vorbereitet und danach automatisch als verifizierte Libri-Kundenbestellung abgesendet. Dafuer muessen in GitHub unter `Settings > Secrets and variables > Actions` im Environment `shop` diese Secrets gesetzt sein:

- `LIBRI_CUSTOMER_NUMBER`
- `LIBRI_USERNAME`
- `LIBRI_PASSWORD`
- `TIKTOK_APP_KEY`
- `TIKTOK_APP_SECRET`
- `TIKTOK_ACCESS_TOKEN`
- `TIKTOK_REFRESH_TOKEN`
- `TIKTOK_SHOP_CIPHER` falls TikTok mehrere Shops fuer den Token zurueckgibt

Wenn neue Bestellungen verarbeitet werden, liegen die Dateien als Actions-Artifact `libri-order-packages-<run-id>` im jeweiligen Workflow-Lauf. Zusaetzlich erstellt der Workflow ein GitHub-Issue mit Link zum Workflow-Lauf, aber ohne Kundendaten im Issue-Text. Bei Fehlern erstellt der Workflow ebenfalls ein Issue und markiert den Actions-Lauf als fehlgeschlagen. Der Workflow commitet nur `.automation/order_state.json`, damit dieselbe erfolgreich bei Libri abgesendete Bestellung nicht erneut verarbeitet wird.

Die Ergebnisse liegen in `outputs/order_automation/<timestamp>/<order-id>/`:

- `libri_kundenbestellung_import.xlsx`: Libri-Import fuer die Artikel dieser einen TikTok-Bestellung.
- `kundenadresse.csv`: Lieferadresse fuer Libri Schritt 2 `Kundenbestellung > Direktversand zum Kunden`.
- `tiktok_order.json`: lokaler Audit-Snapshot.
- `orders_summary.csv`: Zusammenfassung des Laufs.

Wichtig: Die produktive Automation schickt verifizierte TikTok-Orders direkt bei Libri ab. Der Review-Schritt prueft vor dem Absenden, dass die erwarteten EANs, Mengen, Titel und Lieferadressfelder im Libri-Pruefschritt stehen. Wenn eine Libri-Bestellung nicht bestaetigt werden kann, bleibt die Order als `libri_submission_failed` sichtbar und der Workflow meldet den Fehler.

Probe fuer Libri Schritt 2, nur wenn der Libri-Warenkorb leer ist:

```powershell
& "C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" `
  scripts\libri_customer_checkout_probe.py `
  --order-dir "outputs\order_automation\<timestamp>\<order-id>"
```

Der Probe-Helfer legt Artikel in den Libri-Warenkorb, geht bis `Kundenbestellung`, speichert `libri_customer_step2.html` und stoppt vor dem finalen Absenden.
