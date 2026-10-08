# -*- coding: utf-8 -*-
"""negura：標高の事前キャッシュ（緯度経度グリッド・format 2）を作る。2026-10-08 課題#635。
@owns negura の標高事前キャッシュ（data/negura_elev_g1.json）の生成

平井の fetch_elev_cache.py（format 1＝generateFlat()の格子を1行1行再現し、siteAdj完全一致の時だけ使う）
とは考え方が違う: 敷地の位置・角度・倍率（siteAdj）から独立した「地面の格子」を緯度経度で持ち、
アプリ側は今の必要範囲を含んでいれば切り出して使う。腱さんが「敷地を調整」で動かしても無効にならない。

格子: 原点(lat0,lon0)から東へ c*G m・北へ r*G m の点。dLat=G/111320, dLon=G/(111320*cos(lat0))。
      elev は row-major（r=0 が南端の行、c=0 が西端）。null=取得失敗。
範囲: SITES.negura の shape bbox（公簿21,004㎡・倍率1.0）＋アプリの margin 8m ＋ 微調整の余裕 SLACK m。
中断に強く: 5行ごとに <out>.partial.json へ書き出し、再実行すると続きから取る。

使い方: python tools/negura/fetch_elev_cache.py data/negura_elev_g1.json
"""
import json, math, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8', errors='replace')

ANCHOR = (35.1116207, 139.0058319)      # SITES.negura.anchor（＝shape頂点平均＝FLAT_GRIDのcLat/cLon）
BBOX_E = (-124.0, 130.9)                # SITES.negura.shape の bbox（m）
BBOX_N = (-59.5, 69.2)
MARGIN, SLACK, G = 8, 25, 1
OUT = sys.argv[1] if len(sys.argv) > 1 else 'negura_elev_g1.json'
PART = OUT + '.partial.json'
CONC = 6

mLat = 111320.0
mLon = 111320.0 * math.cos(math.radians(ANCHOR[0]))
e0 = BBOX_E[0] - MARGIN - SLACK; e1 = BBOX_E[1] + MARGIN + SLACK
n0 = BBOX_N[0] - MARGIN - SLACK; n1 = BBOX_N[1] + MARGIN + SLACK
cols = int(math.floor((e1 - e0) / G)) + 1
rows = int(math.floor((n1 - n0) / G)) + 1
LAT0 = ANCHOR[0] + n0 / mLat
LON0 = ANCHOR[1] + e0 / mLon
dLat = G / mLat
dLon = G / (111320.0 * math.cos(math.radians(LAT0)))


def fetch(lat, lon):
    u = ('https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php'
         '?lon=%.8f&lat=%.8f&outtype=JSON' % (lon, lat))
    for i in range(5):
        try:
            j = json.loads(urllib.request.urlopen(u, timeout=20).read())
            v = j.get('elevation')
            return None if v in (None, '-----') else round(float(v), 1)
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None


done = []
if os.path.exists(PART):
    p = json.load(open(PART))
    if (p['cols'], p['rows'], p['lat0'], p['lon0']) == (cols, rows, LAT0, LON0):
        done = p['done_rows']
print('grid %d x %d = %d pts, resume from row %d' % (cols, rows, cols * rows, len(done)), flush=True)
t0 = time.time()
with ThreadPoolExecutor(CONC) as ex:
    for r in range(len(done), rows):
        lat = LAT0 + r * dLat
        done.append(list(ex.map(lambda c: fetch(lat, LON0 + c * dLon), range(cols))))
        if r % 5 == 0 or r == rows - 1:
            json.dump({'cols': cols, 'rows': rows, 'lat0': LAT0, 'lon0': LON0, 'done_rows': done}, open(PART, 'w'))
            print('row %d/%d  %.0fs' % (r + 1, rows, time.time() - t0), flush=True)

flat = [v for row in done for v in row]
out = {'format': 2, 'site': 'negura', 'g': G, 'lat0': LAT0, 'lon0': LON0, 'dLat': dLat, 'dLon': dLon,
       'cols': cols, 'rows': rows, 'missing': sum(v is None for v in flat),
       'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
       'note': '緯度経度グリッド。row-major、r=0が南端・c=0が西端。index.html generateFlat() が今の必要範囲を切り出して使う',
       'elev': flat}
json.dump(out, open(OUT, 'w', encoding='utf-8'), separators=(',', ':'), ensure_ascii=False)
os.remove(PART)
print('wrote %s  %d pts  missing %d  %d bytes' % (OUT, len(flat), out['missing'], os.path.getsize(OUT)), flush=True)
