# 平井1298：標高グリッドの事前キャッシュ化

## 背景・目的
「平坦度を計算」を押すたびに、平井物件（`SITES.hirai`）は1m格子で約7,900点前後を
国土地理院 標高APIへ毎回ライブ取得している（サイトが広いため、他物件より点数が多く待ち時間も長い）。
これを一度だけオフラインで取得してJSONファイルに焼き込み、以後はそのキャッシュを読むだけにして
毎回のAPI取得をなくす。対象は**まず平井（hirai）だけ**でよい（他物件は現状のライブ取得のままでよい）。

格子間隔は現状の1mのまま変更しない：国土地理院の標高API自体が「概ね1mメッシュ」のデータ
（index.html内のコメント「DEMは概ね1mメッシュ」を参照）なので、1mより細かくしても実質的な精度向上はない。

## 現状の関連コード（読んでから着手）
- `index.html` の `generateFlat()`（`async function generateFlat()` で検索）：
  - `siteLatLngs`（`buildSite()`が作る、`SITE.shape`と`siteAdj`から計算した敷地の緯度経度）から
    centroid `cLat`/`cLon` を求め、`mLat=111320, mLon=111320*Math.cos(rad(cLat))` でm換算。
  - `siteLatLngs` を `(e,n)` に変換 → `margin=8` を足した範囲で `eMin/eMax/nMin/nMax` を決定。
  - `g`（格子間隔、UIの `#fGrid` の値、既定1）で `cols=floor((eMax-eMin)/g)+1`、`rows`も同様。
  - 二重ループで `e=eMin+c*g, n=nMin+r*g` → `lat=cLat+n/mLat, lon=cLon+e/mLon` の各点を作り、
    `fetchOne(lat,lon)`（`apiUrl()`＝`https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php?lon=..&lat=..&outtype=JSON`）
    で標高を取得。結果を `FLAT_GRID={g,cols,rows,en0:{e:eMin,n:nMin},cLat,cLon,cells:[{e,n,lat,lon,elev,dh}]}` に格納。
- `function buildSite()`（`const cx,cy`＝`SITE.shape`の重心、`a0`＝重心基準のshoelace面積、
  `s=Math.sqrt(SITE.targetArea/a0)*siteAdj.scale`、`r=rad(siteAdj.rot)`、`lat0=siteAdj.lat,lon0=siteAdj.lon`、
  `SITE_XFORM={cx,cy,s,cr,sr,lat0,lon0,mLat,mLon}` を作り `shapeToLatLngs(SITE.shape, SITE_XFORM)` を返す）。
- `function defaultAdj(){return {lat:SITE.anchor.lat,lon:SITE.anchor.lon,rot:0,scale:1};}`
  → 平井は `siteAdj` を手で調整していない限りこれが使われる（`SITES.hirai.anchor={lat:35.0939428,lon:138.9677039}`）。
- `function flatGridSig(){ return JSON.stringify([CURRENT_SITE, siteAdj.lat, siteAdj.lon, siteAdj.rot, siteAdj.scale, g]); }`
  → 「格子を再取得すべきか」の判定に使っている既存の署名。キャッシュの有効性判定もこれと同じ4値＋gで揃える。
- `SITES.hirai` の定義（`hirai:  { id:'hirai', ... shape:[...], ...}`、index.html内で `hirai:` を検索）。
  `shape`は真北基準の実メートル、`targetArea:2876.50`（shoelace面積と1e-6㎡単位で一致済み・検算済み）。
- 参考：`_input/Hirai1298/build_hirai.py`, `build_split2.py`（同物件の座標処理で使ったPythonスクリプトの前例。
  スタイルの参考にしてよいが、それらは測量座標変換用で今回のタスクとは別物）。

## やること
### 1. 事前取得スクリプト（新規）
`_input/Hirai1298/fetch_elev_cache.py` を作成。**Python標準ライブラリのみ**（`requests`は未インストール、
`urllib.request`を使うこと）。内容：
1. 上記の `buildSite()`→格子生成のロジックを **Pythonで完全に再現**する
   （`SITE.shape`・`targetArea`はindex.htmlの値をそのまま転記、`siteAdj`は`defaultAdj()`と同じ値
   　`{lat:35.0939428, lon:138.9677039, rot:0, scale:1}`、`g=1`、`margin=8`）。
   JS側の計算式（centroid→a0→s→cr/sr→SITE_XFORM→shapeToLatLngs→siteLatLngsのcentroid cLat/cLon→
   e/n変換→eMin/eMax/nMin/nMax→cols/rows→各格子点のlat/lon）と**1行1行対応させて**実装し、
   浮動小数の丸め方まで含めてJS版と食い違いが出ないようにする（後述の検証で実際に突き合わせる）。
