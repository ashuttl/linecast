<div align="center">

# linecast

**天気、潮汐、太陽、月、地図、そしてプラネタリウムを、ターミナルで。『The Old Farmer's Almanac』とミニテルの出会い。**

[![Tests](https://github.com/ashuttl/linecast/actions/workflows/test.yml/badge.svg)](https://github.com/ashuttl/linecast/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/linecast)](https://pypi.org/project/linecast/)
[![Python](https://img.shields.io/pypi/pyversions/linecast)](https://pypi.org/project/linecast/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<a href="https://terminaltrove.com/linecast/" title="linecast on Terminal Trove, the $HOME of all things in the terminal"><img src="https://cdn.terminaltrove.com/media/badges/tool_of_the_week/svg/terminal_trove_tool_of_the_week_green_on_dark_grey_bg.svg" alt="Terminal Trove Tool of The Week" height="36"></a>

[English](README.md) | 日本語

</div>

この日本語版は英語版READMEの要約です。全文と最新の内容は[英語版](README.md)にあります。

![Omarchyのデスクトップに並んだlinecastの天気、レーダー、月、一年、そして夕暮れの太陽](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/hero.png)

linecastは、無料で公開されているデータを、macOS・Linux・Windowsで動く7つのターミナルアプリで見せます。どれもリアルタイムに更新され、マウスでも操作できます。依存パッケージのない純粋なPythonで書かれ、色はターミナルのテーマに従い、アカウントもAPIキーも要りません。SSH越しでも、tmuxの中でも、ターミナルが動くところならどこでも動きます。

| コマンド | 表示するもの |
| --- | --- |
| `linecast weather` | 現在の天気、1時間ごとと7日間の予報、45か国の公式警報 |
| `linecast sunshine` | 今日の太陽が空を渡る軌跡と、一年を通じた昼の長さ |
| `linecast moon` | その場所から見た月。月の出と月の入りの時刻、次の満月と新月 |
| `linecast sky` | 今いる場所から見た空。夜には、ターミナルのプラネタリウムが星、星座、惑星、月、天の川を映します |
| `linecast tides` | 昼夜で陰影をつけた、スクロールできる潮汐曲線 |
| `linecast radar` | 世界中の気象レーダーをアニメーション表示。警報、気温、風も文字の升目に描きます |
| `linecast maps` | 街路地図、地形、そして今の昼夜と雲を映した回せる地球儀。地名検索と経路案内つき |

**[インストール](#インストール) · [使い方](#使い方) · [日本語で](#日本語で) · [設定](#設定) · [貢献するには](#貢献するには)**

## インストール

[Homebrew](https://brew.sh/)で:

```sh
brew install linecast
```

または[uv](https://docs.astral.sh/uv/)で:

```sh
uv tool install linecast
```

`pipx install linecast` と `pip install linecast` も使えます。コミュニティによるパッケージが[AUR](https://aur.archlinux.org/packages/linecast)と[nixpkgs](https://search.nixos.org/packages?channel=unstable&show=linecast)（今のところunstableチャンネル）にもあります。linecastにはPython 3.10以降が必要です。

何もインストールせずに試すには:

```sh
uvx linecast weather
```

curlだけでも動きます。[`get.sh`](get.sh)がマシンにあるPythonを探し、それでlinecastを実行します:

```sh
curl -sL https://raw.githubusercontent.com/ashuttl/linecast/main/get.sh | sh
```

これで `weather` が開きます。行末の `sh` を `sh -s sunshine` にすると別のツールが開き、`sh -s -- --metric` ならフラグを渡せます。

<details>
<summary><strong>Windowsでは</strong></summary>

Windows Terminalを使ってください。Git Bashとminttyは、linecastからはターミナルではなくパイプに見えるため、静止した出力になります。Windowsではインストール時に2つのパッケージが加わります。Windowsに独自のタイムゾーンデータベースがないための `tzdata` と、TLSにWindowsが信頼する証明書を使わせるための `truststore` です。アイコンは絵文字ですが、Nerd Fontを設定していれば `linecast icons nerd` でフルセットに切り替わります。

</details>

## 使い方

どのコマンドも、[場所を保存する](#場所)までは、IPアドレスから推定した場所で開き、リアルタイムに更新されます。キー操作は `?` で表示されます。

`weather` では、右上の地名をクリック（または `l`）すると、最近の場所を選んだり、**場所を追加**で検索したりできます。文字を打つと候補が出て、↑/↓ で選び、Enter かクリックで決めます。Escape で閉じます。`/` で検索を直接開きます。最近の場所は10件まで保存され、**最近の場所を消去**で空にできます。**［場所］を既定の場所に設定**を選ぶと、表示中の場所がすべてのビューの既定になります。すでに既定の場所を見ているときは表示されません。`tides` でも、左上の観測地点名をクリック（または `l`）すると同じメニューが開き、選んだ場所に最も近い観測地点に切り替わります。最近の場所は `weather` と共通です。

コマンドをそのまま、あるいはフラグ付きで試してみてください:

```sh
linecast weather --location "kyoto"
linecast radar --location 44.35,-68.22
linecast sky --culture hawaiian --location molokai
linecast sunshine --year --location "vostok station"
linecast moon --lang zh
linecast tides --station "Burntcoat Head"
linecast maps --view terrain --location "new zealand"
linecast maps --from "477 congress street 04101" --to "portland head light" --profile bike
linecast maps --view now
```

`--print` を付けると、更新し続ける表示の代わりに静止した1フレームを出力します。weather、sunshine、moon、sky、tidesには、生データを出す `--json` と、ステータスバー用の `--oneline` もあります。

![ヒーロー画像のアニメーション版。気象レーダーが動いている](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/hero.gif)

各アプリの詳しい説明とスクリーンショットは[英語版README](README.md#a-closer-look)に、それぞれのアプリのさまざまな状態は[docs/gallery.md](docs/gallery.md)にあります。

## 日本語で

ターミナルの言語が日本語なら、linecastは日本語で話します。そうでないときは、次のいずれかで日本語にできます:

```sh
linecast language ja            # 既定を日本語に
linecast weather --lang ja      # 今回だけ
export LINECAST_LANG=ja         # 環境変数で。保存した設定より優先されます
```

`weather` の警報は日本では気象庁から届き、画面の下の行にその名が出ます。`moon` は月相のとなりに旧暦の日付を添え、旧暦の日付に応じて、その夜を十六夜、立待月、居待月、寝待月、更待月などの名で呼び、今の二十四節気と、次の節気を迎える日、次の十五夜までの日数を示します。`sunshine --hours japanese` は、常用時のとなりに江戸の不定時法で一日を読みます。

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/weather-kyoto.png" width="49%" alt="京都の天気、日本語で">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/moon-okinawa.png" width="49%" alt="沖縄の月、日本語で。十六夜、旧暦八月十六日">
</p>

## 設定

設定は `~/.config/linecast/config.json` に保存されます。コマンドラインのフラグが環境変数より優先され、環境変数が保存した設定より優先されます。以下の設定コマンドを引数なしで実行すると現在の値が表示され、`auto` を渡すと既定値に戻ります。

### 場所

場所を一度保存すれば、すべてのコマンドがそれを使います。一回だけなら、フラグで渡します:

```sh
linecast location set "Kyoto"             # 地名で
linecast location set 35.01,135.77        # または 緯度,経度 で
linecast location search fuchu            # その名前が指しうる場所を一覧する
linecast location auto                    # IPアドレスからの推定に戻す
linecast weather --location "Nara"        # 今回だけ
```

地名は一度だけ検索され、最初に一致した場所が保存されます。意図した場所でなかった場合は、`search` で他の候補を確認できます。

場所を保存せず、フラグでも渡していない場合、linecastは[ipinfo.io](https://ipinfo.io/)にネットワーク接続の場所を尋ねます。たいていは正しい都市ですが、時には外れ、VPNや社内ネットワークでは大きくずれます。SSH越しではサーバーの場所が推定されるので、そこでは場所を保存してください。回答は1時間キャッシュされます。場所を保存すれば、この問い合わせは一切行われません。

### 単位と時計

既定では、linecastはアメリカ合衆国ではヤード・ポンド法、それ以外ではメートル法を使います。時刻は、6:50 pmと書く国では12時間制、それ以外では24時間制です。日本では、メートル法と24時間制になります。好みを記憶させるには、次のコマンドを一度実行します:

```sh
linecast units imperial
linecast clock 12
```

表示系のコマンドはどれも、一回限りの `--metric` と `--imperial` を受け付けます。時刻を表示するものは `--12h` と `--24h` も受け付けます。`weather` には気温だけを切り替える `--celsius` と `--fahrenheit` もあり、マイルと摂氏の組み合わせもできます。

月のカレンダーは週を月曜日から始めます。ただし、日本、韓国、アメリカ合衆国、カナダ、ブラジル、メキシコなど、印刷されたカレンダーが日曜日から始まる国では日曜日から、エジプトと湾岸諸国では土曜日からです。`linecast week monday` で固定でき（`sunday` と `saturday` も）、`moon --week-start monday` なら一回だけです。

### 言語

ターミナルの言語がlinecastの知っている言語なら、その言語で話します。そうでなければ英語です。自分で選ぶなら、既定値にも、その回だけにも指定できます:

```sh
linecast language ja        # 既定を日本語に
linecast language auto      # ターミナルに従う
linecast radar --lang en    # 今回だけ
```

言語は、英語（`en`）、フランス語（`fr`）、スペイン語（`es`）、ポルトガル語（`pt`）、イタリア語（`it`）、ルーマニア語（`ro`）、ドイツ語（`de`）、オランダ語（`nl`）、デンマーク語（`da`）、ノルウェー語（`no`）、スウェーデン語（`sv`）、アイスランド語（`is`）、フィンランド語（`fi`）、チェコ語（`cs`）、ポーランド語（`pl`）、ロシア語（`ru`）、ウクライナ語（`uk`）、ギリシャ語（`el`）、トルコ語（`tr`）、ペルシア語（`fa`）、スワヒリ語（`sw`）、中国語の簡体字（`zh`）と繁体字（`zh-Hant`）、日本語（`ja`）、韓国語（`ko`）、タイ語（`th`）、ベトナム語（`vi`）、インドネシア語（`id`）、エスペラント（`eo`）です。スワヒリ語の星空では、南十字座とさそり座に文献のある名前を使い、ほかの星座と星はカタログの名前のままです。中国語のターミナルロケールは地域で字体を選びます。`zh_TW`、`zh_HK`、`zh_MO` は繁体字、`zh_CN`、`zh_SG` は簡体字です。ノルウェー語のロケール `nb_NO` と `nn_NO` はノルウェー語になります。ポルトガル語はブラジル、スペイン語は中南米、フランス語はフランスの言葉づかいです。ポルトガル、スペイン、カナダで異なる語は `pt-PT`、`es-ES`、`fr-CA` で読めます。ターミナルロケールが `pt_PT`、`es_ES`、`fr_CA` なら、それを自動で選びます。

ペルシア語は右から読みます。ダッシュボード、潮汐、月のカレンダー、日照の年表示は右端から並び、現在は右側にあります。日付はイラン暦（ヒジュラ太陽暦）です。`linecast dates gregorian` で暦を固定できます（`solar-hijri` も、どの言語でも）。数字はペルシア数字で書き、`linecast digits latin` なら 0–9 のままです（`native` でペルシア数字に戻ります）。多くのターミナルは右から左の文字を逆向きに描き、アラビア文字をつなげないので、linecast が自分で並べてつなげ、そのまま描くようターミナルに頼みます。アラビア文字を含む等幅フォント、たとえば [Vazir Code](https://github.com/rastikerdar/vazir-code-font) なら文字がきれいにつながります。自分で文字を並べ替え、その頼みを聞かないターミナルでは二重に反転するので、`LINECAST_BIDI=terminal` で並べ替えをターミナルに任せます。

インドでは、多くの警報が州の言語で発表されます。`weather` に `--lang hi`、`--lang te`、`--lang mr` などインドの言語コードを付けると、その言語の警報があればそれで読めます。アプリのほかの部分は英語のままです。

### 暦

`moon` を日本語、中国語、韓国語、ベトナム語、タイ語で実行すると、その言語の伝統暦を使います。日本語なら旧暦です。自分で選ぶなら、既定値にも、その回だけにも指定できます:

```sh
linecast calendar hebrew            # 既定をヘブライ暦に
linecast calendar none              # 伝統暦なし
linecast calendar auto              # 言語に従う
linecast moon --calendar hawaiian   # 今回だけ
```

暦は `chinese`、`japanese`、`korean`、`vietnamese`、`thai`、`hawaiian`、`samoan`、`chamorro`、`refaluwasch`、`islamic`、`hebrew`、`almanac` です。それぞれの説明は[docs/calendars.md](docs/calendars.md)にあります。

### 時刻法

`sunshine` は、常用時のとなりに、ある伝統の時刻法で一日を読むことができます。選ぶなら、既定値にも、その回だけにも指定できます:

```sh
linecast hours japanese             # 江戸の不定時法。昼夜それぞれ六つの刻
linecast hours halachic             # グラの方式によるゼマニーム
linecast hours halachic-mga         # マゲン・アブラハムの方式
linecast hours roman                # 十二のホラと四つのウィギリア
linecast hours islamic              # 礼拝時刻。表示中の国の慣例で
linecast hours islamic-isna         # または名前で指定した慣例で
linecast hours swahili              # スワヒリ時間。朝七時が saa 1 asubuhi
linecast hours none                 # 常用時のみ
linecast sunshine --hours japanese  # 今回だけ
```

`auto` で設定を消します。スワヒリ語ではスワヒリ時間で読みます。それがこの言語の時刻の言い方だからです。ほかの言語では none と同じです。それぞれの説明は[docs/hours.md](docs/hours.md)にあります。

### 星空の伝統

`sky` は中国語では中国の星空を描き、他の言語ではIAUの星座を描きます。22の伝統から選ぶには `linecast culture` と `sky --culture` を使います。`sky` の中では `t` を押して一覧から選べます。名前と出典は[docs/cultures.md](docs/cultures.md)にまとめています。

### そのほかの設定

色とアイコン、短い名前とシェル補完、表示がおかしいときの対処、環境変数、データの出典と対象範囲は、[英語版README](README.md#settings)にあります。

## 貢献するには

質問、要望、アイデアは[Discussions](https://github.com/ashuttl/linecast/discussions)へ。プルリクエストも歓迎です。どんな変更が合うか、どのブランチから始めるか、テストの実行方法は[CONTRIBUTING.md](CONTRIBUTING.md)（英語）にあります。この日本語訳への修正も歓迎します。

## 系譜

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/minitel-terminatel-258.jpg" width="380" alt="3615 LINECAST">
</p>

<p align="center"><em>先行技術。</em></p>

Telic-Alcatelのビデオテックス端末が天気を描いています。1990年ごろ。写真は[minitel-alcatel.fr](https://www.minitel-alcatel.fr/)の収蔵品から。

## ライセンス

[MIT](LICENSE)
