# GoPro Anamorphic Toolkit — Specifica del progetto

> Documento di partenza per Claude Code. Descrive cosa costruire, in quali fasi,
> e tutti i dettagli tecnici già verificati sul campo. Leggere tutto prima di
> iniziare. Procedere **per fasi**, non tutto in un colpo: completare e testare
> una fase prima di passare alla successiva.

## 1. Obiettivo

Uno strumento Linux, con interfaccia grafica semplice, che prende i file video
originali di una **GoPro HERO11 Black** girati con una **lente anamorfica Neewer
LS-56 1.2x** (non ufficiale) e produce video pronti all'uso:

1. **Desqueeze** anamorfico (fattore 1.2x orizzontale) — sempre.
2. **Stabilizzazione** tramite Gyroflow con un profilo di lente **calibrato
   dall'utente** — opzionale, attivabile da interfaccia.
3. **Export** in un formato leggero (default 1080p H.265) adatto alla TV.

Lo strumento NON usa la stabilizzazione interna della GoPro (HyperSmooth): usa
i dati grezzi del giroscopio contenuti nel file (GPMF) + Gyroflow. Questo è
voluto e corretto: con la lente non ufficiale HyperSmooth produce ondeggiamenti,
mentre Gyroflow con profilo calibrato dà un risultato migliore.

Il progetto deve poter essere pubblicato come repository e usato da altri.

## 2. Contesto tecnico già verificato

Questi fatti sono stati verificati sul campo e vanno dati per acquisiti:

- **Formato di ripresa consigliato**: 2.7K (2704x1520 per 16:9, 2704x2028 per
  4:3), lente **Wide**, HyperSmooth **spento**. In Wide l'immagine ha distorsione
  fisheye che Gyroflow corregge col profilo.
- **Fattore di squeeze della lente**: 1.2x orizzontale, verticale 1.0.
- **Dati giroscopio**: contenuti nella traccia **GPMF** del file MP4 originale
  (handler `GoPro MET`). Si perdono se il file passa da app/editor che ricodificano.
  Usare SEMPRE i file originali dalla scheda SD.
- **Gyroflow**: usato come eseguibile esterno (AppImage) via CLI. Comando tipo:
  `Gyroflow.AppImage <video> --preset <file.gyroflow> -f`
  Produce un file `<nome>_stabilized.mp4` accanto all'input.
- **Profilo lente calibrato**: file `.json` prodotto dal Lens Calibrator di
  Gyroflow. Nella calibrazione si imposta Input horizontal stretch = 1.2.
  Reprojection error ottenuto: ~1.27 (buono). Il profilo è specifico per la
  combinazione HERO11 + Neewer + impostazioni.
- **Preset Gyroflow** (`neewer.gyroflow`): JSON che indica codec/bitrate di
  output e il percorso del `calibration_file`. Esempio funzionante:
  ```json
  {
    "version": 2,
    "calibration_file": "/percorso/assoluto/neewer_lens.json",
    "output": {"codec": "H.264/AVC", "bitrate": 100}
  }
  ```
- **Bug noto innocuo**: su hardware AMD (es. ThinkPad E485, Ryzen 2700U) Gyroflow
  stampa errori ripetuti `Failed to initialize OpenCL Platform::list ...` e
  `Cannot load libcuda.so.1` / `libamfrt64.so.1`. NON sono errori fatali:
  Gyroflow ricade su `wgpu` (riga `Initialized wgpu for ...`) e completa il
  rendering. Lo strumento deve ignorare questi messaggi e considerare il
  successo in base alla presenza del file `_stabilized.mp4` e alla riga
  `Done in <tempo>s`.
- **Pipeline desqueeze+crop+encode** (già funzionante in ffmpeg):
  `scale=iw*1.2:ih` (desqueeze) → `crop` al formato finale → `scale` a 1080p →
  `libx265 -crf 22 -preset medium -tag:v hvc1`.
- **Catena ordine operazioni**: Gyroflow PRIMA (stabilizza + corregge lente sul
  file originale con GPMF), poi ffmpeg sul file stabilizzato per desqueeze,
  crop e export. Il desqueeze va fatto DOPO Gyroflow.
- Quando si stabilizza con Gyroflow NON serve ritaglio extra anti-vignettatura
  (ZOOM=1.0): Gyroflow già ritaglia i bordi. Senza stabilizzazione, in 4:3 Wide
  servono ~1.3x di crop per togliere la vignettatura, in 16:9 ~1.2x.

### Punto da verificare durante lo sviluppo
Gyroflow carica i profili lente anche da `~/.local/share/Gyroflow/lens_profiles`.
Va verificato che il `calibration_file` indicato nel preset venga effettivamente
applicato al rendering (e non un profilo di default). Aggiungere un test che
confronti l'output stabilizzato con e senza profilo, o che logghi quale profilo
è stato caricato.

## 3. Formati di output

- Da **4:3** (2704x2028): desqueeze 1.2x → crop a 16:9 → 1080p. Usa tutto il
  sensore, più margine per stabilizzazione.
- Da **16:9** (2704x1520): desqueeze 1.2x → risultato ~2.13:1 (cinematografico)
  → export a 1920 di larghezza (es. 1920x900).
