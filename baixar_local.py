"""Baixa limites de bairros, faixas marginais e elevacao (grade ~250 m) do Recife.
Rode no seu terminal:  python3 baixar_local.py ./raw
Gera: raw/local/bairros.geojson, raw/local/faixas_marginais.geojson, raw/local/elevacao_grade.csv"""
import sys, json, math, time, csv, pathlib, urllib.request

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "raw") / "local"; out.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}

def baixa(url, dest, tentativas=6):
    p = out / dest
    if p.exists() and p.stat().st_size > 1000:
        print("ja existe:", dest); return
    for t in range(1, tentativas + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                dados = r.read()
            json.loads(dados)                          # valida JSON completo (detecta corte de conexao)
            p.write_bytes(dados); print("ok:", dest, len(dados), "bytes"); return
        except Exception as e:
            print(f"  tentativa {t}/{tentativas} {dest}: {e}"); time.sleep(2 * t)
    sys.exit(f"FALHOU: {dest}")

baixa("https://dados.recife.pe.gov.br/dataset/ce23d3f4-7474-44d3-b310-19f3afcebf4a/resource/d5f956ce-7e1f-4c74-839b-06cb490c3721/download/limites-dos-bairros-2023.geojson", "bairros.geojson")
baixa("https://dados.recife.pe.gov.br/dataset/1bf02d9c-2754-41cc-aede-1ac8e237f166/resource/81310c02-4bb8-4fea-b676-0c42977b4aef/download/faixas-marginais-dos-recursos-hidricos.geojson", "faixas_marginais.geojson")

# ---- grade de pontos dentro dos bairros
gj = json.load(open(out / "bairros.geojson", encoding="utf-8"))
def aneis(g):
    if g["type"] == "Polygon": return [g["coordinates"]]
    if g["type"] == "MultiPolygon": return g["coordinates"]
    return []
def dentro(x, y, poly):
    ext = poly[0]; c = False
    for (x1, y1), (x2, y2) in zip(ext, ext[1:] + ext[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1: c = not c
    if not c: return False
    for h in poly[1:]:                                 # buracos
        d = False
        for (x1, y1), (x2, y2) in zip(h, h[1:] + h[:1]):
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1: d = not d
        if d: return False
    return True

pts = [c[:2] for f in gj["features"] for p in aneis(f["geometry"]) for c in p[0]]
lon0, lat0 = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
if abs(lon0) > 180 or abs(lat0) > 90:
    sys.exit(f"Coordenadas nao parecem WGS84 (lon={lon0:.0f}, lat={lat0:.0f}): o GeoJSON esta em outro CRS. Me avise.")
passo = 250 / 111320                                   # ~250 m em graus
grade = []
lo, hi = min(p[0] for p in pts), max(p[0] for p in pts)
la, ha = min(p[1] for p in pts), max(p[1] for p in pts)
polys = [(i, p) for i, f in enumerate(gj["features"]) for p in aneis(f["geometry"])]
y = la
while y <= ha:
    x = lo
    while x <= hi:
        for i, p in polys:
            xs = [c[0] for c in p[0]]; ys = [c[1] for c in p[0]]
            if min(xs) <= x <= max(xs) and min(ys) <= y <= max(ys) and dentro(x, y, p):
                grade.append((i, round(x, 6), round(y, 6))); break
        x += passo
    y += passo
print("pontos na grade:", len(grade))

# ---- elevacao (Open-Meteo, modelo Copernicus 90 m), 100 pontos por chamada
with open(out / "elevacao_grade.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["idx_feature", "lon", "lat", "elev_m"])
    for k in range(0, len(grade), 100):
        lote = grade[k:k + 100]
        url = ("https://api.open-meteo.com/v1/elevation?latitude=" + ",".join(str(g[2]) for g in lote)
               + "&longitude=" + ",".join(str(g[1]) for g in lote))
        for t in range(1, 7):
            try:
                el = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read())["elevation"]
                break
            except Exception as e:
                print(f"  lote {k}: tentativa {t}: {e}"); time.sleep(3 * t)
        else:
            sys.exit(f"FALHOU lote {k}")
        for g, e in zip(lote, el): w.writerow([g[0], g[1], g[2], e])
        print(f"elevacao {min(k + 100, len(grade))}/{len(grade)}"); time.sleep(0.5)
print("pronto.")
