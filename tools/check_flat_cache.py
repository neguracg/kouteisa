# -*- coding: utf-8 -*-
"""
@owns 平坦度の事前キャッシュの実機回帰確認

index.html の generateFlat() が標高の事前キャッシュ（SITE.elevCache）を「敷地を動かしても」使えるか、
範囲外へ動かした時だけライブ取得へ落ちるか、切り出した値がライブAPIと一致するかを、
**ヘッドレスPlaywright**（実Chrome・タブは出ない）で実機確認する。課題#635（2026-10-08）で新設。

仕組み:
  * `python -m http.server` をこのスクリプトが空きポートで起動し、終了時に必ず止める。
  * ケースごとに新しいブラウザコンテキスト（localStorageは空）で index.html を開き、page.evaluate で
      switchSite(物件) → setFlatRef(敷地の中心。標高APIを実際に1回呼ぶ) → siteAdj を書き換えて drawSite()
      → await generateFlat() → #flatProg の文言・FLAT_GRID の rows/cols/cells.length/en0 などを返す。
  * 「キャッシュを使ったか」は文言だけでなく3つの独立した事実で見る:
      ①標高APIへのリクエスト数（generateFlat中。キャッシュ使用なら0）②確認ダイアログの有無
      （ライブ取得に落ちると3000点超でconfirmが出る。dialogは記録してdismissする＝「粗くする」側）
      ③アプリがconsoleに残す「elevCache: 使用/不使用（理由）」。
    generateFlat中の標高APIはスタブ応答（elevation=20.0固定）で返す＝ライブ取得に落ちるケースでも
    公共APIを叩かない（基準点の1回と、Python側の突き合わせ5点だけが本物のAPI）。
  * 値の正しさ: 切り出したセルから勾配のある5点を選び、Python(urllib)で本物の標高APIを取り直して±0.1m以内で比較。
  * 構造の正しさ: 全セルについて cell.e/n が en0+g の等間隔格子（row-major）に載っていること、
      toLL(e,n)＝cell.lat/lon であること、dh＝elev−基準標高 であることをページ内で検算する。
  * 平井のキャッシュを format 2 に読み替えた合成ファイルでも走らせ、format 1 と同じ結果になることを確かめる
      （negura のファイルが出来る前でも format 2 の読み込み経路を検証できる）。

使い方:
  python tools/check_flat_cache.py                       # 全ケース（negura は data/negura_elev_g1.json が完成していれば）
  python tools/check_flat_cache.py --cases hirai-default,hirai-east5
  python tools/check_flat_cache.py --wait-negura 1800    # negura のファイルが出来るまで最大1800秒待つ
  python tools/check_flat_cache.py --shots DIR           # 各ケースの地図スクショを DIR に保存
出力: stdout に結果JSON1個（ensure_ascii=False）。人間向けの合否表は stderr。
終了コード: 0=全ケース合格 / 1=不合格あり / 2=起動・通信エラー / 3=不合格は無いが未実施ケースあり（negura未完成など）
"""
import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]          # = リポジトリ（worktree）直下。ここを http.server の公開ルートにする
NEGURA_CACHE = ROOT / "data" / "negura_elev_g1.json"
HIRAI_CACHE = ROOT / "data" / "hirai_elev_g1.json"


def set_root(path):
    """検証対象のルートを差し替える（--root。改修前のindex.htmlを置いたフォルダとの前後比較用）。"""
    global ROOT, NEGURA_CACHE, HIRAI_CACHE
    ROOT = Path(path).resolve()
    NEGURA_CACHE = ROOT / "data" / "negura_elev_g1.json"
    HIRAI_CACHE = ROOT / "data" / "hirai_elev_g1.json"

API_TMPL = ("https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php"
            "?lon={lon}&lat={lat}&outtype=JSON")                 # index.html の apiUrl() と同じ形
STUB_BODY = '{"elevation":20.0,"hsrc":"stub"}'
CACHE_USED_TEXT = "キャッシュ済み標高データを使用（API取得なし）"   # generateFlat() の #flatProg 文言
TOL_M = 0.1                                                      # ライブAPIとの許容差（受入条件4・5）

