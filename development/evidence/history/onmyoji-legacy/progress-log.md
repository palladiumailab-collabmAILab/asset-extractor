# 陰陽師 Android エミュレーター／アセット抽出 作業経過

最新状態: 2026-09-09の追加変換結果は `completion-status.md` を参照。以下には過去時点の経過も含む。
作業場所: `C:\Users\palla\Documents\Onmyoji-APK-Assets`
サブエージェント: 初期作業は未使用。2026-09-09の追加作業はユーザーの明示許可によりSol mediumと分業。

## 目的

2026-09-09追記: 画像155,695件、DDS/PVR34原本、音声672トラック、モデル33,198原本の変換／対応付けを完了。モデル58件は明示的な形状回収。詳細と意味的に未復元の独自データは `completion-status.md` に集約した。完了済みの全件再抽出は不要。

日本語環境の Android 端末としてゲームをインストール・起動できる状態を作り、取得できた APK/OBB/NPK 等を原本を壊さずに Documents 配下へ保存・抽出する。

## 完了したこと

1. 公式 Android Emulator での検証を実施。ARM64 ネイティブライブラリ（`nximgui.dll`）の SIGILL と、追加データ取得時のアプリ内「メモリ不足」を確認した。
2. BlueStacks 5 の Android 11 (Rvc64) に切り替え。日本語ロケール、8 CPU、8 GB RAM、約 126 GB の仮想ディスク、ABIs `x86,x64,arm,arm64` を設定した。
3. BlueStacks の既定 Nougat32 インスタンスを削除し、Rvc64 のみに整理。Android Emulator の AVD/不要な SDK emulator・system-images も削除し、platform-tools 等は保持した。
4. APK (`com.netease.onmyoji.na`, versionName `1.8.13`) を保存し、APK 内を展開・形式別マニフェスト化した。
5. Google アカウント認証後、OBB の取得とゲームデータの更新が進み、タイトル画面まで到達した。
6. 次の原本を保存した。
   - `source\downloaded\obb\main.251120.com.netease.onmyoji.na.obb` — 1,980,549,688 bytes
   - `source\downloaded\obb\patch.251120.com.netease.onmyoji.na.obb` — 1,871,897,703 bytes
   - `source\downloaded\ExtraRes\res.npk` — 2,658,237,644 bytes
   - `source\downloaded\cloudfilesys3` — 169 ファイル、THX/WPK/設定/キャッシュ等
7. OBB 内 14 本の NPK と動画を展開し、独自スクリプトで NXPK のインデックス、XOR、zlib を処理して各エントリを抽出した。`extracted-npk` 以下に NPK 別フォルダと `manifest.csv` を保存した。
8. `ExtraRes\res.npk`（173,294 エントリ）も抽出済み。KTX、JSON、XML、PNG、mesh 等を形式判定して保存した。抽出画像の目視確認も実施済み。
9. 再開用スクリプトを保存した。
   - `extract-nxpk.ps1`
   - `classify-extracted.ps1`
   - `reports\downloaded-assets-notes.md`

## 未完了／制限

- 初期回収では更新NPKに `Permission denied` が発生した。その後 `source/downloaded/updated-npk` に3原本を回収済み。2026-09-09の再検証でAndroid側記録のSHA-256と一致を確認した。
- 回収済み THX/WPK はコンテナのままで、個別アセットへの分解は未実施。
- KTX/PVR/DDS/FSB/mesh は元形式のまま。PNG/WAV/OBJ 等への変換は未実施。
- `bin` の一部は形式未判定。抽出名はインデックス番号＋ハッシュで、元の論理名ではない。
- BlueStacks は抽出のため再起動している可能性がある。今後再開時に必要なら Rvc64 のみ起動し、Chrome 等の既存ユーザーセッションは勝手に終了しない。

## なぜタスク未完了のままトークンを使い切ったか

これは単一の失敗ではなく、長時間の状態付き作業を一つの会話に連続投入したことが主因である。確認できる要因は次のとおり。

