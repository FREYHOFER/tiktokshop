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

## Produktiver Automationsbetrieb

GitHub Actions ist der produktive Scheduler. Der aktuelle Status ist immer anhand
der Workflow-Dateien und der tatsächlichen Läufe im GitHub-Actions-Tab zu prüfen,
nicht anhand älterer README-Texte oder pausierter lokaler Aufgaben.

- **Bestellungen und Tracking:** `.github/workflows/tiktok-order-automation.yml`
  läuft alle 15 Minuten. Er bereitet neue Bestellungen vor, übermittelt verifizierte
  Kundenbestellungen an Libri und synchronisiert verfügbare Trackingdaten zu TikTok.
- **Bestandsabgleich:** `.github/workflows/tiktok-inventory-update.yml` läuft täglich.
- **Katalogrotation:** `.github/workflows/tiktok-weekly-catalog-rotation.yml` läuft
  wöchentlich live; manuelle Läufe sind standardmäßig Dry-Runs.

Beide schreibenden Abläufe erzeugen zuerst einen Prüfplan. Der Bestandsabgleich
bricht bei ungewöhnlich wenigen gefundenen SKUs, mehr als 30 Änderungen, mehr
als 15 Nullsetzungen oder unvollständigen Datensätzen ab. Die wöchentliche
Katalogrotation ist auf drei ausgeglichene Titelpaare begrenzt: Das neue Listing
wird zuerst erstellt und per TikTok-Lesezugriff bestätigt, bevor der alte Titel
auf Bestand null gesetzt und ebenfalls zurückgelesen wird. Fehler erzeugen ein
GitHub-Issue mit Link zum Lauf, aber ohne Secrets oder Kundendaten.

Für die Live-Neuanlage in der EU muss im GitHub-Environment `shop` zusätzlich
`TIKTOK_MANUFACTURER_IDS_JSON` hinterlegt sein. Das Secret ist ein JSON-Objekt,
das die von Libri gelieferten Verlagsnamen (oder eindeutige Namensbestandteile)
den jeweils in TikTok registrierten Hersteller-IDs zuordnet, zum Beispiel
`{"Piper":"<TikTok-ID>","Carlsen":"<TikTok-ID>"}`. Die Katalogrotation prüft
diese Zuordnung bereits im Planlauf und bricht vor jeder Schreibaktion ab, sobald
Verlag oder TikTok-Hersteller-ID fehlen bzw. mehrdeutig sind. Eine einzige
globale ID wird nicht automatisch als Ersatz verwendet, weil sie Produkte eines
anderen Verlags mit falschen GPSR-Daten versehen könnte.

Die Verlagsbezeichnung wird aus den Libri-Produktdaten in `candidate_report.csv`
übernommen. Neue Hersteller müssen zuerst im Seller Center mit den Daten der
offiziellen Verlagswebsite bzw. ihres Impressums angelegt werden; anschließend
wird nur die von TikTok vergebene ID in das Mapping aufgenommen. Ein erfolgreicher
Workflow-Lauf ist weiterhin der notwendige Betriebsnachweis.

Der Libri-Login öffnet für jeden Versuch eine neue Sitzung und wiederholt eine
vorübergehend abgewiesene Anmeldung mit wachsender Wartezeit. Die Protokolle
unterscheiden eine zurückgegebene Loginseite, HTTP-Fehler und Verbindungsfehler,
ohne Zugangsdaten oder Seiteninhalte auszugeben. Erst nach fünf fehlgeschlagenen
Versuchen wird der Workflow sicher vor TikTok-Schreibaktionen beendet.

Die früheren lokalen Codex-Automationen um 08:30, 09:00 und 18:00 Uhr sind
pausierte Legacy-Abläufe und kein Beleg für den produktiven Status. OpenClaw und
OpenRouter bilden eine separate KI-Schicht; sie steuern derzeit nicht den
Scheduler der produktiven TikTok-Transaktionen. Eine Automation gilt erst nach
einem erfolgreich abgeschlossenen echten Workflow-Lauf als funktionsfähig.

## Tägliche Shoppable-Foto-Slideshow

Der lokale Entwurfs-Workflow erzeugt eine cover-first Slideshow (standardmäßig fünf
1080×1920-JPGs), einen verkaufsorientierten Titeltext und eine `manifest.json`.
Der Entwurf wird pro Datum im `.automation/content_state.json` registriert, damit
Wiederholungen vermieden werden:

```powershell
python scripts\generate_daily_slideshow.py --date 2026-08-31
```

Der Generator verwendet ausschließlich unveränderte Originalauszüge aus dem
Libri-Klappentext. Es gibt keine KI-Hooks, Paraphrasen, Leserzitate oder
Reddit-Screenshots.

Für einen vertonten Beispiel-Clip:

```powershell
python scripts\render_blurb_video.py --manifest <manifest.json> --output <beispiel.mp4>
```

Die Stimme wird lokal über die installierte Windows-Sprachausgabe erzeugt;
der Klappentext wird nicht an einen Cloud-Dienst gesendet.

Die Bilder enthalten keine URL, QR-Code oder Wasserzeichen. Der klickbare
TikTok-Shop-Produktanker muss im nativen Shop-Flow gesetzt werden. Für deutsche
Seller ist dafür – sofern für das Konto freigeschaltet – **Seller Center →
Shoppable Videos → Auto-post** der offiziell dokumentierte Weg; das Feature ist
noch im Beta-Rollout und nicht per Seller-REST-API steuerbar. Die allgemeine
TikTok-Content-Posting-API kann zwar Foto-Posts mit Cover-Index senden, nimmt aber
keinen Shop-Produktanker entgegen und verlangt eine geprüfte, interaktive Creator-
UX.

Die T-1-Shop-Metriken können mit dem Seller-Token read-only importiert werden:

```powershell
python scripts\fetch_shop_video_metrics.py --date 2026-08-30 --end-date 2026-08-31
```

Dafür muss der Token den Scope `data.shop_analytics.public.read` besitzen. Das
Script schreibt die Rohdaten nach `outputs\metrics\` und aktualisiert gematchte
Entwürfe im Content-State; ein Match erfolgt über die gespeicherte Video-ID oder
den exakten Post-Titel. Die Auswahl nutzt die Ergebnisse als kleinen Lernbonus,
behält aber eine 14-Tage-Sperre für denselben Titel bei.
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

Legacy-Hinweis: Die früheren lokalen Codex-Aufgaben um 08:30, 09:00 und 18:00 Uhr
sind pausiert. Der folgende Prompt bleibt nur als historische Referenz erhalten
und darf nicht als Beschreibung des aktuellen produktiven Schedulers verstanden
werden:

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

Produktiver Lauf ueber GitHub Actions: `.github/workflows/tiktok-order-automation.yml`
läuft alle 15 Minuten, bei relevanten Pushes und bei manueller Auslösung. Neue
versandbereite TikTok-Orders werden vorbereitet und danach automatisch als
verifizierte Libri-Kundenbestellung abgesendet. Dafuer muessen in GitHub unter
`Settings > Secrets and variables > Actions` im Environment `shop` diese Secrets
gesetzt sein:

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
