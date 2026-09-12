# Androidエミュレータ経由のAPK回収・アセット抽出

このフォルダは、Windows上でADB操作可能なAndroidエミュレータを使い、インストール済みアプリのAPKを回収し、APK内のファイルを一括抽出・分類するための作業領域です。

## 導入済みの構成

- SDK root: `C:\Users\palla\Documents\android-apk-analysis\android-sdk`
- AVD: `apk-lab`
- System image: Android 15 / Google APIs / x86_64
- Emulator: `-accel auto`、SwiftShader
- ADB: SDK rootの`platform-tools\adb.exe`
- JDK: Microsoft OpenJDK 17

ユーザー環境変数として`ANDROID_SDK_ROOT`、`ANDROID_HOME`、`JAVA_HOME`を設定済みです。新しいPowerShellを開くと、`adb`、`emulator`、`sdkmanager`、`avdmanager`をそのまま呼び出せます。

## 起動とADB接続

```powershell
emulator @apk-lab -accel auto -gpu swiftshader_indirect -no-snapshot -no-boot-anim -no-metrics
adb wait-for-device
adb devices -l
adb -s emulator-5554 shell getprop sys.boot_completed
```

`sys.boot_completed`が`1`になれば起動完了です。今回のAVDはWindows Hypervisor Platformが利用できるため、自動アクセラレーションで起動しています。

## APK回収

端末にインストール済みのパッケージ名を指定して回収します。分割APKの場合は、`base.apk`と各`split-*.apk`をすべて取得します。

```powershell
.\tools\pull-installed-apk.ps1 `
  -PackageName 'org.example.app' `
  -Serial 'emulator-5554' `
  -OutputDirectory '.\apk\org.example.app'
```

手動で確認する場合は次の流れです。

```powershell
adb -s emulator-5554 shell pm path org.example.app
adb -s emulator-5554 pull /data/app/.../base.apk .\apk\base.apk
```

## APK全体とアセットの抽出

```powershell
.\tools\extract-apk-assets.ps1 `
  -ApkPath '.\apk\org.example.app\base-base.apk' `
  -OutputDirectory '.\extracted\org.example.app'
```

生成物は次のとおりです。

- `apk\`: APKのZIP構造を保った全展開
- `assets\`: APK内の`assets/`だけを平坦な作業用ルートへ複製
- `reports\file-inventory.csv`: 展開ファイルのカテゴリ、サイズ、SHA-256
- `reports\zip-entry-inventory.csv`: APK ZIPエントリの圧縮前後サイズ
- `reports\category-summary.csv`: `assets`、`res`、`lib`、DEXなどの集計
- `reports\extension-summary.csv`: 拡張子別の集計
- `reports\analysis.json`: APKハッシュと集計値の機械可読レポート
- `reports\aapt-badging.txt`: package名、version、SDK、permissionなど
- `reports\manifest-xmltree.txt`: バイナリAndroidManifestの`aapt`表示
- `reports\signature-verify.txt`: APK署名検証結果
- `reports\apkanalyzer-summary.txt`: `apkanalyzer`によるpackage/version summary
- `reports\apkanalyzer-files.txt`: `apkanalyzer`が認識したファイル一覧

## 実証結果

権利上安全なオープンソースのKiwix Android 3.14.1（x86_64 standalone APK）で検証しました。

- パッケージ: `org.kiwix.kiwixmobile.standalone`
- APK: `apk\kiwix-v3.14.1-installed-base.apk`
- APK SHA-256: `3aa782f421b9aa2c1dbdb7baef000fd766f2cd7adfebcad792253dcef1657ddf`
- APK全体: 1,063ファイルを抽出
- `assets/`: 17ファイル、11,480,368 bytes
- native library: 6ファイル、57,278,984 bytes
- APK署名: v2検証成功

アプリ内の追加リソースとして、Project EulerのZIMをダウンロードし、アプリ終了後に端末から回収しました。

- 実行時資源: `runtime\freecodecamp_en_project-euler_2026-08.zim`
- サイズ: 7,281,613 bytes
- 重要な区別: このZIMはAPK内の`assets/`ではなく、アプリ実行中に外部から取得されたランタイムデータです。

Kiwixにはログイン画面がないため、今回の実証では初期設定完了→追加コンテンツのダウンロード→アプリ終了→APKとランタイム資源の回収、という流れで代替しました。ログインを持つアプリでは、認証情報を入力せず、ログイン画面まで到達した状態で同じ回収手順を実行できます。

## 商用アプリを対象にする場合

Google Play配布のアプリは、base APKだけでなく分割APKやPlay Asset Deliveryを使うことがあります。その場合、`pm path`で列挙された全APKを回収し、端末の`/sdcard/Android/media`、`Android/obb`、アプリ固有の外部ストレージも別々に保存します。認証、DRM、暗号化、アクセス制御の回避は行わず、利用許諾のあるアプリ・資産だけを対象にしてください。