- 公式エミュレーターの不具合調査から、BlueStacks の導入・二重インスタンス整理・設定変更・Google ログイン・ゲーム更新・大容量 OBB/NPK の回収・抽出まで、別種類の作業を一つのタスクに積み重ねた。
- 2～3 GB 級の ADB 転送と 17 万件規模の NPK 抽出は、処理自体が長時間で、非同期セッションの状態確認（ポーリング）が多数必要だった。各確認結果やログを会話へ戻したため、コンテキスト／出力トークンを大きく消費した。
- 初期の公式エミュレーター経路、ARM 互換性、ストレージ権限、BlueStacks の Nougat32/Rvc64 併存、誤った MIM オプションなどの試行錯誤が発生し、同じ目的に到達するまでの中間状態が増えた。
- ユーザーからの再開・継続・タイマー指定・画面確認が途中で複数回入り、作業を中断して状態を再構成するコストが発生した。
- 抽出開始時点で耐久的なチェックポイント（原本、完了済み NPK、残課題、再開コマンド）を一つの記録へ先に固定していなかった。そのため、会話のトークンが残っている間に最後まで処理を完結させようとして、長い転送・抽出の完了待ちに依存した。
- トークン消費量の正確な内訳や上限到達の数値 telemetry は、この作業からは取得できない。したがって「何トークンがどの呼び出しで消費されたか」までは断定できず、上記は会話履歴と実行ログから確認できる構造的な原因である。

### 現時点で取得できた使用量スナップショット

2026-09-09 02:45 JST 頃に Codex の使用量を照会したところ、5 時間窓の `codex` 使用率は 100%、7 日窓は 47%、残クレジットは 0 だった。表示された 5 時間窓のリセット予定は 2026-09-09 06:34 JST。これは「上限に到達した」ことの確認であり、過去の各ツール呼び出し別の消費量を示すものではない。

## 次回の再開手順

1. まずこのファイルと `reports\downloaded-assets-notes.md` を読む。
2. `source\downloaded` と `extracted-npk` の存在・サイズ・manifest を検査し、完了済み NPK を再抽出しない。
3. 必要なら BlueStacks Rvc64 を起動し、権限を壊さない読み取り方法（アプリ内エクスポート、ADB バックアップ等）だけを追加検討する。
4. 残る THX/WPK の仕様調査・分解を独立した短い工程として実行し、各工程の終了時にこのログを更新する。
5. 大容量処理は会話で逐次ポーリングせず、ログファイルへ進捗を書き、最後に一度だけ要約する。

## reserve（自動化）に関する記録

以前、`陰陽師 OBB・NPKアセット抽出` という一回限りの Codex automation を 2026-09-09 00:14 JST に suggested-create で登録し、抽出の再開指示を保存した。今回さらに `陰陽師 作業経過ログ・再開チェック` を 2026-09-09 02:50 JST の一回限りの suggested-create として reserve に登録した。今回の記録はこれらの予約から再開した場合にも参照できるよう、上記の絶対パスと残課題を明記している。

## 2026-09-09 12:36 JST の再開作業

- `source\downloaded\cloudfilesys3\zipres\script3.zip` を `extracted-cloud\zipres\script3` に展開（3エントリ、43,081 bytes）。
- 展開された `PC 01 00` エントリを `decrypt-cloudfilesys.ps1` で復号し、`decoded-cloud\zipres\script3-all` に保存。復号後は `ENON + zlib` の形式だったため、zlib第2段階を展開して3ファイル（計110,437 bytes）を保存した。内部はバイナリスクリプト／テーブル形式で、平文スクリプトへの変換は未実施。
- `decoded-wpk-final` の全249件を変更せず、`decoded-wpk-typed` に型付きコピーを作成。KTX1 248件（ASTC RGBA 5x5、icon 247件＋model 1件）とRIFF/FEV 1件を確認し、`manifest.csv/json` と `SUMMARY.txt` を保存した。
- ダウンロード済みのMP4 16件を `assets-by-type\video\downloaded-res` にハードリンクし、原本を保持した。OBB/NPK/res/script/tex の原本6件も `assets-by-type\containers\downloaded` にハードリンクした。

### 現在の抽出状態

- OBB内NPK 14件、追加res.npk、更新NPK群：全エントリ抽出済み（各manifestのErrors=0）。
- NPK抽出物：KTX/PNG/JPG/DDS/PVR/FSB/RIFF/mesh/JSON/XML等を元形式で保存。KTX等のPNG/WAV/OBJ変換は未実施。
- cloudfilesys：THFB表の境界抽出済み、WPKのIDX分割・復号・zstd展開・型付きコピー済み。ASTC画像の可視化にはASTCデコーダが別途必要。
- 訂正：更新後NPKは回収済み。上記時点の「引き続き回収不能」という判断は古い記録を引き継いだ誤り。実ファイル・展開manifest・Android側ハッシュ記録に基づき訂正する。
