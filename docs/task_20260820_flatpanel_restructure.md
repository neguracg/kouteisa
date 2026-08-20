# 平坦度パネル：計算式修正＋ブロック再編＋改称（2026-08-20）

対象ファイル: `C:\Claude\52_kouteisa\index.html`（単一ファイル、複数箇所にまたがる変更）
前提コミット: `71ec8e6`（このタスクの直前の完成状態。git logで確認）

## 着手前4問（kaishu-policy）の回答（オーケストレータ済み・再走査不要）
1. 同じ知識を持つ場所: `regionUsableAreaSelected()`/`usableAreaAtElev()`/`tallyCutFillAtElev()`/`bestRefForRegion()` が使える面積・累計坪の唯一の計算経路。ここを直せば全表示箇所（区画別内訳カード・敷地全体カード・価格シミュ）に伝播する。
2. 同種の既存機能: `regionCardHTML()`+`cutFillBodyHTML()`（区画別内訳カードの「枠＋タイトル」表現）が、今回ブロック全体に適用したい視覚言語のお手本。
3. 引っ越しではない。仕様の一部修正＋UI再編。
4. 過去の類似改修: 本日のdocs/BUGLOG.md 2026-08-20行（基準区画の使える面積比算出の独立化／敷地全体チェックボックスでの内訳消失／XYラジオの絞り込みバグ）が直接の前例。**この3件と同じ「実機で再現してから直す」を必ず踏襲すること**（腱さん本人の明示指示）。

## 作業単位ごとに commit＋WORKLOG追記を必須とする（このタスクは複数箇所にまたがるため）
1コミット=1項目。各コミット後、`docs/WORKLOG.md`に1行追記。全項目完了まで`git push`はしない（オーケストレータが最終確認してから行う）。

---

## 項目1（最優先・実機再現必須）：価格シミュ「使える面積比」の基準がおかしい

### 症状（腱さん報告、生の言葉）
> Cが1722.7万　違うでしょ　まず単純面積で1138万　Ａとの使える面積比だと　それよりやすくなるでしょＣが　ってのが前段　Ａの値段/使える面積　を基準にするって前提がなくなっちゃったじゃん　当然ＤＥもその前提で計算するんだよ

「使える面積比」の試算は必ず「A区画の価格 ÷ A区画の使える面積」を単価の基準にする、という前提のはずが、C区画の試算価格（使える面積比ベース）が「面積比ベース」の試算価格より**高く**出てしまっている（使える面積は生面積の部分集合なので、通常は面積比より安く出るはずという前提が崩れている）。

### 疑われる根本原因（構造解析済み・実機で確認すること）
`renderPriceSim()`（index.html 1498行付近）の `baseUsable`（1533行）:
```js
const baseUsable=FLAT_PLANES.low ? usableAreaAtElev(baseLL, FLAT_PLANES.low.elev, thM) : 0;
```
A区画の「使える面積」を、**その時たまたまFLAT_PLANES.lowに入っている標高**（＝直近で「低い面」ボタン経由でどの区画向けに最適化されたか任意＝「ABCを最大化」かもしれないし「Cを最大化」かもしれない）で評価している。この標高がA区画自身にとって最適とは限らないため、Aの使える面積が過小に出て単価(`unit2=effPrice/baseUsable`)が異常に高騰し、それが全区画（特にC）の試算価格を押し上げている可能性が高い。

これは「Aの価格／Aの使える面積」という前提そのものが、Aにとって不安定な入力（他区画向けに最適化されたかもしれない共有標高）に依存してしまっている設計上の穴。

### 修正方針
- `bestRefForRegion(base.pts, thM)`（2452行、既存の低い面用ヘルパー。A区画にもそのまま使える）で**Aの自区画専用の最良使える面積**を都度計算し、それを`baseUsable`に使う。FLAT_PLANES.lowの現在値には依存させない（Aは「実売価格の分かっている参照点」であり、購入予定の区画セットの一部ではない＝チェックボックス状態からも独立させた既存方針の延長）。
- 修正後、**実機で**（下記の検証手順で）C区画の「使える面積比」試算価格が「面積比」試算価格以下になることを確認する。もし依然として上回る場合は、それが「Cの使える面積割合がAより高いという地形的事実を反映した正しい結果」なのか「別のバグ」なのかを判定し、判定根拠を報告に書くこと（黙って握らない）。