# --- ケース定義 -----------------------------------------------------------------------------------
# expect: 'cache'=キャッシュを使う／'live'=キャッシュ範囲外でライブ取得へ落ちる／'nocfg'=elevCache を持たない物件で従来どおりライブ取得
#         ／None=合否を付けない（参考）。warm=True は「同じページで先に既定配置のまま1回計算してから、動かして再計算する」
#         ＝実際の操作順（計算→「敷地を調整」→もう一度計算）。測るのは2回目の計算。
CASES = {
    "hirai-default":      dict(site="hirai", dx=0, dy=0, scale=None, expect="cache", acc="1"),
    "hirai-east5":        dict(site="hirai", dx=5, dy=0, scale=None, expect="cache", acc="2"),
    "hirai-east300":      dict(site="hirai", dx=300, dy=0, scale=None, expect="live", acc="3"),
    "hirai-west5":        dict(site="hirai", dx=-5, dy=0, scale=None, expect=None, acc="参考"),   # 平井のキャッシュは西・南に余裕が無い（参考）
    "hirai-east5-after-calc": dict(site="hirai", dx=5, dy=0, scale=None, expect="cache", acc="2", warm=True),
    "hirai-f2-synthetic": dict(site="hirai", dx=0, dy=0, scale=None, expect="cache", acc="format2経路",
                               synthetic_format2=True),
    "negura-default":     dict(site="negura", dx=0, dy=0, scale=None, expect="cache", acc="5"),
    "negura-n10-s086":    dict(site="negura", dx=0, dy=10, scale=0.86, expect="cache", acc="5"),
    "negura-n10-s086-after-calc": dict(site="negura", dx=0, dy=10, scale=0.86, expect="cache", acc="5", warm=True),
    "hannan-nocache":     dict(site="hannan", dx=0, dy=0, scale=None, expect="nocfg", acc="7"),
    "camp-nocache":       dict(site="camp", dx=0, dy=0, scale=None, expect="nocfg", acc="7"),
    "furuya-nocache":     dict(site="furuya", dx=0, dy=0, scale=None, expect="nocfg", acc="7"),
    "mikokai-nocache":    dict(site="mikokai", dx=0, dy=0, scale=None, expect="nocfg", acc="7"),
}
NEGURA_CASES = tuple(n for n, s in CASES.items() if s["site"] == "negura")

# --- ページ内で動かすJS ----------------------------------------------------------------------------
JS_PLACE_REF = r"""async () => {
  await setFlatRef({lat: siteAdj.lat, lng: siteAdj.lon});      // 基準点（敷地の中心）。標高APIを本当に呼ぶ
  return flatRef ? {lat: flatRef.lat, lon: flatRef.lon, elev: flatRef.elev, hsrc: flatRef.hsrc} : null;
}"""

JS_MOVE_SITE = r"""(a) => {
  siteAdj.lon += a.dx / (111320 * Math.cos(rad(siteAdj.lat)));   // 東へdx[m]
  siteAdj.lat += a.dy / 111320;                                   // 北へdy[m]
  if (a.scale != null) siteAdj.scale = a.scale;
  saveSiteAdj(); drawSite();
  return {lat: siteAdj.lat, lon: siteAdj.lon, rot: siteAdj.rot, scale: siteAdj.scale};
}"""

JS_START_GENERATE = r"""() => {
  window.__gf = {done: false, err: null, ms: null};
  const t0 = performance.now();
  generateFlat().then(() => { window.__gf.done = true; window.__gf.ms = performance.now() - t0; })
                .catch(e => { window.__gf.done = true; window.__gf.err = String((e && e.stack) || e); });
}"""

