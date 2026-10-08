# 指示書: 標高の事前キャッシュを「敷地を動かしても効く」作りに変える（課題#635）

作業場所: **worktree `C:\Claude\52_kouteisa\.claude\worktrees\kadai-635-elevcache`**（本体では他セッションが稼働中。
本体 `C:\Claude\52_kouteisa` 直下のファイルには一切書かないこと）。

## 背景
新物件 negura（220m×111m、公簿21,004㎡）は格子1mだと平坦度の標高取得が約3万点になる。平井と同じ事前キャッシュを
作りたいが、今の `generateFlat()` のキャッシュ判定は **`siteAdj`（敷地の位置・角度・倍率）の完全一致** を要求しており、
腱さんが「敷地を調整」で1回でも動かすと一切使われなくなる（＝腱さんの微調整が終わるまで作れない）。
キャッシュ側の各点は**絶対的な緯度経度**を持っているので、この完全一致は本来不要。
**判定を「格子間隔一致＋今必要な範囲を空間的に含んでいるか」だけにし、今の敷地の座標系へ投影し直して切り出す**作りに変える。

negura 用の新キャッシュ `data/negura_elev_g1.json`（**format 2**・下記）はオーケストレータが生成中（62,595点・約16分）。
**このファイルがまだ無い間は、平井で実装と検証を進め、negura の検証は最後に行う**（ファイルの出現を待ってよい）。

## 着手前5問（kaishu-policy A・回答済み）
1. **同じ知識を持つ場所**: 事前キャッシュの読み込み判定は `generateFlat()` 内の `const ec=SITE.elevCache; if(...){...}` の
   1ブロックだけ（grep 済み）。⚠ **名前の罠**: `fetchOne()` の直前にある `const elevCache=new Map();` は
   API結果のメモ化（別物）。こちらは触らない。
2. **同種の既存機能**: 標高を大量に取る経路は他に `sampleSectionLL()`（断面図）・`generateBand()`（2H影響帯）があるが、
   どちらも `fetchOne()` のライブ取得で事前キャッシュを使っていない。**今回は対象外**（範囲を広げない）。
3. **引っ越しか**: いいえ。
4. **過去の類似改修**: BUGLOG 2026-08-20「D/Eを個別調整するとリロードのたびにキャッシュを使わずライブ取得（約11,430点）」
   ＝腱さん「敷地は確定なんだから保存して毎回計らせないで」。この時に cols/rows 完全一致→**包含判定**へ緩めたが、
   `siteAdj` 完全一致は残した。今回はその残りを外す＝**同じ方向の続き**。
5. **所有モジュール**: 「事前キャッシュの読み込みと切り出し」を `generateFlat()` から**関数1つに切り出す**
   （例 `loadElevCacheGrid(ec, g, cLat, cLon, eMin, eMax, nMin, nMax)` → 成功なら FLAT_GRID と同じ形の
   オブジェクト、使えなければ `null`）。`generateFlat()` はそれを呼んで非nullなら採用するだけにする。

## やること

### 1) キャッシュ判定を siteAdj 非依存に（index.html `generateFlat()`）
- 条件から `siteAdj` と `ec.adj` の完全一致4行を外す。`g===ec.g` は残す。
- 2つの形式を受け付ける:
  - **format 1（平井・既存）** `{g, cLat, cLon, eMin, nMin, cols, rows, cells:[{e,n,lat,lon,elev}]}`
    （row-major、`cells[r*cols+c]`、r が北向き・c が東向き。lat/lon は格子上で線形）
  - **format 2（negura・新規）** `{format:2, g, lat0, lon0, dLat, dLon, cols, rows, elev:[...]}`
    点(r,c) の緯度経度＝`lat0 + r*dLat, lon0 + c*dLon`、標高＝`elev[r*cols+c]`（null可）。r=0 が南端・c=0 が西端。
  - format 1 は `lat0=cells[0].lat, lon0=cells[0].lon, dLat=cells[cols].lat-cells[0].lat, dLon=cells[1].lon-cells[0].lon,
    elev=cells.map(c=>c.elev)` と読み替えれば、以降は同じ処理で済む。
- **今の座標系へ投影**: `mLat=111320, mLon=111320*cos(rad(cLat))`（generateFlat と同じ値）で
  `E0=(lon0-cLon)*mLon, N0=(lat0-cLat)*mLat, gE=dLon*mLon, gN=dLat*mLat`。
- **包含判定**: `E0 <= eMin+EPS && E0+(cols-1)*gE >= eMax-EPS && N0 <= nMin+EPS && N0+(rows-1)*gN >= nMax-EPS`。
  満たさなければ `null`＝従来どおりライブ取得へ。
