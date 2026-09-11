from flask import Flask, jsonify, request
from flask_cors import CORS
import subprocess
import time
import os
import zipfile
import tempfile
import json

app = Flask(__name__)

# Tüm origin'lerden gelen isteklere izin ver (Vercel frontend → Render backend)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# --- FAIRY-STOCKFISH MOTOR KURULUMU ---
if os.name == 'nt':
    # Windows (lokal geliştirme)
    exe_yolu = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fairy-stockfish-largeboard_x86-64-bmi2.exe")
else:
    # Linux (Render sunucusu) - /tmp/ klasöründe çalıştır
    exe_yolu = "/tmp/fairy-stockfish-largeboard_x86-64"

    if not os.path.exists(exe_yolu):
        with zipfile.ZipFile("motor.zip", 'r') as zip_ref:
            zip_ref.extractall("/tmp/")
        os.chmod(exe_yolu, 0o755)

# Geçici variants.ini dosyaları için dizin
VARIANTS_DIR = tempfile.mkdtemp(prefix="wsn_variants_")
# Varsayılan variants.ini dosyasını kopyala
DEFAULT_VARIANTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "variants.ini")

@app.route('/')
def index():
    return jsonify({
        "proje": "TÜBİTAK 1001 - WSN Otonom Karar API",
        "durum": "Sistem Aktif",
        "motor": "Fairy-Stockfish Largeboard",
        "api_endpoints": {
            "karar": "/api/karar",
            "health": "/api/health"
        }
    })

@app.route('/api/health', methods=['GET'])
def health():
    """Sunucu uyanık mı kontrolü (Render cold-start bypass)"""
    motor_mevcut = os.path.exists(exe_yolu)
    return jsonify({
        "durum": "aktif",
        "motor_hazir": motor_mevcut,
        "motor": "fairy-stockfish-largeboard"
    })

@app.route('/api/karar', methods=['GET', 'POST'])
def karar_al():
    baslangic = time.time()

    # --- Parametreleri al (GET veya POST) ---
    if request.method == 'POST':
        if request.is_json:
            veri = request.get_json()
        else:
            veri = request.form.to_dict()
    else:
        veri = request.args.to_dict()

    hamle_gecmisi = veri.get('hamle_gecmisi', '')
    fen = veri.get('fen', '')
    varyant_adi = veri.get('varyant_adi', '')
    variants_ini_icerik = veri.get('variants_ini', '')

    try:
        # --- Variants.ini dosyasını hazırla ---
        kullanilan_variants_path = DEFAULT_VARIANTS_PATH

        if variants_ini_icerik:
            # Kullanıcının yüklediği variants.ini'yi geçici dosyaya yaz
            gecici_ini = os.path.join(VARIANTS_DIR, f"variants_{int(time.time())}.ini")
            with open(gecici_ini, 'w', encoding='utf-8') as f:
                f.write(variants_ini_icerik)
            kullanilan_variants_path = gecici_ini

            # Eğer varyant adı gönderilmemişse, ini'den çıkar
            if not varyant_adi:
                for satir in variants_ini_icerik.split('\n'):
                    satir = satir.strip()
                    if satir.startswith('[') and ':' in satir:
                        varyant_adi = satir.split('[')[1].split(':')[0].strip()
                        break

        # --- Motoru başlat ---
        motor = subprocess.Popen(
            exe_yolu,
            universal_newlines=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # UCI Handshake
        motor.stdin.write("uci\n")
        motor.stdin.flush()

        # uciok'u bekle
        while True:
            satir = motor.stdout.readline().strip()
            if satir == "uciok":
                break

        # Variants.ini dosyasını yükle
        variants_abs_path = os.path.abspath(kullanilan_variants_path)
        motor.stdin.write(f"setoption name VariantPath value {variants_abs_path}\n")

        # Varyant seçimi
        if varyant_adi:
            motor.stdin.write(f"setoption name UCI_Variant value {varyant_adi}\n")

        motor.stdin.write("isready\n")
        motor.stdin.flush()

        # readyok'u bekle
        while True:
            satir = motor.stdout.readline().strip()
            if satir == "readyok":
                break

        # Yeni oyun
        motor.stdin.write("ucinewgame\n")

        # Pozisyon ayarla
        if fen:
            if hamle_gecmisi:
                motor.stdin.write(f"position fen {fen} moves {hamle_gecmisi}\n")
            else:
                motor.stdin.write(f"position fen {fen}\n")
        elif hamle_gecmisi:
            motor.stdin.write(f"position startpos moves {hamle_gecmisi}\n")
        else:
            motor.stdin.write("position startpos\n")

        # Arama başlat
        motor.stdin.write("go depth 10\n")
        motor.stdin.flush()

        bestmove = None
        cp_skoru = None

        while True:
            satir = motor.stdout.readline().strip()

            if "score cp" in satir:
                parcalar = satir.split()
                try:
                    cp_indeksi = parcalar.index("cp")
                    cp_skoru = int(parcalar[cp_indeksi + 1])
                except (ValueError, IndexError):
                    pass

            if satir.startswith("bestmove"):
                bestmove = satir.split()[1]
                break

        motor.terminate()
        gecen_sure = round((time.time() - baslangic) * 1000, 2)

        # Geçici dosyayı temizle
        if variants_ini_icerik and os.path.exists(gecici_ini):
            try:
                os.remove(gecici_ini)
            except OSError:
                pass

        return jsonify({
            "gelen_veri": hamle_gecmisi,
            "fen": fen if fen else "startpos",
            "varyant": varyant_adi if varyant_adi else "standart",
            "bestmove": bestmove,
            "cp_skoru": cp_skoru,
            "gecikme_ms": gecen_sure,
            "motor": "fairy-stockfish-largeboard"
        })

    except Exception as e:
        return jsonify({
            "hata": str(e),
            "mesaj": "Sistem motoru tetikleyemedi."
        }), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)