### 検証手順（実機再現。ヘッドレスbrowserでOK）
1. Claude Browser の preview_start で `file:///C:/Claude/52_kouteisa/index.html` を開く。
2. `document.getElementById('siteSel').value='hirai'; document.getElementById('siteSel').dispatchEvent(new Event('change',{bubbles:true}));`
3. `siteLatLngs`の重心で`moveFlatRef(lat,lon)`→`generateFlat()`（confirm自動応答で粗い格子になるが検証には十分。本番同等で見たい場合は`window.confirm=()=>true;`を先に上書きしてから`generateFlat()`すると1mグリッドで取得される＝時間がかかる点に注意）。
4. 低い面：`document.querySelector('input[name="lowRegion"][value="-1"]').checked=true; optimizeFlatRef();`（敷地全体最大化）などで`FLAT_PLANES.low`を設定。
5. 高い面：`cdeAnchor={lat:null,lon:null,elev:23.4}; optimizePlaneForPurchaseSet('CDE')`のように直接標高を与えて`FLAT_PLANES.high`を設定（または `setCdeAnchorByElev()`系のUI経由）。
6. `areaSelectState`のデフォルト（C=low:true,high:true / D,E=low:false,high:true）のまま`renderPriceSim()`を呼び、`document.getElementById('priceSimResult').innerHTML`をログして、修正前後でCの2つの試算価格の大小関係を比較する。
7. `bestRefForRegion(base.pts, thM)`の`thM`は`(parseFloat(document.getElementById('priceSimThreshold').value)||50)/100`と同じ値を使うこと（価格シミュのしきい値と平坦度計算のしきい値は別物なので混同しない）。

---

## 項目2（実機再現必須）：D/E区画の「使える面積」坪数が、区画別内訳カードの「累計坪」と食い違う

### 症状（腱さん報告）
> まずDEの坪数が上の区画ごとの表の「土工までの累計坪」になってないこの区分面積の上段下段で評価する

価格シミュ表のD/E行の坪数が、`区画別の内訳`カードでD/Eそれぞれに表示される「50cmまでの累計坪」（`cutFillAreaTableHTML()`の2行目=`cum`列、`CUTFILL_BAND_LABELS`の30〜50cmの行）と一致していない、という指摘。

### 確認すべきこと（先に実機で数値を突き合わせる。原因を決め打ちしない）
1. 価格シミュのしきい値セレクト`#priceSimThreshold`が50cm（既定）になっている状態で、D区画の
   - 価格シミュ「使える面積比」行の坪数（`regionUsableAreaSelected('D', deRegionLatLngs('D'), 0.5)`相当）
   - D区画の区画別内訳カード（`tallySelectedAreas()`ではなく、D単体の`tallyCutFillAtElev()`を該当tierで呼んだ結果の「50cmまでの累計坪」）
   を両方コンソールに出して比較する。
2. 一致しない場合、差異の性質を特定する：
   - 単位・正規化係数(`regionAreaScale`)の掛け忘れ／二重掛け
   - `areaSelectState`のチェック状態（D=low:false,high:trueが既定）と、区画別内訳カード側が参照している段（上/下）が食い違っている
   - `usableAreaAtElev()`のしきい値`thM`と`cutFillBandOf()`が使う段階境界（0.30/0.50/1.00m）の対応が違う（`usableAreaAtElev(...,0.5)`は「±50cm以内」＝`cutFillAreaTableHTML`の2行目の累計に相当するはずだが、`cutFillBandOf`の実装を読んで境界の丸め方向（以上/未満）まで一致するか確認）