- **切り出し**: 必要範囲だけ（キャッシュ全体ではなく）を FLAT_GRID にする。
  `c0=floor((eMin-E0)/gE), c1=ceil((eMax-E0)/gE), r0=floor((nMin-N0)/gN), r1=ceil((nMax-N0)/gN)`（0〜cols-1 / rows-1 にクランプ）。
  セルは `e=E0+c*gE, n=N0+r*gN, lat=lat0+r*dLat, lon=lon0+c*dLon, elev, dh=(elev!=null)?elev-flatRef.elev:null` を
  **row-major（r0→r1 の外側ループ、c0→c1 の内側ループ）**で並べる（ライブ取得と同じ並び。消費側は `en0+g` の等間隔格子を
  前提に `cells[r*cols+c]` で読む: `traceMaskOutline`・`marchingSquaresLevel` 等）。
  FLAT_GRID は `{g, cols:c1-c0+1, rows:r1-r0+1, en0:{e:E0+c0*gE, n:N0+r0*gN}, cLat, cLon, cells}`。
  （gE は g と 1e-7 程度しか違わないので、FLAT_GRID.g は `g` のままでよい。）
- 表示文言は従来どおり `キャッシュ済み標高データを使用（API取得なし）：ok/total 点`。
- 既存の古いコメント（「siteAdjがキャッシュ生成時と一致する場合だけ」「回帰リスクゼロを最優先」等）は**実態に合わせて書き換える**
  （コメントと実装が食い違うと次のセッションが逆走する）。

### 2) SITES の変更
- `SITES.negura` に `elevCache:{url:'data/negura_elev_g1.json', g:1}` を追加（`adj` は不要）。
- `SITES.hirai.elevCache.adj` は判定に使わなくなる。消さずに残し、コメントで「生成時の配置の記録（判定には使わない）」と明記。
- `SITES.negura` の冒頭コメントの「⚠ 未解消の食い違い」「地積測量図が手に入ったら再検討」の段落を次の趣旨に書き換える:
  「面積メモは登記簿（公簿）の地積と確認済み（2026-10-08 腱さん）。航空写真から測った地面の実寸 15,582㎡ との差（公簿が1.35倍）は
  山林によくある公簿と実測の差として了承済み。倍率1.0＝公簿。航空写真に合わせて倍率を下げると表示面積も実測寄りに変わる。」
  （数値・根拠の記述は残してよい。「未解消」「再検討」という言葉だけ外す。）

### 3) .gitignore
`!data/negura_elev_g1.json` を `!data/negura_kouzu.png` の次に追加。

### 4) 検証用スクリプト（コミットする）
`tools/check_flat_cache.py` を新設（冒頭に `@owns 平坦度の事前キャッシュの実機回帰確認` の1行）。
**ヘッドレスPlaywright**で `http://localhost:<port>/index.html` を開き、`page.evaluate` で次を行い結果をJSONで出す:
物件を切替 → 基準点を置く（`setFlatRef` 相当。API1回でよい）→ 必要なら `siteAdj` を書き換えて `drawSite()` →
`generateFlat()` を await → `#flatProg` の文言・`FLAT_GRID.rows/cols/cells.length`・`en0` を返す。
dialog は自動で dismiss される前提（＝ライブ取得の確認ダイアログが出たら「粗くする」側に倒れ、キャッシュ不使用が分かる）。
サーバーは `python -m http.server <空きポート>` をスクリプト内でサブプロセス起動し、終了時に必ず kill する。
**Browser pane（preview_start / mcp__Claude_Browser__*）は使わない**（フックで止められる）。
腱さんのChromeにタブを出さない（headless 既定）。参考: `C:\Claude\101_KaihatsuHyoujun\shiken\tools\browser_check.py` の起動条件。

## 受入条件（tools/check_flat_cache.py の実測で示す）
1. **平井・既定配置**: キャッシュ使用（文言に「キャッシュ済み」）。セル数は従来のライブ相当の範囲（切り出し後）。
2. **平井・敷地を東へ5m動かした配置**: **キャッシュ使用**（従来はここでライブ取得になっていた＝今回の改善点）。
3. **平井・敷地を東へ300m動かした配置**: キャッシュ**不使用**（範囲外→ライブ取得へ落ちる）。
4. **値の正しさ**: 平井で切り出したセルのうち任意5点の lat/lon をライブAPIで取り直し、標高が一致（±0.1m）。
5. **negura・既定配置／北へ10m＋倍率0.86の配置**: どちらもキャッシュ使用、キャッシュ不使用の確認ダイアログが出ない。
   任意5点をライブAPIと突き合わせて一致（±0.1m）。（`data/negura_elev_g1.json` が出来てから実施）
6. 平坦度の結果（`#flatResult` の文言）が出ること・コンソールエラー0件（ネットワーク由来の ERR_NAME_NOT_RESOLVED は除外してよいが件数は報告）。
7. 他物件（hannan/camp/furuya/mikokai）は elevCache を持たないので従来どおり（コード経路上の確認で可）。

## 報告に含めるもの
- `カイシュウ5問:済`、変更分類 **B**（キャッシュ判定の仕様変更）。DESIGN.md はオーケストレータが同期するので触らない。
- ヨコテン表（キャッシュ判定の箇所が `generateFlat()` の1箇所だけであることの確認結果）。
- 受入条件1〜7の実測値（スクリプト出力をそのまま）。
- コミットは意味のある単位で（worktree のブランチ `worktree-kadai-635-elevcache` に。**本体 main へのマージ・push はしない**＝オーケストレータがやる）。
  メッセージ末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
- 作業単位ごとにコミット＋ docs/WORKLOG.md へ1行追記（中断されても失われないように）。
- `spawn_task` は使わない。気づいた別件は報告に書いてオーケストレータへ。
