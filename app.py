from flask import Flask, jsonify, request
from flask_cors import CORS
import subprocess
import time
import os
import zipfile
import uuid
import json
import urllib.request

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VARIANTS_DIR = "/tmp" if os.name != "nt" else BASE_DIR
DEFAULT_VARIANTS_PATH = os.path.join(BASE_DIR, "variants.ini")


def _resolve_engine_path():
    """Locate or extract the Fairy-Stockfish engine binary."""
    if os.name == "nt":
        return os.path.join(BASE_DIR, "fairy-stockfish-largeboard_x86-64-bmi2.exe")

    linux_binary_path = "/tmp/fairy-stockfish-largeboard_x86-64"
    if not os.path.exists(linux_binary_path):
        archive_path = os.path.join(BASE_DIR, "engine.zip")
        if os.path.exists(archive_path):
            with zipfile.ZipFile(archive_path, "r") as zip_ref:
                zip_ref.extractall("/tmp/")
            os.chmod(linux_binary_path, 0o755)
    return linux_binary_path


ENGINE_BINARY_PATH = _resolve_engine_path()


def _parse_request_payload():
    """Extract parameters from POST JSON, form data, or GET query string."""
    if request.method == "POST":
        if request.is_json:
            return request.get_json() or {}
        return request.form.to_dict()
    return request.args.to_dict()


def _extract_variant_from_ini(ini_text):
    """Extract the variant name from a '[variant:parent]' section header."""
    for line in ini_text.split("\n"):
        cleaned = line.strip()
        if cleaned.startswith("[") and ":" in cleaned:
            return cleaned.split("[")[1].split(":")[0].strip()
    return ""


def _write_temp_variants_ini(variants_ini_content, variant_name):
    """
    Normalize and write custom variants.ini content to a temporary file.
    Returns (active_variants_path, temp_ini_path, resolved_variant_name).
    """
    if not variants_ini_content:
        return DEFAULT_VARIANTS_PATH, None, (variant_name or "").strip()

    temp_ini_path = os.path.join(
        VARIANTS_DIR, f"variants_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}.ini"
    )

    if isinstance(variants_ini_content, dict):
        section = variant_name or "custom_topology"
        lines = [f"[{section}:chess]"]
        for key, value in variants_ini_content.items():
            lines.append(f"{key} = {value}")
        ini_text = "\n".join(lines)
    elif isinstance(variants_ini_content, str):
        ini_text = variants_ini_content
    else:
        ini_text = str(variants_ini_content)

    # Normalize Windows CRLF (\r\n) to LF (\n) for Fairy-Stockfish compatibility
    ini_text = ini_text.replace("\r\n", "\n").replace("\r", "\n")

    with open(temp_ini_path, "w", encoding="utf-8", newline="\n") as temp_file:
        temp_file.write(ini_text)

    resolved_variant = (variant_name or "").strip()
    if not resolved_variant and ini_text:
        resolved_variant = _extract_variant_from_ini(ini_text)

    return temp_ini_path, temp_ini_path, resolved_variant


def _wait_for_uci_token(engine_proc, expected_token):
    """Read lines from engine stdout until expected_token is received."""
    while True:
        line = engine_proc.stdout.readline()
        if not line:
            break
        if line.strip() == expected_token:
            break


def _start_engine_process(variants_path, variant_name):
    """Spawn Fairy-Stockfish, initialize UCI, and load variant configuration."""
    engine_proc = subprocess.Popen(
        ENGINE_BINARY_PATH,
        universal_newlines=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )

    engine_proc.stdin.write("uci\n")
    engine_proc.stdin.flush()
    _wait_for_uci_token(engine_proc, "uciok")

    if variants_path and os.path.exists(variants_path):
        abs_variants_path = os.path.abspath(variants_path)
        engine_proc.stdin.write(f"setoption name VariantPath value {abs_variants_path}\n")

    if variant_name:
        engine_proc.stdin.write(f"setoption name UCI_Variant value {variant_name}\n")

    engine_proc.stdin.write("isready\n")
    engine_proc.stdin.flush()
    _wait_for_uci_token(engine_proc, "readyok")

    return engine_proc