3. 原因が特定できたら、**区画別内訳カードとD/E行が同じ関数を通るように統一する**（今回の項目1と同じ「同じ知識を2箇所に持たない」原則）。個別に係数を合わせ込む対症療法はしないこと。

---

## 項目3（実機再現）：地図上の30/50/100cm境界線（緑・黒の点線／太線）がD/Eを含んでいない

### 背景
`drawCutFillOutlines()`（index.html 3220行）は`pointInSite()`（ABC敷地のみ）でセルを絞り込んでおり、D/E（隣接2筆）はこの境界線の対象外。腱さんが今回D/EをC区画と隙間なく（flush）調整し直したため、C+D+Eを1つの連続した敷地として境界線を引けるはずだが、今は引けていない。

### 要求
> 30cm50cm両方のエリア＝つかえるえりあを　しめす緑の点線がDとEをふくめた敷地全体で描画できるようにして

### 修正方針
`drawCutFillOutlines()`内の`inSiteArr`を、ABC(`pointInSite`)に加えてD/E（`deSubAreaPolys()`の各`s.latlngs`に対する`pointInLLPoly`）も含めた判定に拡張する：
```js
const des = deSubAreaPolys();  // SITE.subAreaSets.DEが無い物件では空配列のはず（要確認）
const inCombinedArr = cells.map(c => pointInSite(c.lat,c.lon) || des.some(s=>pointInLLPoly(c.lat,c.lon,s.latlngs)));
```
`maskAt(thr)`内で`inSiteArr[i]`を`inCombinedArr[i]`に差し替える。

### 検証手順
1. hirai物件で低い面/高い面どちらかをアクティブにした状態（`ACTIVE_PLANE`と`flatRef`が実際のC+D+E境界にかかる標高になっていること）で`drawCutFillOutlines()`相当の描画を発火させ、地図上（またはLeafletレイヤーのpolygon座標配列を直接検査）でC⇄D、D⇄E間に境界線の切れ目が無く1つながりになっているか確認する。
2. D/Eを持たない物件（函南・camp・furuya・mikokai）で`deSubAreaPolys()`が空配列を返し、この変更が何の副作用も起こさないことを確認する（`SITE.subAreaSets.DE`が存在しない物件でのnullチェックの有無を確認）。

---

## 項目4：ブロック構造の再編（枠・タイトルで「どこまでがそのブロックか」を明示）

### 腱さんの指摘（生の言葉）
> 機能がいつもボタンの羅列すぎる　意味のある固まりで区切って　ブロックの名前を付けて　ブロックがどこまでが分かるようにする
> ・平坦度判定　・区画割案　そして　・面積一覧表（内訳の区画別の内訳が上、敷地全体が一番下で毛色が違う＝高い面・低い面・合計が見えるように）　という並び

### 目標構成（上から順）
1. **平坦度判定**（既存のh2カードのまま。中身は「基準点クリック→計算」の操作系のみに絞る）
2. **区画割案**（新設・独立ブロック。現在`flatComputeBlock`の中に埋もれている`subAreaSelectBlock`＝「区画割案の選択」（ABC/XYトグル）と、`deSplitPanel`（X/Y敷地分割の%調整）をここへ移す。他の主要ブロックと同じ枠線・タイトルスタイルで独立させる。SITE.purchaseSetsが無い物件では非表示のまま＝現状のdisplay:none制御は維持）
3. **面積一覧表**（新設タイトル。現在`#flatResult`に無題で書き出されている内容一式をこの枠でラップする）
   - サブブロック「区画別の内訳」を先に表示（現状のABC/XY区画カード＋D/E区画カードをここに統合。「隣接筆（D/E）」という別見出しに分けず、区画別の内訳の並びに含める）
   - サブブロック「敷地全体」を最後に表示。**毛色を変える**（他のカードと違う背景色/縁取りで「これは合算値」と一目で分かるように）。中身は既存の`tallySelectedAreas()`+`cutFillBodyHTML()`のカード（平ら/軽造成/要造成/超過の内訳と累計坪は維持）に加え、**上の段・下の段それぞれの使える面積単独の数値＋合計**が見えるようにする（現状は`tallySelectedAreas()`で2段を合算してから1本のカテゴリ内訳しか出していないので、「上の段だけ」「下の段だけ」の内訳も並べて出す。3枚のカード：上の段カード／下の段カード／合計カード、または1枚のカードに3列、実装しやすい方でよい。チェックが入っていない段は「未計算」または非表示にする）
   - チェックボックス列（`areaSelectCheckboxesHTML()`）は「パラメータ設定」として、この面積一覧表ブロックの冒頭（区画別の内訳より上）に据え置く
