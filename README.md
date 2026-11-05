# Autonomous Decision & Topology Visualizer System

Web-based routing decision and topology analysis panel built on **Fairy-Stockfish Largeboard** and **Flask**. Topologies are modeled as board variants (FEN + `.ini` rules), evaluated via UCI search (`go depth` and `go mate`), filtered against a Centipawn (CP) threshold, and exported as JSON or PDF reports.

- **Live Application:** [https://oldchess.vercel.app/](https://oldchess.vercel.app/)

---

## Project Structure

```text
├── api/
│   └── index.py              # Vercel Serverless entry point (imports Flask app)
├── lang/
│   └── lang.json             # Unified EN/TR translation catalog (all keys in one file)
├── app.py                    # Flask backend API & Fairy-Stockfish UCI process manager
├── index.html                # Main topology visualizer, decision engine panel, and CP filter UI
├── scenarios.html            # Copy-paste FEN & custom scenario management page
├── variants.ini              # Default 10x10 cylindrical topology definition
├── standard_chess.ini        # Standard 8x8 topology config
├── shatranj.ini              # 9th-century Shatranj (Ferz & Alfil rules) config
├── capablanca.ini            # 10x8 extended grid (Archbishop & Chancellor) config
├── crazyhouse.ini            # 8x8 dynamic node injection (drop = true) config
├── xiangqi.ini               # 10x9 Xiangqi topology config
├── engine.zip                # Linux x86-64 Fairy-Stockfish binary archive for Vercel
├── requirements.txt          # Python dependencies (Flask, flask-cors, gunicorn)
└── vercel.json               # Vercel routing & rewrite rules
```

---

## Core Features

1. **Topology Visualizer (`index.html`):**
   - Supports `8x8` (Standard, Shatranj, Crazyhouse), `10x8` (Capablanca), and `10x9` (Xiangqi) grids.
   - Move history navigation (`Start`, `Back`, `Forward`) and `Flip` board toggle (allows playing as Black while the engine responds as White).
   - Shatranj mode labels `Ferz (F)` and `Alfil (A)` pieces and enforces `[variant:shatranj]` inheritance.
2. **Decision Engine & Mansuba Solver (`app.py`):**
   - **Depth Search (`go depth 1..25`):** Evaluates best next-hop route (`bestmove`), full Principal Variation (`pv`), and Centipawn (`cp`) score.
   - **Mate Search (`go mate N`):** Dedicated problem/mansuba solver that searches for forced mate in `N` moves and parses `score mate` output.
   - **Autonomous Simulation:** Plays both sides step-by-step on the board for live testing.
3. **Scenario Pool (`scenarios.html`):**
   - Opens in a separate tab for adding, saving, and deleting custom FEN strings via copy-paste.
   - Syncs across open tabs via `localStorage`.
4. **CP Filter & Reporting:**
   - Compares engine score against a user-defined minimum CP threshold (`APPROVED` / `REJECTED`).
   - Exports single-column **PDF** and **JSON** decision reports in Turkish or English.

---

## API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/health` | `GET` | Checks server status and engine binary availability. |
| `/api/decision` | `POST` | Runs engine analysis (`fen`, `variant_name`, `variants_ini`, `depth`, `mode`, `mate_moves`). |
| `/api/legalmoves` | `POST` | Runs `go perft 1` and returns legal moves for the active FEN and variant. |
| `/api/external/random-puzzle` | `GET` | Fetches a random topology FEN from the Chess.com public API. |

---

## Local Setup

```bash
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000` (or serve `index.html` locally). On Windows, place `fairy-stockfish-largeboard_x86-64-bmi2.exe` in the project root.
