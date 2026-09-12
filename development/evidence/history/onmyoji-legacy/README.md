# 陰陽師本格幻想 APK アセット展開

閲覧は `Open-Asset-Gallery.cmd` を実行する。画像・音声・動画の検索に加え、OBJをブラウザー内で回転・ズーム・ワイヤーフレーム表示し、候補テクスチャを貼って確認できる。
最新の完了数と残る制限は `reports/completion-status.md`、変換元との対応は `reports/*conversion.csv` を参照。

対象APK: `com.netease.onmyoji.na` バージョン `1.8.13`（versionCode `251120`）

SHA-256: `85954173A1D79D476FF8A2DA28CFBFA07F2B95F38BD8A7BDB8EC1AEA1C19A3B4`

## フォルダ構成

- `source/`: 解析元APKのコピー
- `extracted-apk/`: APK全体の展開結果（2,263ファイル）
- `assets-by-type/images/`: PNG/JPG画像 1,214ファイル
- `assets-by-type/audio/`: MP3/OGG音声 5ファイル
- `assets-by-type/video/`: 動画ファイル（APK内にはなし）
- `assets-by-type/fonts/`: フォント（APK内にはなし）
- `assets-by-type/containers/`: NPK/TFLite 2ファイル
- `assets-by-type/web/`: HTML/CSS/JavaScript 3ファイル
- `assets-by-type/video/downloaded-res/`: 更新後に取得したMP4 16ファイル（原本へのハードリンク）
- `assets-by-type/containers/downloaded/`: 取得済みOBB/NPK原本（原本へのハードリンク）
- `decoded-wpk-typed/`: WPK展開物の型付きコピー（KTX1/FEV、manifest付き）
- `decoded-cloud/zipres/script3-all/`: script3.zipの復号・zlib第2段階展開物
- `reports/file-manifest.csv`: 全ファイルの相対パス、容量、SHA-256
- `reports/image-manifest.csv`: 画像のパス、寸法、形式、容量
- `reports/extension-summary.csv`: 拡張子別集計
- `reports/apk-badging.txt`: パッケージ情報・権限・SDK情報
- `reports/resources-dump.txt`: Androidリソーステーブルのダンプ

## 注意

このベースAPKに含まれる画像は、主にアプリアイコン、ログインUI、決済UI、Webローディング素材です。ゲーム本編のキャラクター画像・背景・動画・音声の大部分はAPK内にはなく、初回起動後にOBBおよびNPK形式で追加取得されます。

`assets/a1.npk` は4KB弱の独自形式データで、一般的なZIPアーカイブではありません。

## 抽出済み形式について

OBB/NPKの原本と元形式の抽出物を保持し、閲覧用のPNG/WAV/OBJを `converted/` に生成しています。KTX全155,695件をPNGに変換し、DDS/PVR全34件も面・スライス単位で変換。FSB15バンクから672トラックをWAVに展開しました。重複画像はSHA-256でまとめ、manifestに各原本との対応を残しています。

モデルのOBJは形状・法線・UV・グループを含みます。材質の結合、スキニング、アニメーションはOBJに含まれません。HDR DDSは浮動小数点RGBをPFMにも保存し、PNGは0〜1にクランプしたプレビューです。KTXは最上位の画像をPNG化し、小さなmipmapは原本内に保持しています。

3Dビューアーは一覧の「3Dで形状・テクスチャを確認」から開く。初期テクスチャ候補は同じNPKフォルダ内でモデルのインデックスに近い画像で、正式な材質対応ではない。右側の検索欄からファイル名またはハッシュで全画像を検索して適用できる。テクスチャ解除、ワイヤーフレーム、フラット陰影、全体表示にも対応。

`converted/typed-binary/` は原本へのハードリンクです。ここにあるファイルを直接編集すると対応する抽出元も変わるため、編集用には別のコピーを作成してください。