JS_COLLECT = r"""() => {
  const out = {};
  const txt = id => { const el = document.getElementById(id); return el ? el.textContent : null; };
  out.prog = txt('flatProg');
  const fr = document.getElementById('flatResult');
  out.flatResult = fr ? {display: fr.style.display, text: fr.textContent.trim()} : null;
  out.siteAdj = {lat: siteAdj.lat, lon: siteAdj.lon, rot: siteAdj.rot, scale: siteAdj.scale};
  out.hasElevCache = !!SITE.elevCache;
  out.gf = window.__gf;
  // --- オラクル：generateFlat() と同じ式で「ライブ取得ならこの格子になる」範囲を独立に求める ---
  const g0 = Math.max(0.5, parseFloat(document.getElementById('fGrid').value) || 1);
  const cLat = siteLatLngs.reduce((s, p) => s + p.lat, 0) / siteLatLngs.length;
  const cLon = siteLatLngs.reduce((s, p) => s + p.lon, 0) / siteLatLngs.length;
  const mLat = 111320, mLon = 111320 * Math.cos(rad(cLat));
  const sEN = siteLatLngs.map(p => ({e: (p.lon - cLon) * mLon, n: (p.lat - cLat) * mLat}));
  deSubAreaPolys().forEach(s => s.latlngs.forEach(p => sEN.push({e: (p.lon - cLon) * mLon, n: (p.lat - cLat) * mLat})));
  const margin = 8;
  const eMin = Math.min(...sEN.map(p => p.e)) - margin, eMax = Math.max(...sEN.map(p => p.e)) + margin;
  const nMin = Math.min(...sEN.map(p => p.n)) - margin, nMax = Math.max(...sEN.map(p => p.n)) + margin;
  const liveCols = Math.floor((eMax - eMin) / g0) + 1, liveRows = Math.floor((nMax - nMin) / g0) + 1;
  out.needed = {g: g0, eMin, eMax, nMin, nMax, liveCols, liveRows, liveN: liveCols * liveRows};
  const G = FLAT_GRID;
  if (!G) { out.grid = null; return out; }
  const cells = G.cells;
  const grid = {g: G.g, cols: G.cols, rows: G.rows, n: cells.length, en0: G.en0, cLat: G.cLat, cLon: G.cLon};
  grid.okCnt = cells.filter(c => c.elev != null).length;
  out.coversNeeded = G.en0.e <= eMin + 0.02 && G.en0.e + (G.cols - 1) * G.g >= eMax - 0.02 &&
                     G.en0.n <= nMin + 0.02 && G.en0.n + (G.rows - 1) * G.g >= nMax - 0.02;
  // --- 構造の検算（全セル）---
  const mLatG = 111320, mLonG = 111320 * Math.cos(rad(G.cLat));
  let latticeErr = 0, llErr = 0, dhBad = 0, h = 2166136261 >>> 0;
  for (let r = 0; r < G.rows; r++) {
    for (let c = 0; c < G.cols; c++) {
      const cell = cells[r * G.cols + c];
      latticeErr = Math.max(latticeErr, Math.abs(cell.e - (G.en0.e + c * G.g)), Math.abs(cell.n - (G.en0.n + r * G.g)));
      llErr = Math.max(llErr, Math.abs(G.cLon + cell.e / mLonG - cell.lon) * mLonG, Math.abs(G.cLat + cell.n / mLatG - cell.lat) * mLatG);
      const dhExp = (cell.elev != null) ? (cell.elev - flatRef.elev) : null;
      if ((dhExp == null) !== (cell.dh == null) || (dhExp != null && Math.abs(dhExp - cell.dh) > 1e-9)) dhBad++;
      const v = (cell.elev == null) ? -99999 : Math.round(cell.elev * 10);
      h ^= (v & 0xffffffff); h = Math.imul(h, 16777619) >>> 0;
    }
  }
  grid.latticeErrM = latticeErr; grid.llErrM = llErr; grid.dhBad = dhBad; grid.elevHash = h;
  out.grid = grid;
  // --- 突き合わせ用の5点：勾配のあるセル（隣との標高差>=0.3m）から均等に。足りなければ均等に ---
  const cand = [];
  for (let r = 1; r < G.rows - 1; r++) for (let c = 1; c < G.cols - 1; c++) {
    const i = r * G.cols + c, v = cells[i].elev;
    if (v == null) continue;
    const nb = [cells[i - 1].elev, cells[i + 1].elev, cells[i - G.cols].elev, cells[i + G.cols].elev];
    if (nb.some(x => x == null)) continue;
    if (Math.max(...nb.map(x => Math.abs(x - v))) >= 0.3) cand.push(i);
  }
  let pool = cand, pooled = 'gradient';
  if (pool.length < 5) { pool = []; for (let i = 0; i < cells.length; i++) if (cells[i].elev != null) pool.push(i); pooled = 'any'; }
  out.samplePool = {kind: pooled, size: pool.length};
  out.samples = [];
  for (let k = 0; k < 5 && pool.length; k++) {
    const i = pool[Math.min(pool.length - 1, Math.floor((k + 0.5) * pool.length / 5))];
    const cell = cells[i];
    out.samples.push({r: Math.floor(i / G.cols), c: i % G.cols, lat: cell.lat, lon: cell.lon, elev: cell.elev});
  }
  return out;
}"""

