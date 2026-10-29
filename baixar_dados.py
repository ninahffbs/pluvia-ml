"""Baixa as fontes verificadas. Rode no seu terminal normal (fora do sandbox):
    python3 baixar_dados.py ./raw
So biblioteca padrao. Depois me mande o conteudo de ./raw para eu avaliar a qualidade."""
import sys, time, urllib.request, urllib.error, urllib.parse, pathlib

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "raw"); out.mkdir(exist_ok=True)

falhas = []

def get(url, dest, tentativas=8):
    """Baixa com retomada (Range) e novas tentativas; nao aborta o script se um arquivo falhar."""
    path = out / dest
    marcador = out / (dest + ".ok")
    if marcador.exists():
        print("ja baixado:", dest); return
    for t in range(1, tentativas + 1):
        feito = path.stat().st_size if path.exists() else 0
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        if feito:
            req.add_header("Range", f"bytes={feito}-")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                if feito and r.status != 206:      # servidor ignorou o Range: recomeca
                    feito = 0
                cr = r.headers.get("Content-Range")
                cl = r.headers.get("Content-Length")
                total = int(cr.split("/")[-1]) if cr else (int(cl) + feito if cl else None)
                with open(path, "ab" if feito else "wb") as f:
                    while chunk := r.read(1 << 16):
                        f.write(chunk)
            if total and path.stat().st_size < total:   # read() em partes nao acusa corte de conexao
                raise IOError(f"incompleto: {path.stat().st_size} de {total} bytes")
            marcador.touch()
            print("ok:", dest, path.stat().st_size, "bytes"); return
        except urllib.error.HTTPError as e:
            if e.code == 416:                      # ja estava completo
                marcador.touch(); print("ok:", dest); return
            print(f"  tentativa {t}/{tentativas} {dest}: HTTP {e.code}")
        except Exception as e:
            print(f"  tentativa {t}/{tentativas} {dest}: {e}")
        time.sleep(2 * t)
    falhas.append(dest)

# F01: Defesa Civil Recife (IDs de recurso verificados via API; 2020-2025 tem uploads duplicados, usar o mais recente)
base = "https://dados.recife.pe.gov.br/dataset/ebda936c-f15a-4e0d-b8b6-5a9e270b0b67/resource/{}/download/atendimentos-{}.csv"
recursos = {2024: "7c7bb871-3906-4d82-8993-857c9e6f137b", 2023: "921d87c7-5ace-4856-9e3f-c31521259c36",
            2022: "10203dd4-9052-4a76-95eb-fd858aa053d4", 2021: "bf6f5af8-3556-425c-bfec-0eddccdeeb73",
            2020: "559ce500-deab-467d-862e-cf50332a9c26", 2019: "9bb859e1-19ae-4b95-9246-139b9273846f",
            2018: "a3a25520-de12-4f56-ae05-6dc1ec4c6207", 2017: "40e0558f-dc49-4ec7-b5e6-5a791703ae34",
            2016: "932fee1e-80fd-49f8-9ae3-6e8dd96e33a3", 2015: "9a5103f7-6bd0-4694-90d6-7e776b1e372d",
            2014: "b81bf4cc-ae19-4a43-94a7-f11b3e0b662b"}
for ano, rid in recursos.items():
    get(base.format(rid, ano), f"defesa_civil_{ano}.csv")

# F02: INMET (contem todas as estacoes; filtrar A301 depois)
for ano in range(2014, 2027):
    get(f"https://portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip", f"inmet_{ano}.zip")

# F05 (so para conferir que termina em 1968): UHSLC Recife id 712
q = urllib.parse.quote('time,sea_level,quality&uhslc_id=712', safe="=&,")
get(f"https://uhslc.soest.hawaii.edu/erddap/tabledap/global_hourly_rqds.csv?{q}", "uhslc_recife_712.csv")

print("\nFalhas:", falhas if falhas else "nenhuma")