4. **価格シミュレーション**（既存`priceSimPanel`。他ブロックと統一した枠線・タイトルスタイルにする以外、構造変更は不要）

### 制約
- 既存のonclick等が参照しているid（`flatComputeBlock`/`planeSelectBlock`/`subAreaSelectBlock`/`flatResult`/`priceSimPanel`/`deSplitPanel`等）は**リネームしない**。DOMツリー上の親子関係の組み替え・ラッパーdivの追加・CSSスタイルの変更のみで対応すること。id付きの要素をJSから`document.getElementById`している箇所を`Grep`で全部洗い出してから移動すること（横展開の要領）。
- 枠のスタイルは既存の`planeSelectBlock`等が使っている`padding:8px;background:#111c26;border-radius:8px;border:1px solid #2a3542`＋`font-weight:700;color:#e6edf3;font-size:12px`のタイトル行を流用し、新しい見た目を発明しない（統一感優先）。

---

## 項目5：「低い面／高い面」→「下の段／上の段」への改称（UI文言のみ）

### 対象
ユーザーに見える文言のみ改称する。**関数名・変数名（`FLAT_PLANES.low/high`、`planeFocusMode`、`selectPlaneFocus('low')`、`ACTIVE_PLANE`等）はリネーム不要**（内部実装であり、無用な差分を増やさない）。CSV出力のデータセット名（`low_50cm_*`/`high_50cm_*`）も**そのまま**（SitePlanner側への既存の取り決めを壊さない。ヘッダーコメント内の日本語説明文だけ「下の段／上の段」に言い換える）。

改称対象の具体箇所（Grep `低い面|高い面` で全数棚卸ししてから機械的に置換すること）:
- `#planeBtnLow`/`#planeBtnHigh`のボタン文言
- `#planeMaximizeHint`に書き込まれる説明文（`optimizeFlatRef()`/`optimizePlaneForPurchaseSet()`内の`prog.textContent`）
- `#highAnchorControls`まわりの説明文・alert文言（例:「先に「地図で位置を指定」ボタンを押してから、上の段（道路など）の目印になる地点を…」は既に「上の段」表記になっている＝統一の一環として矛盾がないか確認）
- `areaSelectCheckboxesHTML()`のラベル（既に「下の段」「上の段」表記＝ここは先行済み。他の箇所をこれに合わせる）
- `exportSitePlannerCSV()`のヘッダーコメント文中の「低い面」「高い面」という日本語説明（データセット名`low_50cm`/`high_50cm`自体は変更しない）
- HTMLコメント中の説明文言（コード保守用、必須ではないが余裕があれば統一）

---

## 完了条件
- 上記5項目すべて、実機（Claude Browserでの検証）で確認してから完了とする。
- 各項目1コミット、コミットメッセージは日本語で変更内容を要約。
- `docs/BUGLOG.md`に項目1・2・3を新しいバグとして1行ずつ追記（症状/原因/commit/#分類/ヨコテン/グローバル判定を含む、CLAUDE.mdの記録ルールに従う）。項目1は「同じ問題が別の場所（B区画等）にも及んでいないか」のヨコテン確認を行うこと（Cだけでなく全区画の単価が同じ根本原因の影響を受けているはず）。
- 全項目完了後、オーケストレータ（呼び出し元セッション）に実施結果と実機確認の数値を報告すること。pushはオーケストレータが行う。