JS_FIT_MAP = r"""() => {
  map.fitBounds(L.latLngBounds(siteLatLngs.map(p => [p.lat, p.lon])), {animate: false, padding: [40, 40]});
}"""


# --- ユーティリティ ---------------------------------------------------------------------------------
def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_server():
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d" % port
    deadline = time.time() + 20
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("http.server が起動直後に終了した（ポート%d）" % port)
        try:
            urllib.request.urlopen(base + "/index.html", timeout=2).read(1)
            return proc, base
        except Exception:
            time.sleep(0.2)
    stop_server(proc)
    raise RuntimeError("http.server が応答しない（ポート%d）" % port)


def stop_server(proc):
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
        proc.wait(timeout=5)


def live_elev(lat, lon):
    """本物の標高APIを1点取り直す（ブラウザを通さない＝ページ側のカウンタを汚さない）。取得不能・欠測は None。"""
    url = API_TMPL.format(lat=repr(float(lat)), lon=repr(float(lon)))
    last = None
    for i in range(3):
        try:
            j = json.loads(urllib.request.urlopen(url, timeout=20).read())
            v = j.get("elevation")
            return None if v in (None, "-----") else float(v)
        except Exception as e:     # noqa: BLE001  通信系の一時エラーは再試行
            last = e
            time.sleep(1.0 * (i + 1))
    raise RuntimeError("標高APIが取れない: %s" % last)


def negura_cache_ready():
    """negura のキャッシュが「完成している」か。(ok, 理由)。生成途中（.partial.json が残っている）は未完成扱い。"""
    part = Path(str(NEGURA_CACHE) + ".partial.json")
    if not NEGURA_CACHE.exists():
        return False, "data/negura_elev_g1.json がまだ無い"
    if part.exists():
        return False, "生成途中（.partial.json が残っている）"
    try:
        j = json.loads(NEGURA_CACHE.read_text(encoding="utf-8"))
    except Exception as e:     # noqa: BLE001
        return False, "JSONとして読めない（書き込み中？）: %s" % e
    if j.get("format") != 2:
        return False, "format が 2 ではない: %r" % j.get("format")
    if len(j.get("elev", [])) != j["cols"] * j["rows"]:
        return False, "elev の長さ %d ≠ cols*rows %d" % (len(j.get("elev", [])), j["cols"] * j["rows"])
    return True, "format 2・%dx%d=%d点・欠測%s" % (j["cols"], j["rows"], j["cols"] * j["rows"], j.get("missing"))


def hirai_as_format2():
    """平井の format 1 を format 2 の本文に変換する（読み込み側の format 2 経路を平井で検証するための合成ファイル）。"""
    j = json.loads(HIRAI_CACHE.read_text(encoding="utf-8"))
    cols, rows, c = j["cols"], j["rows"], j["cells"]
    return json.dumps({
        "format": 2, "site": "hirai-synthetic", "g": j["g"],
        "lat0": c[0]["lat"], "lon0": c[0]["lon"],
        "dLat": c[cols]["lat"] - c[0]["lat"], "dLon": c[1]["lon"] - c[0]["lon"],
        "cols": cols, "rows": rows, "elev": [x["elev"] for x in c],
    }, separators=(",", ":"))


