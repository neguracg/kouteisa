# WORKLOG（作業ログ）

書式: `- YYYY-MM-DD HH:MM | 完了項目 | 次の予定`
（このプロジェクトでは初回作成。docs/task_20260820_flatpanel_restructure.md 実施分から開始）

- 2026-08-20 | 項目1完了(commit cc1db86)：価格シミュ「使える面積比」基準(A区画のbaseUsable)がFLAT_PLANES.lowの現在値（他区画向けに最適化されたかもしれない標高）に依存していたバグを修正。bestRefForRegion(base.pts, thM)でA区画専用の最良使える面積を都度計算する方式に変更。実機検証：FLAT_PLANES.lowをC区画最大化(22.0m)にした状態で旧ロジックのCの試算価格が1717万円（腱さん報告の1722.7万円とほぼ一致・再現成功）、新ロジックでは1212万円に是正（面積比1138万円との残差はCの使える面積割合がAより高いという地形的事実、判断根拠は報告参照） | 次: 項目2（D/Eの坪数不整合）に着手
- 2026-08-20 | 項目2完了：D/E区画別内訳カードが`tallyCutFill()`（現在アクティブな面のみ）を使っており、areaSelectStateを見る価格シミュの使える面積比行と数字が食い違うバグを修正。新設`tallyRegionSelected(key,ll,trueArea)`にD/Eカードを統一。実機検証：ACTIVE_PLANE='low'・D/Eは'high'のみチェックの状態で、旧実装Dカード9.3坪→価格シミュ23.3坪(不一致)、修正後は両方23.3坪で一致（実際のDOM描画=drawFlat()経由のflatResult innerHTML・priceSimResult innerHTML両方で確認） | 次: 項目3（D/E境界線）に着手
- 2026-08-20 | 項目3完了：`drawCutFillOutlines()`の`inSiteArr`にD/E（`deSubAreaPolys()`）を含めるよう拡張（`drawFlat()`と同じOR判定パターン）。実機検証：C/D境界の実標高(C側18.3-18.4m/D側17.8-17.9m)を基準標高18.1m・しきい値50cmで判定した場合、修正前は連結成分がC/D間を跨がない(0件)のに対し修正後は2件跨ぐことを同一条件の前後比較で確認。函南/camp/furuya/mikokai(D/E無し物件)では`deSubAreaPolys()`が空配列を返し副作用なしも確認 | 次: 項目4（ブロック構造の再編）に着手