2. 生成した全格子点について、`https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php?lon={lon}&lat={lat}&outtype=JSON`
   にGETし、JSONの`elevation`を取得（`null`または`"-----"`なら欠測=Noneとして記録）。
   - `concurrent.futures.ThreadPoolExecutor`で並列数6程度（アプリ本体のCONC=8と同程度、公共APIへの
     配慮でやや控えめ）。1点あたり最大2回リトライ（タイムアウト・一時エラー時）。
   - 進捗を`print()`で定期的に出す（例：200点ごと）。全点で数千点あるため数分かかる想定。
3. 結果を `data/hirai_elev_g1.json`（新規ディレクトリ`data/`を作成）に保存。フォーマット：
   ```json
   {
     "site": "hirai",
     "g": 1,
     "adj": {"lat":35.0939428, "lon":138.9677039, "rot":0, "scale":1},
     "cLat": ..., "cLon": ..., "eMin": ..., "nMin": ..., "cols": ..., "rows": ...,
     "cells": [{"e":.., "n":.., "lat":.., "lon":.., "elev":..}, ...]
   }
   ```
   `cells`の並び順は生成時と同じ（r外側→cループ内側、generateFlat()と同じ順）にすること
   （index.html側はこの並びをそのままFLAT_GRID.cellsとして使う前提で読み込む）。
4. スクリプトを実際に実行し、`data/hirai_elev_g1.json` を生成する（このタスクの成果物として必須。
   「スクリプトを書いた」だけでは未完了）。欠測点が多い（例：1割超）場合は原因（座標が海上/範囲外等）を
   確認し、コメントとして記録する。

### 2. index.html：キャッシュ優先で読み込むよう修正
`generateFlat()` の冒頭、格子(`eMin/nMin/cols/rows/g`)を計算した**直後・ライブ取得ループに入る前**に、
以下を追加：
- `SITE.elevCache` が定義されていて、かつ `g===SITE.elevCache.g` かつ
  `siteAdj.lat/lon/rot/scale` が `SITE.elevCache.adj` と（浮動小数の誤差を許容して`1e-9`程度で）一致する場合、
  `fetch(SITE.elevCache.url)` でJSONを取得し、返ってきた `cols/rows/eMin/nMin` が
  今計算した値と一致することを確認した上で、`cells`をそのまま`FLAT_GRID`として採用する
  （ライブ`fetchOne()`ループを丸ごとスキップ）。`FLAT_GRID_SIG`も通常どおり設定し、
  `#flatProg`に「キャッシュ済み標高データを使用（API取得なし）：N点」のように出す。
  取得失敗・不一致時は**必ず既存のライブ取得ループにフォールバック**する（黙って空データにしない。
  他物件・キャッシュ未整備の状態には一切影響が出ないこと＝回帰リスクゼロを最優先）。
- `SITES.hirai` の定義に `elevCache:{url:'data/hirai_elev_g1.json', g:1, adj:{lat:35.0939428, lon:138.9677039, rot:0, scale:1}}`
  を追加する。

### 3. 検証（必須・省略不可）
- ブラウザで平井を選択→「平坦度を計算」を実行し、`read_network_requests`で
  `cyberjapandata2.gsi.go.jp`への通信が**発生していない**こと（キャッシュ経路を通っている証拠）を確認する。
- 得られた`FLAT_GRID`の数点（例：格子の四隅付近・中央付近、3〜5点）について、
  同じlat/lonで**実際にライブAPIを1回叩いて**標高値を突き合わせ、キャッシュ値と一致することを確認する
  （Python再現ロジックが微妙にズレていないかの検算。誤差が出たらPython側の式をJSと再度突き合わせて直す）。
- 従来のライブ取得の物件（例：hannan）で「平坦度を計算」が今までどおり動くこと（キャッシュ分岐が
  他物件に影響していないこと）も確認する。
- 面積表・使える面積最大化ボタンなど、既存の平坦度機能が平井でも数値的に壊れていないこと
  （キャッシュ導入前後で同じ基準点なら同じ使える面積になること）を確認する。

## 完了条件
- `_input/Hirai1298/fetch_elev_cache.py`、`data/hirai_elev_g1.json`、`index.html`の変更が揃っている。
- 上記「検証」が実測で確認できている（未検証の見込みで完了報告しない）。
- 作業単位ごとにコミット（スクリプト＋データ生成／index.html配線、の最低2コミット目安）し、
  `WORKLOG.md`に追記する（このファイルの内容と背景も要約して残すこと）。
- 完了後、このファイル（`docs/task_hirai_elev_cache.md`）は削除してよい（役目を終えた指示書のため）。
