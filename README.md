# GoPro Anamorphic Toolkit (gat)

Strumento Linux per elaborare i clip di una **GoPro HERO11 Black** girati con
una lente anamorfica **Neewer LS-56 1.2x** (non ufficiale) e produrre video
pronti all'uso per la TV o il montaggio.

La pipeline fa tre cose:

1. **Stabilizzazione** opzionale con **Gyroflow**, usando i dati grezzi del
   giroscopio (traccia GPMF) e un **profilo lente calibrato** dall'utente —
   non la stabilizzazione interna della GoPro (HyperSmooth), che con la lente
   non ufficiale produce ondeggiamenti.
2. **Desqueeze** anamorfico (fattore 1.2x orizzontale).
3. **Export** leggero in H.265 (default 1080p, `tag:v hvc1` per compatibilità
   Apple/TV).

> Lo sviluppo procede per fasi. **Fase 1 (core CLI)** e **Fase 2 (GUI PySide6)**
> sono complete. La **Fase 3 (AppImage)** è in arrivo.

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

- Risoluzione **2.7K**: `2704x1520` (16:9) o `2704x2028` (4:3).
- Lente **Wide** (la distorsione fisheye viene corretta da Gyroflow col profilo).
- **HyperSmooth SPENTO**.
- Usa **sempre i file ORIGINALI** dalla scheda SD: i dati giroscopio (GPMF) si
  perdono se il file passa da app/editor che ricodificano.

## Uso — GUI

```bash
gat-gui
```

Interfaccia minimale: scegli una cartella (o trascina file .MP4), controlla i
metadati rilevati e gli avvisi nella tabella, seleziona formato e qualità,
spunta *Stabilizza con Gyroflow*, indica la cartella di output e premi **Avvia**.
Barra di avanzamento e log integrati.

## Uso — CLI

```bash
# Stabilizza + desqueeze, formato scelto automaticamente in base all'input
gat /percorso/clip_originali /percorso/output

# Solo desqueeze (niente Gyroflow)
gat input/ output/ --no-stabilize

# Forza il formato cinema 2.13:1 a 1920 px di larghezza
gat input/ output/ --aspect 2.13:1 --width 1920

# Indica un Gyroflow e un profilo lente specifici
gat input/ output/ --gyroflow ~/Applications/Gyroflow.AppImage --calibration mio_profilo.json

# Solo ispezione: metadati + validazione, senza elaborare
gat input/ --probe
```

### Formati di output

| Input                | `--aspect auto` produce | Risultato      |
|----------------------|-------------------------|----------------|
| 4:3 (2704x2028)      | 16:9                    | 1920x1080 (TV) |
| 16:9 (2704x1520)     | 2.13:1 (cinema)         | 1920x900 ca.   |

Tutto è parametrizzabile: `--aspect`, `--width`, `--squeeze`, `--crf`,
`--preset`, `--zoom`.

- **`--zoom auto`** (default): con stabilizzazione = 1.0 (Gyroflow ritaglia già
  i bordi); senza stabilizzazione applica un crop anti-vignettatura (~1.3x in
  4:3, ~1.2x in 16:9).

### Configurazione

I default si possono salvare in `~/.config/gat/config.json`:

```bash
gat input/ output/ --crf 20 --width 2560 --save-config   # salva ed esce
```

Le opzioni da riga di comando hanno sempre la priorità sul file di config.

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