def _configure_position(engine_proc, fen, move_history=""):
    """Send ucinewgame and position command to the initialized engine."""
    engine_proc.stdin.write("ucinewgame\n")
    if fen:
        if move_history:
            engine_proc.stdin.write(f"position fen {fen} moves {move_history}\n")
        else:
            engine_proc.stdin.write(f"position fen {fen}\n")
    elif move_history:
        engine_proc.stdin.write(f"position startpos moves {move_history}\n")
    else:
        engine_proc.stdin.write("position startpos\n")
    engine_proc.stdin.flush()


def _run_engine_search(engine_proc, search_mode, depth, mate_moves):
    """Run 'go depth' or 'go mate' search and parse UCI info/bestmove output."""
    if search_mode == "mate":
        engine_proc.stdin.write(f"go mate {mate_moves} movetime 25000\n")
    else:
        engine_proc.stdin.write(f"go depth {depth}\n")
    engine_proc.stdin.flush()

    best_move = None
    cp_score = None
    mate_score = None
    principal_variation = None
    reached_depth = None

    while True:
        raw_line = engine_proc.stdout.readline()
        if not raw_line:
            break
        line = raw_line.strip()
        tokens = line.split()

        if line.startswith("info") and "depth" in tokens:
            try:
                reached_depth = int(tokens[tokens.index("depth") + 1])
            except (ValueError, IndexError):
                pass

        if "pv" in tokens:
            try:
                pv_index = tokens.index("pv")
                principal_variation = " ".join(tokens[pv_index + 1 :])
            except ValueError:
                pass

        if "score" in tokens:
            try:
                score_index = tokens.index("score")
                score_type = tokens[score_index + 1]
                score_value = int(tokens[score_index + 2])
                if score_type == "cp":
                    cp_score = score_value
                    mate_score = None
                elif score_type == "mate":
                    mate_score = score_value
                    cp_score = None
            except (ValueError, IndexError):
                pass

        if line.startswith("bestmove"):
            if len(tokens) > 1:
                best_move = tokens[1]
            break

    return {
        "best_move": best_move,
        "cp_score": cp_score,
        "mate_score": mate_score,
        "principal_variation": principal_variation,
        "reached_depth": reached_depth,
    }


def _parse_perft_moves(engine_proc):
    """Execute 'go perft 1' and return the list of legal moves for the position."""
    engine_proc.stdin.write("go perft 1\n")
    engine_proc.stdin.flush()

    legal_move_list = []
    while True:
        raw_line = engine_proc.stdout.readline()
        if not raw_line:
            break
        line = raw_line.strip()
        if not line:
            continue

        if ": " in line and "Nodes" not in line:
            parts = line.split(": ")
            if len(parts) == 2 and parts[1].strip().isdigit():
                legal_move_list.append(parts[0].strip())

        if "Nodes searched:" in line:
            break

    return legal_move_list


def _shutdown_engine(engine_proc):
    """Gracefully terminate the engine subprocess."""
    if not engine_proc:
        return
    try:
        engine_proc.stdin.write("quit\n")
        engine_proc.stdin.flush()
    except Exception:
        pass
    try:
        engine_proc.terminate()
    except Exception:
        pass


def _cleanup_temp_file(file_path):
    """Remove a temporary file if it exists."""
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass


def _clamp_int(raw_value, default_val, min_val, max_val):
    """Safely convert raw_value to int and clamp within [min_val, max_val]."""
    try:
        parsed = int(raw_value)
    except (ValueError, TypeError):
        parsed = default_val
    return max(min_val, min(parsed, max_val))


