# GoPro Anamorphic Toolkit (gat)

Strumento Linux per elaborare i clip di una **GoPro HERO11 Black** girati con
una lente anamorfica **Neewer LS-56 1.2x** (non ufficiale) e produrre video
pronti all'uso per la TV o il montaggio.

Il tool tratta **un solo formato: clip 2.7K 16:9** (2704×1520). Il profilo lente
calibrato è valido solo per questo formato; i file non conformi (es. 4:3) vengono
**segnalati e saltati**, non elaborati.

La pipeline fa tre cose:

1. **Stabilizzazione** opzionale con **Gyroflow**, usando i dati grezzi del
   giroscopio (traccia GPMF) e un **profilo lente calibrato** dall'utente —
   non la stabilizzazione interna della GoPro (HyperSmooth), che con la lente
   non ufficiale produce ondeggiamenti.
2. **Desqueeze** anamorfico 1.2x → formato cinematografico ~2.13:1.
3. **Export** a **piena risoluzione** (~3244×1520, nessun downscale) in H.265 di
   alta qualità (CRF 18, preset slow, `tag:v hvc1` per compatibilità Apple/TV).

> **Nota onesta sulla qualità:** il desqueeze e la stabilizzazione *ricampionano*
> l'immagine, quindi l'output è *near-original* (qualità molto alta a piena
> risoluzione) ma non bit-identico alla sorgente. Il CRF basso evita di
> aggiungere perdite percepibili sopra al ricampionamento.

> Sviluppo per fasi, tutte complete: **Fase 1 (core CLI)**, **Fase 2 (GUI
> PySide6)** e **Fase 3 (packaging AppImage)**.

---

## Requisiti

- **Linux** con **Python ≥ 3.10**.
- **ffmpeg / ffprobe** (con `libx265`):
  ```bash
  sudo apt install ffmpeg
  ```
- **Gyroflow** (solo per la stabilizzazione): scarica l'AppImage da
  <https://gyroflow.xyz> — **non è incluso** in questo progetto. Vedi sotto.
- Un **profilo lente calibrato** per la tua combinazione camera + lente +
  impostazioni. Nel repo è incluso `resources/neewer_lens.json` come default,
  ma **è specifico del setup dell'autore**: per risultati ottimali calibra la
  tua lente (vedi *Calibrazione*).

## Installazione

```bash
git clone https://github.com/bianchi-john/GoProNeewer1.2xAnamorphic.git
cd GoProNeewer1.2xAnamorphic
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Questo installa il comando `gat` (CLI). Per la **GUI** installa anche PySide6:

```bash
pip install -e ".[gui]"
```

che aggiunge il comando `gat-gui`.

## Formato di ripresa consigliato

Verificato sul campo:

- Risoluzione **2.7K 16:9**: `2704x1520` (unico formato supportato).
- Lente **Wide** (la distorsione fisheye viene corretta da Gyroflow col profilo).
- **HyperSmooth SPENTO**.
- Usa **sempre i file ORIGINALI** dalla scheda SD: i dati giroscopio (GPMF) si
  perdono se il file passa da app/editor che ricodificano.

## Uso — GUI

```bash
gat-gui
```

Interfaccia minimale in inglese con tema scuro: aggiungi una cartella (o trascina
file .MP4), controlla stato e avvisi nella tabella (i file non 16:9 sono marcati
*Skip*), usa il grande **toggle Stabilize** (ON/OFF, usa Gyroflow + profilo lente
quando acceso), scegli la cartella di output e premi **Start**. Le impostazioni
avanzate (percorso Gyroflow, CRF, preset x265) sono in una sezione *Advanced
options* nascosta di default. Barra di avanzamento e log integrati.

## Uso — CLI

```bash
# Stabilizza + desqueeze a piena risoluzione (default di alta qualità)
gat /percorso/clip_originali /percorso/output

# Solo desqueeze (niente Gyroflow)
gat input/ output/ --no-stabilize

# Indica un Gyroflow e un profilo lente specifici
gat input/ output/ --gyroflow ~/Applications/Gyroflow.AppImage --calibration mio_profilo.json