- Entrambi i casi parametrizzabili (aspect ratio e larghezza finale configurabili).

## 4. Interfaccia (semplice)

Requisiti minimi dell'interfaccia:
- Selezione di una cartella di input (o trascinamento file).
- Rilevamento automatico delle impostazioni di ogni file (risoluzione, fps,
  presenza GPMF, aspect) via ffprobe/exiftool, con un avviso se un file non è
  nel formato atteso (es. non 2.7K, o manca il giroscopio).
- Checkbox "Stabilizza con Gyroflow" (default attivo).
- Scelta formato output (16:9 TV / 2.13:1 cinema) e qualità.
- Pulsante Avvia, barra di avanzamento, log.
- Cartella di output selezionabile.

Tenere l'interfaccia minimale e pulita. Priorità alla chiarezza, non alle opzioni.

## 5. Architettura consigliata (per fasi)

### Fase 1 — Core CLI (riscrittura pulita dello script esistente)
- Linguaggio: **Python 3**.
- Modulo che: scansiona input, legge metadati, valida il formato, chiama
  Gyroflow (se richiesto), esegue la pipeline ffmpeg, scrive in output.
- Config via argomenti CLI + file di config.
- Il profilo lente calibrato (`neewer_lens.json`) va **incluso nel repository**
  come risorsa di default, e il preset generato al volo con percorso assoluto
  corretto a runtime (non hardcodare `/home/john/...`).
- Gestione del bug OpenCL: non trattare gli stderr di Gyroflow come fallimento;
  verificare successo dal file prodotto.
- Test su file reali (vedi sezione 7).

### Fase 2 — GUI
- Opzioni consigliate, scegliere in base a semplicità di packaging AppImage:
  - **PySide6/Qt** (completa, si impacchetta bene) — consigliata.
  - Alternative: GTK (PyGObject), o una web UI locale (più pesante).
- La GUI chiama lo stesso core della Fase 1 (nessuna logica duplicata).

### Fase 3 — Packaging AppImage
- Impacchettare l'app Python in **AppImage** per Linux (strumenti tipo
  `python-appimage`, `appimage-builder`, o `linuxdeploy` + conda/venv).
- **Gyroflow NON va incluso dentro l'AppImage.** Va richiesto come requisito.
  L'utente scarica la sua `Gyroflow.AppImage` e la indica nelle impostazioni
  (o la si cerca in percorsi noti). Documentare questo chiaramente nel README.
- Il profilo lente calibrato di default può invece essere incluso.

## 6. Struttura repository proposta

```
gopro-anamorphic-toolkit/
├── README.md
├── LICENSE                 (suggerire MIT o GPLv3; chiedere all'utente)
├── .gitignore              (deve escludere la cartella di test gopro/ e gli output)
├── SPECIFICA_PROGETTO.md   (questo file)
├── src/
│   └── gat/
│       ├── __init__.py
│       ├── core.py         (pipeline: scan, validate, gyroflow, ffmpeg)
│       ├── metadata.py     (ffprobe/exiftool, rilevamento GPMF e formato)
│       ├── gyroflow.py     (wrapper CLI Gyroflow, gestione bug OpenCL)
│       ├── cli.py          (entry point a riga di comando)
│       └── gui.py          (Fase 2)
├── resources/
│   └── neewer_lens.json    (profilo lente calibrato di default)
├── tests/
│   └── ...                 (vedi sezione 7)
└── packaging/
    └── ...                 (script AppImage, Fase 3)
```

## 7. Materiale di test incluso

Nella root c'è una cartella **`gopro/`** (esclusa da git tramite `.gitignore`)
con materiale reale per testare durante lo sviluppo:
- `gopro/169/GX010050.MP4` — clip 16:9, 2.7K, Wide, con mosso volontario forte
  (utile per testare la stabilizzazione).
- `gopro/43/GX010049.MP4` — clip 4:3, 2.7K, Wide.
- `gopro/video calibrazione/GX010051.MP4` — video della scacchiera.
- `gopro/neewer_lens.json` — profilo lente calibrato (copiarlo in `resources/`).
- `gopro/Gyroflow.AppImage` — eseguibile Gyroflow per i test.
- `gopro/gopro_anamorfico.sh` — lo script bash originale, da usare come
  riferimento per la logica (NON come codice finale).

Usare questi file per verificare ogni fase. I clip di test possono essere
pubblicati nel repo (nessun contenuto sensibile), ma meglio tenerli fuori dal
versionamento per il peso: valutare git-lfs o un link di download separato.

## 8. Note finali per Claude Code

- Procedere a blocchi, con commit frequenti e messaggi chiari.
- Non hardcodare percorsi assoluti dell'utente: tutto relativo o configurabile.
- Scrivere un README chiaro con: requisiti (incl. Gyroflow AppImage e ffmpeg),
  installazione, uso, come calibrare la propria lente, limiti noti.
- Il bug OpenCL su AMD va documentato nel README come "comportamento atteso".
- Chiedere conferma all'utente su: nome del progetto, licenza, e se pubblicare
  i clip di test.
