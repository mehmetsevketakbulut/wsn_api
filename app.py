from flask import Flask, jsonify, request
import subprocess
import time
import os
import zipfile

app = Flask(__name__)

# İŞLETİM SİSTEMİNE GÖRE DİNAMİK YOL VE ZIP ÇIKARMA (MÜHENDİSLİK ÇÖZÜMÜ)
if os.name == 'nt': 
    # Senin bilgisayarın (Windows)
    exe_yolu = r"C:\Users\msı\Downloads\stockfish-windows-x86-64-avx2\stockfish\stockfish-windows-x86-64-avx2.exe"
else: 
    # Vercel'de kodlar salt-okunurdur, sadece /tmp/ (Geçici RAM) klasöründe dosya çalıştırabiliriz
    exe_yolu = "/tmp/stockfish-ubuntu-x86-64" 
    
    # Eğer motor henüz zip'ten çıkmamışsa, çıkartıp yetki veriyoruz
    if not os.path.exists(exe_yolu):
        with zipfile.ZipFile("motor.zip", 'r') as zip_ref:
            zip_ref.extractall("/tmp/")
        os.chmod(exe_yolu, 0o755)

@app.route('/')
def index():
    return jsonify({
        "proje": "TÜBİTAK 1001 - WSN Otonom Karar API",
        "durum": "Sistem Aktif",
        "test_linki": "/api/karar?hamle_gecmisi=e2e4"
    })

@app.route('/api/karar', methods=['GET'])
def karar_al():
    baslangic = time.time()
    hamle_gecmisi = request.args.get('hamle_gecmisi', '')
    
    try:
        # Motoru başlat
        motor = subprocess.Popen(exe_yolu, universal_newlines=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        
        # UCI Handshake
        motor.stdin.write("uci\n")
        motor.stdin.write("isready\n")
        
        if hamle_gecmisi:
            motor.stdin.write(f"position startpos moves {hamle_gecmisi}\n")
        else:
            motor.stdin.write("position startpos\n")
            
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
                except:
                    pass
                    
            if satir.startswith("bestmove"):
                bestmove = satir.split()[1]
                break
                
        motor.terminate() 
        gecen_sure = round((time.time() - baslangic) * 1000, 2)
        
        return jsonify({
            "gelen_veri": hamle_gecmisi,
            "bestmove": bestmove,
            "cp_skoru": cp_skoru,
            "gecikme_ms": gecen_sure,
            "uyari": "None"
        })
        
    except Exception as e:
        return jsonify({"hata": str(e), "mesaj": "Sistem motoru tetikleyemedi."})

if __name__ == '__main__':
    app.run(debug=True, port=5000)