@app.route("/")
def index():
    return jsonify(
        {
            "project": "Autonomous Decision & Topology Visualizer API",
            "status": "active",
            "engine": "Fairy-Stockfish Largeboard",
            "platform": "Vercel Serverless",
            "api_endpoints": {
                "decision": "/api/decision",
                "legalmoves": "/api/legalmoves",
                "health": "/api/health",
            },
        }
    )


@app.route("/api/health", methods=["GET"])
def health():
    engine_ready = os.path.exists(ENGINE_BINARY_PATH)
    return jsonify(
        {
            "status": "active",
            "engine_ready": engine_ready,
            "engine": "fairy-stockfish-largeboard",
        }
    )


@app.route("/api/decision", methods=["GET", "POST"])
def evaluate_decision():
    start_time = time.time()
    payload = _parse_request_payload()

    move_history = payload.get("move_history", "")
    fen = payload.get("fen", "")
    variant_name = payload.get("variant_name", "")
    variants_ini_content = payload.get("variants_ini", "")

    depth = _clamp_int(payload.get("depth", 12), default_val=12, min_val=1, max_val=40)
    search_mode = str(payload.get("mode", "depth")).lower()

    mate_moves = None
    if search_mode == "mate":
        mate_moves = _clamp_int(
            payload.get("mate_moves", 8), default_val=8, min_val=1, max_val=30
        )

    temp_ini_path = None
    engine_proc = None

    try:
        variants_path, temp_ini_path, resolved_variant = _write_temp_variants_ini(
            variants_ini_content, variant_name
        )
        engine_proc = _start_engine_process(variants_path, resolved_variant)
        _configure_position(engine_proc, fen, move_history)
        search_result = _run_engine_search(engine_proc, search_mode, depth, mate_moves)
        _shutdown_engine(engine_proc)
        _cleanup_temp_file(temp_ini_path)

        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        engine_name = os.path.basename(ENGINE_BINARY_PATH).split(".")[0]

        return jsonify(
            {
                "move_history": move_history,
                "fen": fen if fen else "startpos",
                "bestmove": search_result["best_move"],
                "full_solution": search_result["principal_variation"],
                "cp_score": search_result["cp_score"],
                "mate_score": search_result["mate_score"],
                "search_mode": search_mode,
                "mate_moves": mate_moves,
                "reached_depth": search_result["reached_depth"],
                "engine": engine_name,
                "variant": resolved_variant if resolved_variant else "standard",
                "latency_ms": elapsed_ms,
            }
        )

    except Exception as exc:
        _shutdown_engine(engine_proc)
        _cleanup_temp_file(temp_ini_path)
        return (
            jsonify({"error": str(exc), "message": "Engine execution failed."}),
            500,
        )


@app.route("/api/legalmoves", methods=["POST"])
def get_legal_moves():
    payload = request.get_json() or {}
    fen = payload.get("fen", "")
    variant_name = payload.get("variant_name", "")
    variants_ini_content = payload.get("variants_ini", "")

    temp_ini_path = None
    engine_proc = None

    try:
        variants_path, temp_ini_path, resolved_variant = _write_temp_variants_ini(
            variants_ini_content, variant_name
        )
        engine_proc = _start_engine_process(variants_path, resolved_variant)
        _configure_position(engine_proc, fen)
        legal_move_list = _parse_perft_moves(engine_proc)
        _shutdown_engine(engine_proc)
        _cleanup_temp_file(temp_ini_path)

        return jsonify({"legal_moves": legal_move_list})

    except Exception as exc:
        _shutdown_engine(engine_proc)
        _cleanup_temp_file(temp_ini_path)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/external/random-puzzle", methods=["GET"])
def fetch_random_puzzle():
    try:
        req = urllib.request.Request(
            "https://api.chess.com/pub/puzzle/random",
            headers={"User-Agent": "Autonomous-Decision-System"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            return jsonify(
                {
                    "success": True,
                    "fen": data.get("fen"),
                    "title": data.get("title", "Random Puzzle"),
                    "source": "Chess.com API",
                }
            )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
