# Dauerhafte Projektregeln

- Aktuellen Automationsstatus immer über die GitHub-Actions-Workflows und deren
  reale Laufprotokolle prüfen. README-Aussagen, Zustandsdateien und pausierte
  Codex-Aufgaben allein sind kein Betriebsnachweis.
- Bestandsabgleich, Bestell-/Trackingautomation und Katalogrotation getrennt
  bewerten und benennen.
- Keine erfolgreiche Funktion behaupten, bevor ein echter Lauf des betreffenden
  Workflows erfolgreich abgeschlossen wurde.
- GitHub Actions ist der produktive Scheduler. Die lokalen Codex-Automationen um
  08:30, 09:00 und 18:00 Uhr sind pausiertes Legacy. OpenClaw/OpenRouter ist eine
  separate KI-Schicht und derzeit kein Scheduler produktiver TikTok-Transaktionen.
- Bei schreibenden TikTok-Aktionen bestehende Freigaben, Dry-Run-Vorgaben,
  Validierungen und Sicherheitsregeln einhalten. Keine Schreibaktion ausführen,
  wenn Ziel, Umfang oder Freigabe unklar sind.
- Keine Secrets, Kundendaten, lokale Caches, TTS-Ausgaben, temporären Tools oder
  generierten Binärartefakte committen.
