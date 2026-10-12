# CLI リファレンス

> `p8080` の**コマンドとオプションのリファレンス**です。`-c` で渡す設定ファイルは [config.md](config.md)、解析の進め方は [workflow.md](workflow.md)、アセンブリの構文は [language.md](language.md) を参照してください。

`p8080` コマンド（または `python -m p8080`）で使います。サブコマンドは 3 つです。

| サブコマンド | 内容 |
| --- | --- |
| [`asm`](#asm) | アセンブリソースをバイナリにする |
| [`disasm`](#disasm) | バイナリを逆アセンブルする |
| [`walk`](#walk) | 制御の流れを追って、コードとデータの境目を調べる |

> **このページのヘルプ出力は Python 3.10 / 端末幅 90 桁で生成しています。**
> `argparse` の表示は Python のバージョンで変わるため（3.13 以降は
> `-f FILE, --file FILE` が `-f, --file FILE` と短く出ます）、
> お使いの環境では表示が異なる場合があります。

```bash
C:\>p8080
usage: p8080 [-h] {disasm,walk,asm} ...

Intel 8080 assembler & disassembler v0.1.0

positional arguments:
  {disasm,walk,asm}
    disasm           8080 disassembler
    walk             Detect data regions in binary via CFG tracing
    asm              8080 assembler

options:
  -h, --help         show this help message and exit

C:\>
```

## asm

```bash
C:\>p8080 asm --help
usage: p8080 asm [-h] -f FILE -o OUTPUT [-s SIZE] [-D DEFINE]

options:
  -h, --help            show this help message and exit
  -f FILE, --file FILE  asm file
  -o OUTPUT, --output OUTPUT
                        output file(bin)
  -s SIZE, --size SIZE  *option* : output file(bin) size
  -D DEFINE, --define DEFINE
                        symbol definition for conditional assembly (repeatable, merged
                        left to right). NAME=VALUE, NAME (=1), or a Python dict.
                        example: -D DEBUG=1

C:\>
```

アセンブリソースをアセンブルして、バイナリを出力します。

```bash
p8080 asm -f source.asm -o output.bin
```

| オプション | 内容 |
| --- | --- |
| `-f`, `--file` | 入力のアセンブリファイル（必須） |
| `-o`, `--output` | 出力のバイナリファイル（必須） |
| `-s`, `--size` | 出力の大きさ。足りない分は `0x00` で埋める |
| `-D`, `--define` | 条件アセンブル用のシンボル（何度でも指定可）。書き方は [language.md](language.md#条件アセンブル-if--elseif--else--endif) を参照 |

## disasm

```bash
C:\>p8080 disasm --help
usage: p8080 disasm [-h] [-i INPUT] [-c CONFIG] [-s START] [-n] [-o OUTPUT]

options:
  -h, --help            show this help message and exit
  -i INPUT, --input INPUT
                        input image file (specify -i multiple times for multiple files)
  -c CONFIG, --config CONFIG
                        config file (Python module, see README)
  -s START, --start START
                        start address
  -n, --nodump          remove dump info
  -o OUTPUT, --output OUTPUT
                        output file

C:\>
```

バイナリを逆アセンブルします。

```bash
p8080 disasm -i rom.bin
p8080 disasm -i rom.bin -c rom_config.py -n -o rom.asm
```

| オプション | 内容 |
| --- | --- |
| `-i`, `--input` | 入力のバイナリ（複数指定可。アドレス 0 から順に並べる）。設定ファイルに `bins` を書けば不要 |
| `-c`, `--config` | 設定ファイル（[config.md](config.md)） |
| `-s`, `--start` | 開始アドレス（既定は `0x0000`、または設定ファイルの `start`）。ROM の終わりより後ろならエラーになる。`bins` の隙間を指すときは、次の ROM から逆アセンブルする |
| `-n`, `--nodump` | アドレスとバイト列を出さず、アセンブリだけを出す |
| `-o`, `--output` | 出力ファイル（既定は標準出力）。UTF-8 で書く |

出力の形は 2 つあります。ニーモニックは大文字、レジスタは小文字で出ます。

```
0x0100 3E 01          MVI a, 0x01        ← 既定（アドレス・バイト列付き）
    MVI a, 0x01                          ← -n
```

**どちらの形も、そのまま `p8080 asm` で組み直せます。** 組み直した結果は元のバイナリと一致します（[workflow.md](workflow.md#5-組み直して確かめる)）。

設定ファイルの指定どおりに出せなかった箇所（`data` の `fmt` で範囲を割り切れない、など）は、`Warning:` で始まる行として標準エラーに出ます。設定ファイルの誤り（ラベル名に使えない文字、範囲外のアドレスなど）は、`Error:` で始まる 1 行を標準エラーに出して終了コード 1 で止まります。

## walk

```bash
C:\>p8080 walk --help
usage: p8080 walk [-h] [-i INPUT] [-c CONFIG] [-s START] [-e ADDR_OR_SYMBOL]
                  [--auto-entry]

options:
  -h, --help            show this help message and exit
  -i INPUT, --input INPUT
                        input binary file (specify -i multiple times for multiple files)
  -c CONFIG, --config CONFIG
                        config file (Python module, see README)
  -s START, --start START
                        start address (default: 0x0000)
  -e ADDR_OR_SYMBOL, --entry ADDR_OR_SYMBOL
                        additional entry point (address or: RESET/RST0-7)
  --auto-entry          auto-detect entry points from dispatch idioms (jump tables etc.)

C:\>
```

エントリポイントから制御の流れを追い、**コードとして到達できない範囲**を出力します。出力は設定ファイルの `data` の形なので、そのまま保存して `disasm -c` に渡せます。

```bash
p8080 walk -i practice.bin -e RST7 > practice_cfg.py
p8080 disasm -i practice.bin -c practice_cfg.py
```

```python
data = [
    [0x0007, 0x0017],
    [0x0023, 0x0037],
    [0x0043, 0x018F],
    [0x01AB, 0x01BD],
    [0x01BF, 0x03FF],
]
```

（[workflow.md](workflow.md) の練習用 ROM での出力です）

| オプション | 内容 |
| --- | --- |
| `-i`, `--input` | 入力のバイナリ（複数指定可。アドレス 0 から順に並べる）。設定ファイルに `bins` を書けば不要 |
| `-c`, `--config` | 設定ファイル。`bins` / `start` / `entry` / `m1_handler` を使う |
| `-s`, `--start` | 最初に追うアドレス（既定は `0x0000`、または設定ファイルの `start`）。ROM を置く位置は変わらない（`-i` の ROM は `0x0000` から並ぶ。ほかの位置に置くなら `bins`） |
| `-e`, `--entry` | 追加のエントリポイント（複数指定可）。シンボル名かアドレス。設定ファイルの `entry` に足される |
| `--auto-entry` | ジャンプテーブルなどからエントリポイントを探す（[後述](#エントリポイントの自動抽出---auto-entry)） |

`bins` で複数のファイルを置いたとき、どのファイルも置かれていないアドレスは出力から除外されます。`disasm` も同じです。

### エントリポイントのシンボル名

8080 の固定のアドレスは、シンボル名でも指定できます。

| シンボル | アドレス | 内容 |
| --- | --- | --- |
| `RESET` / `RST0` | `0x0000` | リセット |
| `RST1` 〜 `RST7` | `0x0008` 〜 `0x0038` | `RST n` の飛び先（n × 8。8 バイトおき） |

**割り込みの入口も `RST1`〜`RST7` で指定します。** 8080 は割り込みを受けると、外部の回路がデータバスに置いた命令を実行します。普通は `RST n` で、どれを使うかは基板の配線で決まり、ROM を見ても分かりません。Z80 の `NMI`（`0x0066`）と `IM1` に当たるものは 8080 には無く、書くとエラーになります。

### 追う分岐

* `JMP` / `Jcc`（`JNZ` など）/ `CALL` / `Ccc`（`CNZ` など）: アドレスを直接書いた分岐と呼び出し。条件付きのものは次の命令へも進む
* `RST n`: `n × 8` のアドレスへの呼び出しとして追い、次の命令へも進む
* `RET`: そこで流れが終わる。条件付きの `Rcc`（`RNZ` など）は次の命令へも進む
* `HLT`: 次の命令へ進む（割り込みから戻ると続きを実行するため）

`JP` は「正なら飛ぶ」条件付きジャンプなので、次の命令へも進みます（Z80 の無条件 `JP` とは違います）。

`PCHL`（HL のアドレスへ飛ぶ）は、飛び先が実行時の値で決まるので追えません。飛び先は `-e` で指定するか、`--auto-entry` で探します。

### エントリポイントの自動抽出 (--auto-entry)

間接分岐の飛び先は、多くの場合ジャンプテーブルに並んでいます。`--auto-entry` は、到達できたコードの中から**分岐の定型の書き方**を探し、表を読んでエントリポイントを足します。

```bash
p8080 walk -i practice.bin -e RST7 --auto-entry
```

```python
# auto-entry: [push-return] @0x0196 -> 0x01B4
# auto-entry: [rst-vector] @0x019D -> 0x0018
# auto-entry: [inline-after-rst] @0x019D table=0x019E stride=2 -> 0x01A4 0x01AB 0x01AF
# auto-entry: [pchl] @0x01CE table=0x01CF stride=2 -> 0x0200 0x0201 0x0202
# auto-entry: entry = -e 0x0000 -e 0x0018 -e 0x0038 -e 0x01A4 -e 0x01AB -e 0x01AF -e 0x01B4 -e 0x0200 -e 0x0201 -e 0x0202
data = [
    [0x0007, 0x0017],
    [0x0023, 0x0037],
    [0x0043, 0x018F],
    [0x019E, 0x01A3],
    [0x01CF, 0x01FF],
    [0x0206, 0x03FF],
]
```

**最後の `entry =` 行が結果**です。その上の行は、見つけた分岐の形を 1 件ずつ示すもので、**finding lines** と呼びます。`[ ]` の中が形の名前、`@` が見つけた命令のアドレス、`->` の後ろが足したエントリポイントです。`# ` で始まる行は Python のコメントなので、出力をそのまま設定ファイルに保存できます。

> **誤ったエントリポイントは、データをコードとして読ませてしまいます。** finding lines を確認し、正しいものを設定ファイルの `entry` に移して使ってください。`--auto-entry` は既定では無効です。

見つける形は次のとおりです。

| 形の名前 | 形 | 扱い |
| --- | --- | --- |
| `pchl` | `LXI H,tbl` → 添字を足す → `PCHL` | 表を読む。表のアドレスを RAM 経由で渡す形（`SHLD` → `LHLD`、`MVI A` → `STA` ×2）も追う。途中に `XTHL` があれば、それより前に HL へ入れた値は表とみなさない |
| `push-ret` | `PUSH H` → `RET` | 表を読む |
| `inline-after-call` | `CALL disp` の直後に表。`disp` が `POP H` / `POP D` で取り出す | 戻りアドレスを表の先頭として読む |
| `inline-after-rst` | `RST n` の直後に表（[下記](#rst-直後の表)） | 同上 |
| — | 表の中身が `JMP nnnn` の並び | 各 `JMP` のアドレスをエントリにする（上の形で表を読むときに判定） |
| `rst-vector` | 到達したコードにある `RST n` | その飛び先（n × 8）をエントリにする |
| `push-return` | `LXI H,nn` → `PUSH H`（[下記](#積んだ戻り先)） | `nn` をエントリにする |
| `xthl-return` | `LXI H,nn` → `XTHL`（[下記](#積んだ戻り先)） | 同上 |
| `sphl-ret` | `SPHL` → `RET` | 飛び先が実行時のスタックで決まるので、報告だけする |
| `rom-stack` | `LXI SP,nn`（`nn` は ROM）→ `RET`（[下記](#rom-に置いたスタックと-ram-に置いた飛び先)） | `nn` からの語を飛び先の並びとして読む |
| `pchl-ram` | `LHLD ram` → `PCHL`（[下記](#rom-に置いたスタックと-ram-に置いた飛び先)） | `ram` に書いた値を飛び先にする |

#### RST 直後の表

`RST n` の直後に `dw` の表を置き、`RST` の飛び先が `POP H` で戻りアドレス（＝表の先頭）を取り出して飛ぶ形です。この `RST` は呼び出し元へ戻らないので、直後のバイトはデータとして扱われます。

```asm
    MVI  A, 1           ; 添字
    RST  3
    dw   handler0, handler1, handler2   ; 命令の直後が表

    org 0x0018
    ADD  A              ; 添字を 2 倍
    POP  H              ; 戻りアドレス = 表の先頭
    MOV  E, A
    MVI  D, 0
    DAD  D
    MOV  E, M
    INX  H
    MOV  D, M
    XCHG
    PCHL
```

表の長さは書かれていないので、次のどれかに当たったところを終わりとします。

* イメージの外を指す値、または `0x0000`
* 直前と同じ値（離れた位置で同じ値が出るのは構いません）
* 既に命令と分かっているアドレスに重なる
* 表より後ろを指す飛び先のうち、いちばん近いものに達した

#### 積んだ戻り先

`LXI H, nn` の直後に `PUSH H` があると、`nn` をエントリに加えます。後で `RET` したときの戻り先になるからです。積んだ値をすぐ `POP` で戻している場合（遅延ループの回数など）は除きますが、誤検出の余地は残るので finding lines を確認してください。

`PUSH H` の代わりに `XTHL` で積む形（`xthl-return`）も同じように扱います。`XTHL` はスタックの先頭と HL を入れ替えるので、`nn` がスタックに載ります。次の例では、戻り先を積んでから DE のアドレスを呼んでいます。

```asm
    PUSH H
    LXI  H, resume      ; 戻り先
    XTHL                ; resume を積み、先に積んだ値を HL へ戻す
    PUSH D
    PCHL                ; DE のアドレスを呼ぶ。戻ると resume へ
resume:
    POP  H
```

このとき `PCHL` で飛ぶ先は `resume` ではありません。`pchl` の形では、`XTHL` より前に HL へ入れた値を表のアドレスとみなしません。

#### ROM に置いたスタックと RAM に置いた飛び先

RAM を確かめる前の起動処理は、RAM のスタックを使えません。そこで SP を ROM の中の語の並びに向け、`RET` で 1 つ目の語へ飛びます（`rom-stack`）。飛んだ先も `RET` で終わり、次の語へ進みます。次は、リセットの直後にこの形を使う例です。

```asm
    DI
    LXI  SP, chain      ; SP を ROM の中へ向ける
    RET                 ; step1 へ
chain:
    dw   step1, step2   ; 戻り先の並び
step1:
    XRA  A
    RET                 ; step2 へ
step2:
    LXI  SP, 0x8100     ; RAM を確かめたら、ふつうのスタックにする
    JMP  step2
```

`LXI SP` と `RET` の間に `PUSH` や `CALL` があれば、この形とはみなしません。積めば SP の指す先がずれるからです。

`LHLD ram` のあと HL を変えずに `PCHL` するときは、`ram` に書いた値が表のアドレスではなく飛び先そのものです（`pchl-ram`）。状態機械の「次の状態」の置き場所によくある形で、`ram` へ `LXI H, nn` → `SHLD ram` で書く `nn` を飛び先にします。`SHLD` の値は、HL を変えずに `SHLD` まで届く `LXI H` のものだけを採ります（別の RAM へ書いた値は混ぜません）。

### 追えないもの

* `PCHL` の飛び先で、`--auto-entry` が見つけられないもの
* 割り込みの入口（基板の配線で決まる `RST n`）
* `SPHL` → `RET` のように、飛び先が実行時のスタックで決まるもの

これらは `-e` か設定ファイルの `entry` で指定してください。

### 追えなかった分岐先の報告

分岐先を読めなかったときは、`# unresolved:` の行で報告します。

```
# unresolved: 0x2000
# unresolved: branch targets above could not be decoded.
# unresolved: a ROM file may be missing from bins, or an entry is wrong.
data = [
    ...
```

**出たら、飛び先を確かめる合図です。** いちばん多い原因は、`bins` に ROM ファイルを書き忘れたことです。上の例なら、`0x2000` に置くはずのファイルが足りていません。

ただし、本物のコードが外へ飛ぶこともあります。拡張 ROM があるかを確かめてから飛ぶコードや、RAM に写して動かすコードです。エントリ（`-e` や `--auto-entry` で見つけたもの）がデータを指していて、データの中の「分岐」が外を指していることもあります。飛び先と、そこへ至る命令を見て判断してください。

最後のバイトが `HLT` のイメージでは、その次のアドレスが報告されます（`HLT` の後ろへ進むため）。
