# OBB / NPK抽出記録

2026-09-09。サブエージェント未使用。

## 原本と展開先

- source/downloaded/obb: main（1,980,549,688 bytes）とpatch（1,871,897,703 bytes）。両方ZIP展開成功。
- extracted-obb: OBB内のNPK 14本とMP4動画16本など。
- source/downloaded/ExtraRes: 追加res.npk（2,658,237,644 bytes）と付随ファイル。
- source/downloaded/cloudfilesys3: 169ファイル（103,731,161 bytes）。THX、WPK、キャッシュ、インデックスなど。
- source/downloaded/res: 動画など16ファイル。
- extracted-npk: NPKから分離・解凍した素材。各フォルダのmanifest.csvに元コンテナ内の位置、圧縮前後サイズ、処理結果を記録。
- npk-summary.csv / npk-types.csv: NPK別検証結果と形式別集計。

## 方法と検証

NXPKの32-byteインデックスを読み、該当する先頭128-byte XORおよびzlib圧縮を処理。各エントリについて原本内の範囲と展開後サイズを検証。格納されたコードは実行していない。
形式調査の参考: https://github.com/zhouhang95/neox_tools/blob/master/onmyoji_extractor.py
独自に作成したextract-nxpk.ps1とclassify-extracted.ps1を保存。

## 残る制限

初期のADB回収ではPermission deniedだったが、その後の更新NPKは回収済み。2026-09-09の再検証で、source/downloaded/updated-npk内の3原本のSHA-256がandroid-sha256.txtに記録されたAndroid内Documents/res.npk、script.npk、tex.npkのハッシュと完全一致した。extracted-npk/updated-res、updated-script、updated-texも全エントリ展開済み。以前の「回収できなかった」は現在の状態を表していない。

THX表の分離、WPKの分割・復号・展開は実施済み。KTX/PVR/DDSからPNG、FSBからWAV、対応meshからOBJへの変換も進んでいる。最新の件数と制限はcompletion-status.mdおよび各conversion.csvを参照。
binは再分類し、XMLの文字コード変換、内包ZIPの展開、シェーダー・アニメーション・骨格の識別を実施。論理名を復元できないファイルには元インデックス番号とハッシュを保持する。