# --- 1ケースを実機で走らせる --------------------------------------------------------------------------
def run_case(browser, base, name, spec, args):
    rec = {"phase": "load", "api": {"load": 0, "ref": 0, "generate": 0}, "dialogs": [], "console_errors": [],
           "ignored_network_errors": 0, "page_errors": [], "failed_requests": [], "elev_msgs": [],
           "cache_file_hits": 0}
    ctx = browser.new_context(viewport={"width": 1400, "height": 900}, device_scale_factor=1,
                              locale="ja-JP", timezone_id="Asia/Tokyo")
    try:
        page = ctx.new_page()
        page.set_default_timeout(60000)
        page.set_default_navigation_timeout(60000)

        def on_dialog(d):
            rec["dialogs"].append({"type": d.type, "message": d.message[:160], "phase": rec["phase"]})
            d.dismiss()                           # 指示書どおり dismiss（confirm なら「粗くする」側＝false）

        def on_console(m):
            t = m.text
            if m.type == "error":
                if "ERR_NAME_NOT_RESOLVED" in t:
                    rec["ignored_network_errors"] += 1          # 指示書: 件数は報告するが合否には含めない
                else:
                    rec["console_errors"].append(t[:300])
            elif "elevCache:" in t:
                rec["elev_msgs"].append({"type": m.type, "text": t[:400], "phase": rec["phase"]})

        def on_request(r):
            if "_elev_g1.json" in r.url:
                rec["cache_file_hits"] += 1

        def on_api(route):
            if rec["phase"] == "generate":              # generateFlat 中はスタブ（公共APIを叩かない・件数だけ数える）
                rec["api"]["generate"] += 1
                route.fulfill(status=200, content_type="application/json",
                              headers={"access-control-allow-origin": "*"}, body=STUB_BODY)
            else:                                       # 基準点の標高は本物
                rec["api"][rec["phase"] if rec["phase"] in rec["api"] else "load"] += 1
                route.continue_()

        page.on("dialog", on_dialog)
        page.on("console", on_console)
        page.on("pageerror", lambda e: rec["page_errors"].append(str(e)[:300]))
        page.on("requestfailed", lambda r: rec["failed_requests"].append({"url": r.url[:120], "failure": r.failure}))
        page.on("request", on_request)
        page.route("**/getelevation.php*", on_api)
        if spec.get("synthetic_format2"):
            body = hirai_as_format2()
            page.route("**/data/hirai_elev_g1.json",
                       lambda route: route.fulfill(status=200, content_type="application/json", body=body))

        page.goto(base + "/index.html", wait_until="load")
        page.wait_for_function("typeof switchSite==='function' && typeof generateFlat==='function'")
        page.evaluate("(id) => switchSite(id)", spec["site"])
        page.evaluate("() => setTool('flat')")        # 実際の操作と同じく「平坦度」タブで計算する（セル塗りが地図に載る＝描画の重さも含めて測る）
        rec["phase"] = "ref"
        ref = page.evaluate(JS_PLACE_REF)
        if not ref or ref.get("elev") is None:
            raise RuntimeError("基準点の標高が取れなかった（標高APIが応答しない？）: %r" % (ref,))
        if spec.get("warm"):
            # 実際の操作順：既定配置のまま1回計算 → 敷地を動かす → もう一度計算。1回目は測らない（カウンタを捨てる）
            rec["phase"] = "generate"
            page.evaluate(JS_START_GENERATE)
            page.wait_for_function("window.__gf && window.__gf.done === true", timeout=args.gen_timeout * 1000)
            rec["warm_prog"] = page.evaluate("() => document.getElementById('flatProg').textContent")
            rec["api"]["generate"] = 0
            rec["dialogs"], rec["elev_msgs"], rec["cache_file_hits"] = [], [], 0
        moved = page.evaluate(JS_MOVE_SITE, {"dx": spec["dx"], "dy": spec["dy"], "scale": spec["scale"]})
        rec["phase"] = "generate"
        page.evaluate(JS_START_GENERATE)
        page.wait_for_function("window.__gf && window.__gf.done === true", timeout=args.gen_timeout * 1000)
        rec["phase"] = "after"
        res = page.evaluate(JS_COLLECT)
        res["ref"] = ref
        res["moved_to"] = moved
        if args.shots:
            Path(args.shots).mkdir(parents=True, exist_ok=True)
            page.evaluate(JS_FIT_MAP)
            page.wait_for_timeout(2500)
            shot = Path(args.shots) / ("%s.png" % name)
            page.screenshot(path=str(shot))
            res["shot"] = str(shot)
        # 本物の標高APIとの突き合わせ（受入条件4・5）。ブラウザの外（Python）で取る
        if args.api_check and res.get("samples") and spec["expect"] == "cache":
            for s in res["samples"]:
                s["live"] = live_elev(s["lat"], s["lon"])
                s["diff"] = None if (s["live"] is None or s["elev"] is None) else round(abs(s["live"] - s["elev"]), 4)
        res["rec"] = rec
        return res
    finally:
        ctx.close()


