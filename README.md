# String Quartet Part Extractor

Photographed quartet score pages から、指定した1パートだけを抜き出してPDFにします。

## Webプロトタイプ

依存関係を入れて、Flaskアプリとして起動できます。

```powershell
pip install -r requirements.txt
python app.py
```

ブラウザで `http://localhost:5000` を開きます。

画面でできること:

- 画像を複数アップロード
- 画像の順番変更
- 画像の削除
- パート1からパート4のPDF作成
- 4パートまとめてZIP作成

Renderでは `render.yaml` を使ってWeb Serviceとして起動できます。

## 使い方

```powershell
python extract_part.py "p*.jpg" --part violin1 --output violin1.pdf
```

抜き出した段は入力画像1枚ごとではなく、A4縦ページに上から順に詰めて配置します。
既定では段と段の間隔は10mmです。

指定できるパート:

- `violin1`
- `violin2`
- `viola`
- `violoncello` または `cello`

## 前処理

既定では、抽出前に各JPEGへ軽い前処理を行います。

- 紙面らしい領域を検出して、外側の背景を取り除く
- 五線が水平に近くなるよう軽く傾き補正する
- 紙面全体の明るさを整える

前処理後の画像を確認したい場合:

```powershell
python extract_part.py "p*.jpg" --part viola --output viola.pdf --preprocess-debug-dir preprocessed
```

前処理を切りたい場合:

```powershell
python extract_part.py "p*.jpg" --part viola --output viola.pdf --no-preprocess
```

## 見た目の補正

切り出した譜面の紙色や影は、白に寄せて黒い五線と音符が残るように補正します。
補正の強さは `--clean-strength` で調整できます。

```powershell
python extract_part.py "p*.jpg" --part violin1 --output violin1.pdf --clean-strength 1.5
```

抽出した各段を横幅はそのまま、縦方向だけ拡大したい場合は `--vertical-scale` を使います。
`1.2` から `1.4` くらいが試しやすい範囲です。

```powershell
python extract_part.py "p*.jpg" --part viola --output viola.pdf --vertical-scale 1.25
```

縦に伸ばすほど読みやすくなる場合がありますが、1ページに入る段数は少なくなります。

## リハーサルマーク

リハーサルマークは既定で各パートの同じ横位置に出るようにします。
Violin1以外のパートでは、上部帯をそのまま貼るのではなく、箱付きアルファベットだけを白背景に抜き出して合成します。

不要な場合だけ `--no-rehearsal-marks` を指定します。

```powershell
python extract_part.py "p*.jpg" --part cello --output cello.pdf --no-rehearsal-marks
```

## 検出結果の確認

切り出し前の検出位置を確認したい場合:

```powershell
python extract_part.py "p*.jpg" --part violin1 --output violin1.pdf --debug-dir debug
```

`debug` フォルダに、検出した4パートの位置を色付きで描いた画像が出ます。
色は上から順に、赤=Violin1、橙=Violin2、緑=Viola、青=Violoncelloです。

## 調整

検出が薄い五線を拾えない場合は、`--percentile` を少し下げます。

```powershell
python extract_part.py "p*.jpg" --part violin1 --output violin1.pdf --percentile 65
```

音部記号の左側が切れる場合は、`--x-margin` を小さくします。

```powershell
python extract_part.py "p*.jpg" --part violin1 --output violin1.pdf --x-margin 0.01
```

段間隔を変えたい場合は、`--gap-mm` を7から15程度で調整します。

```powershell
python extract_part.py "p*.jpg" --part violin1 --output violin1.pdf --gap-mm 12
```