# Solo ispezione: metadati + validazione, senza elaborare
gat input/ --probe
```

### Output

Un solo formato in ingresso (**2.7K 16:9**, 2704×1520) → desqueeze 1.2x →
**~3244×1520** a piena risoluzione (cinema ~2.13:1). I file 4:3 o con
risoluzione diversa vengono segnalati e saltati.

Parametri avanzati (già impostati su valori di alta qualità):
`--crf` (default 18), `--preset` (default slow), `--squeeze` (1.2), `--zoom`.

- **`--zoom auto`** (default): con stabilizzazione = 1.0 (Gyroflow ritaglia già
  i bordi); senza stabilizzazione applica un crop anti-vignettatura ~1.2x.

### Configurazione

I default si possono salvare in `~/.config/gat/config.json`:

```bash
gat input/ output/ --crf 16 --preset slower --save-config   # salva ed esce
```

Le opzioni da riga di comando hanno sempre la priorità sul file di config.

## AppImage (installazione senza Python)

È possibile distribuire l'app come singolo file **AppImage** (include Python +
PySide6 + `gat` + profilo lente). **Gyroflow e ffmpeg NON sono inclusi**: restano
requisiti esterni che l'utente installa/scarica a parte.

Costruzione:

```bash
pip install python-appimage
pip install -e .                      # rende 'gat' importabile (local+gat)
packaging/build_appimage.sh          # -> packaging/GoProAnamorphic-x86_64.AppImage
```

Uso dell'AppImage:

```bash
./GoProAnamorphic-x86_64.AppImage                    # avvia la GUI
./GoProAnamorphic-x86_64.AppImage cli input/ output/ # usa la CLI
```

> L'AppImage richiede **glibc ≥ 2.28** (distro recenti). Richiede comunque
> **ffmpeg** nel sistema e, per la stabilizzazione, l'**AppImage di Gyroflow**
> indicata nelle impostazioni.

## Calibrazione della propria lente

Il profilo incluso è calibrato per *HERO11 + Neewer LS-56 1.2x + Wide 2.7K*
dell'autore (reprojection error ~1.27). Per il tuo setup:

1. Gira un video della **scacchiera** di calibrazione (Gyroflow Lens Calibrator).
2. Nel calibratore imposta **Input horizontal stretch = 1.2**.
3. Esporta il profilo `.json` e passalo con `--calibration mio_profilo.json`
   (o sostituisci `resources/neewer_lens.json`).

## Comportamento atteso: errori OpenCL/CUDA su hardware AMD

Su alcune macchine (es. AMD Ryzen) Gyroflow stampa ripetutamente messaggi come:

```
Failed to initialize OpenCL Platform::list ...
Cannot load libcuda.so.1
libamfrt64.so.1 ...
```

**Non sono errori fatali.** Gyroflow ricade su `wgpu` e completa il rendering.
Il toolkit li riconosce, li marca come `[gyroflow:ignorato]` nel log e giudica
il successo dalla presenza del file `_stabilized` (e dalla riga `Done in …s`).

### AppImage senza FUSE

Se il sistema non ha FUSE, il toolkit esegue l'AppImage di Gyroflow in modalità
`APPIMAGE_EXTRACT_AND_RUN=1` (estrae ed esegue senza montare), quindi funziona
comunque.

## Limiti noti

- Testato su GoPro **HERO11 Black** + **Neewer LS-56 1.2x**. Altre combinazioni
  richiedono un profilo lente proprio.
- Il desqueeze assume squeeze orizzontale 1.2 e verticale 1.0.
- Solo Linux (per ora).

## Sviluppo

```bash
pip install -e ".[dev]"
pytest -q
```

I clip di test reali sono in `gopro/` (versionati con **Git LFS**). Serve
`git lfs` installato per scaricarli:

```bash
sudo apt install git-lfs && git lfs install && git lfs pull
```

## Licenza

[MIT](LICENSE) © 2026 John Bianchi

Gyroflow è un progetto separato (GPLv3), **non incluso** qui: va scaricato
dall'utente.