# --- 合否判定 ---------------------------------------------------------------------------------------------
def judge(name, spec, res, args):
    """(checks, summary)。check = {acc, item, ok, detail}。"""
    rec = res["rec"]
    checks = []

    def add(acc, item, ok, detail=""):
        checks.append({"acc": acc, "item": item, "ok": bool(ok), "detail": detail})

    g = res.get("grid")
    prog = res.get("prog") or ""
    confirms = [d for d in rec["dialogs"] if d["type"] == "confirm"]
    alerts = [d for d in rec["dialogs"] if d["type"] != "confirm"]
    msgs = [m["text"] for m in rec["elev_msgs"]]
    gen_err = (res.get("gf") or {}).get("err")

    add("6", "generateFlat() が例外なく完了", gen_err is None and g is not None, gen_err or ("grid無し" if g is None else ""))
    fr = res.get("flatResult") or {}
    add("6", "#flatResult に結果の文言が出る", fr.get("display") != "none" and len(fr.get("text") or "") > 20,
        "display=%r len=%d: %s" % (fr.get("display"), len(fr.get("text") or ""), (fr.get("text") or "")[:80]))
    add("6", "コンソールエラー0件（ERR_NAME_NOT_RESOLVED除く）・pageerror0件",
        not rec["console_errors"] and not rec["page_errors"],
        "console=%s pageerror=%s／除外したERR_NAME_NOT_RESOLVED=%d件" % (
            rec["console_errors"][:3], rec["page_errors"][:3], rec["ignored_network_errors"]))
    add("構造", "alert()が出ていない", not alerts, str(alerts[:2]))
    if g:
        add("構造", "全セルが en0+g の等間隔格子（row-major）に載る", g["latticeErrM"] < 0.02,
            "最大ずれ %.5f m" % g["latticeErrM"])
        add("構造", "toLL(e,n) = cell.lat/lon（描画位置と標高点の位置が一致）", g["llErrM"] < 1e-3,
            "最大ずれ %.2e m" % g["llErrM"])
        add("構造", "dh = elev − 基準標高（全セル）", g["dhBad"] == 0, "不一致 %d 点" % g["dhBad"])
        add("構造", "cells.length = cols×rows", g["n"] == g["cols"] * g["rows"], "%d = %dx%d" % (g["n"], g["cols"], g["rows"]))

    if spec["expect"] == "cache" and g:
        used_text = prog.startswith(CACHE_USED_TEXT)
        acc = spec["acc"]
        add(acc, "文言が「キャッシュ済み標高データを使用（API取得なし）」", used_text, prog)
        add(acc, "generateFlat中の標高APIリクエスト0件", rec["api"]["generate"] == 0, "%d件" % rec["api"]["generate"])
        add(acc, "確認ダイアログ（3000点超のconfirm）が出ない", not confirms, str(confirms[:1]))
        add(acc, "キャッシュファイルを取得した", rec["cache_file_hits"] >= 1, "%d回" % rec["cache_file_hits"])
        add(acc, "consoleに「elevCache: 使用」", any("elevCache: 使用" in m for m in msgs), "; ".join(msgs)[:200])
        nd = res["needed"]
        # 切り出しは floor/ceil で必要範囲を「覆う」ので、ライブ取得の格子（floor(幅/g)+1）より各方向で
        # 最大 +2 行/列（キャッシュ格子が今の必要範囲の端と揃っていない分、両端に最大1つずつ）大きくなりうる。
        add(acc, "切り出し範囲がライブ取得相当（行・列とも live〜live+2。キャッシュ全体ではない）",
            nd["liveCols"] <= g["cols"] <= nd["liveCols"] + 2 and nd["liveRows"] <= g["rows"] <= nd["liveRows"] + 2,
            "切り出し %dx%d=%d点／ライブ相当 %dx%d=%d点" % (g["cols"], g["rows"], g["n"], nd["liveCols"], nd["liveRows"], nd["liveN"]))
        add(acc, "切り出しが必要範囲を覆っている", res.get("coversNeeded") is True, "")
        if args.api_check:
            sm = res.get("samples") or []
            ok = len(sm) == 5 and all(
                (s["live"] is None and s["elev"] is None) or (s["diff"] is not None and s["diff"] <= TOL_M + 1e-6) for s in sm)
            add("4" if spec["site"] == "hirai" else "5", "任意5点がライブAPIと一致（±%.1fm）" % TOL_M, ok,
                "; ".join("(r%d,c%d) cache=%s live=%s" % (s["r"], s["c"], s["elev"], s.get("live")) for s in sm))
    elif spec["expect"] == "live" and g:
        acc = spec["acc"]
        add(acc, "文言が「キャッシュ済み」ではない（キャッシュ不使用）", not prog.startswith("キャッシュ済み"), prog)
        add(acc, "ライブ取得に落ちた（generateFlat中の標高APIリクエストあり）", rec["api"]["generate"] > 0, "%d件" % rec["api"]["generate"])
        add(acc, "確認ダイアログが出た（3000点超）", len(confirms) >= 1, str(confirms[:1]))
        add(acc, "不使用の理由が「範囲外」（取得失敗などではない）", any("範囲外" in m for m in msgs), "; ".join(msgs)[:300])
    elif spec["expect"] == "nocfg" and g:
        acc = spec["acc"]
        add(acc, "この物件は SITES に elevCache を持たない", res.get("hasElevCache") is False, "hasElevCache=%r" % res.get("hasElevCache"))
        add(acc, "文言が「キャッシュ済み」ではない（従来どおりライブ取得）", not prog.startswith("キャッシュ済み"), prog)
        add(acc, "ライブ取得（generateFlat中の標高APIリクエストあり）", rec["api"]["generate"] > 0, "%d件" % rec["api"]["generate"])
        add(acc, "キャッシュファイルを取りに行っていない・consoleに elevCache の記録が無い",
            rec["cache_file_hits"] == 0 and not msgs, "cache_file_hits=%d msgs=%s" % (rec["cache_file_hits"], msgs))
    return checks


def main():
    ap = argparse.ArgumentParser(description="平坦度の事前キャッシュの実機回帰確認（ヘッドレスPlaywright）")
    ap.add_argument("--cases", default="all", help="カンマ区切り。既定 all。選択肢: " + ",".join(CASES))
    ap.add_argument("--shots", help="各ケースの地図スクショの保存先ディレクトリ")
    ap.add_argument("--no-api-check", dest="api_check", action="store_false", help="本物の標高APIとの突き合わせをしない")
    ap.add_argument("--wait-negura", type=int, default=0, metavar="SEC", help="negura のキャッシュが完成するまで最大SEC秒待つ")
    ap.add_argument("--gen-timeout", type=int, default=300, help="generateFlat 1回の待ち上限[秒]（既定300）")
    ap.add_argument("--bundled", action="store_true", help="channel=chrome ではなくバンドルChromiumを使う")
    ap.add_argument("--root", help="検証対象のルート（index.html と data/ を置いたフォルダ）。既定=このリポジトリ。改修前との前後比較用")
    args = ap.parse_args()
    if args.root:
        set_root(args.root)

    names = list(CASES) if args.cases == "all" else [c.strip() for c in args.cases.split(",") if c.strip()]
    unknown = [n for n in names if n not in CASES]
    if unknown:
        print("未知のケース: %s（選択肢: %s）" % (unknown, list(CASES)), file=sys.stderr)
        return 2

    out = {"ok": False, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cases": {}, "skipped": {}, "errors": [],
           "acceptance": {}, "browser": None}
    skipped = {}
    if any(n in NEGURA_CASES for n in names):
        deadline = time.time() + args.wait_negura
        while True:
            ready, why = negura_cache_ready()
            if ready or time.time() >= deadline:
                break
            print("[待機] negura のキャッシュ未完成: %s" % why, file=sys.stderr, flush=True)
            time.sleep(15)
        out["negura_cache"] = why
        if not ready:
            for n in NEGURA_CASES:
                if n in names:
                    skipped[n] = "negura のキャッシュが未完成: %s" % why
            names = [n for n in names if n not in NEGURA_CASES]
    out["skipped"] = skipped

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        out["errors"].append("playwright が未導入です（pip install playwright && python -m playwright install chrome）")
        json.dump(out, sys.stdout, ensure_ascii=False)
        return 2

    server = None
    t_start = time.time()
    try:
        server, base = start_server()
        out["base"] = base
        with sync_playwright() as pw:
            kw = {"headless": True}
            if not args.bundled:
                kw["channel"] = "chrome"
            try:
                browser = pw.chromium.launch(**kw)
            except Exception as e:     # noqa: BLE001  黙ってバンドル版へは落とさない（browser_check.py と同じ方針）
                out["errors"].append("ブラウザ起動失敗(%s): %s  --bundled で再実行できます" % (kw, e))
                json.dump(out, sys.stdout, ensure_ascii=False)
                return 2
            out["browser"] = {"version": browser.version, "channel": kw.get("channel", "bundled"), "headless": True}
            try:
                for n in names:
                    t0 = time.time()
                    try:
                        res = run_case(browser, base, n, CASES[n], args)
                        res["checks"] = judge(n, CASES[n], res, args)
                        res["case_ok"] = all(c["ok"] for c in res["checks"])
                    except Exception as e:     # noqa: BLE001
                        res = {"case_ok": False, "error": "%s: %s" % (type(e).__name__, e), "checks": []}
                    res["seconds"] = round(time.time() - t0, 1)
                    res.setdefault("spec", {k: v for k, v in CASES[n].items()})
                    out["cases"][n] = res
                    print("[%s] %s  (%.1fs)" % ("PASS" if res["case_ok"] else "FAIL", n, res["seconds"]),
                          file=sys.stderr, flush=True)
            finally:
                browser.close()
    except Exception as e:     # noqa: BLE001
        out["errors"].append("%s: %s" % (type(e).__name__, e))
        json.dump(out, sys.stdout, ensure_ascii=False)
        return 2
    finally:
        stop_server(server)

    # --- ケース間の比較: format 2（合成）は format 1 と同じ格子・同じ標高になること ---
    cs = out["cases"]
    if "hirai-f2-synthetic" in cs and "hirai-default" in cs and cs["hirai-f2-synthetic"].get("grid") and cs["hirai-default"].get("grid"):
        a, b = cs["hirai-default"]["grid"], cs["hirai-f2-synthetic"]["grid"]
        same = (a["cols"], a["rows"], a["elevHash"]) == (b["cols"], b["rows"], b["elevHash"]) and \
            abs(a["en0"]["e"] - b["en0"]["e"]) < 1e-6 and abs(a["en0"]["n"] - b["en0"]["n"]) < 1e-6
        cs["hirai-f2-synthetic"]["checks"].append({
            "acc": "format2経路", "item": "format 1 と同じ格子・同じ標高（cols/rows/en0/elevHash）", "ok": same,
            "detail": "f1=%s f2=%s" % ((a["cols"], a["rows"], a["elevHash"]), (b["cols"], b["rows"], b["elevHash"]))})
        cs["hirai-f2-synthetic"]["case_ok"] = all(c["ok"] for c in cs["hirai-f2-synthetic"]["checks"])

    # --- 受入条件ごとの合否 ---
    def acc_ok(acc):
        items = [c for r in cs.values() for c in r.get("checks", []) if c["acc"] == acc]
        return None if not items else all(c["ok"] for c in items)
    for acc in ("1", "2", "3", "4", "5", "6", "7", "format2経路", "構造"):
        v = acc_ok(acc)
        out["acceptance"][acc] = "PASS" if v else ("NOT RUN" if v is None else "FAIL")

    out["seconds"] = round(time.time() - t_start, 1)
    out["ok"] = bool(cs) and all(r.get("case_ok") for r in cs.values()) and not out["errors"]
    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")

    # --- 人間向けの合否表（stderr）---
    for n, r in cs.items():
        print("\n== %s  %s" % (n, "PASS" if r.get("case_ok") else "FAIL"), file=sys.stderr)
        if r.get("error"):
            print("   ERROR %s" % r["error"], file=sys.stderr)
        for c in r.get("checks", []):
            print("   [%s] 受入%s %s  -- %s" % ("ok" if c["ok"] else "NG", c["acc"], c["item"], c["detail"][:160]), file=sys.stderr)
    for n, why in skipped.items():
        print("\n== %s  未実施: %s" % (n, why), file=sys.stderr)
    print("\n受入条件: %s" % out["acceptance"], file=sys.stderr)
    if not out["ok"]:
        return 1
    return 3 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
