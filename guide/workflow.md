# ROM 解析の流れ

> p8080 で ROM を読み解く**手順の通し例**です。各コマンドの詳細は [cli.md](cli.md)、設定ファイルは [config.md](config.md) を参照してください。

練習用の小さな ROM を作り、次の順に進めます。手元でそのまま再現できます。

1. 練習用 ROM を作る
2. `walk` でコードとデータを分ける
3. `disasm` で逆アセンブルして眺める
4. 分かったことを設定ファイルに書く（名前・コメント・表の形）
5. 組み直して、元の ROM と一致することを確かめる

実際の解析では、1 が手元の ROM ファイルに置き換わり、3〜5 を何度も繰り返します。

## 1. 練習用 ROM を作る

次のソースを `practice.asm` として保存します。1KB の ROM で、ゲームの状態で処理を切り替える表と、タスクを切り替える表を持っています。割り込みは `RST 7`（`0x0038`）で受ける作りです。

```asm
; 練習用 ROM（1KB）
FRAME:   EQU 0xC000         ; フレームカウンタ（RAM）
STATE:   EQU 0xC001         ; ゲームの状態 0-2
TASK:    EQU 0xC002         ; 実行するタスクの番号 0-2
INT_ON:  EQU 0xE000         ; 割り込み許可（書き込み）

        org 0x0000
        di
        lxi  sp, 0xC400
        jmp  main

        org 0x0018           ; RST 3: 直後に置いた表で分岐する
        add  a
        pop  h               ; 戻りアドレス = 表の先頭
        mov  e, a
        mvi  d, 0
        dad  d
        mov  e, m
        inx  h
        mov  d, m
        xchg
        pchl

        org 0x0038           ; RST 7: 割り込みの入口（基板が RST 7 を置く）
        push psw
        lda  FRAME
        inr  a
        sta  FRAME
        pop  psw
        ei
        ret

        org 0x0190
main:   mvi  a, 1
        sta  INT_ON
        ei
loop:   lxi  h, frame_end   ; 戻り先を積む
        push h
        lda  STATE
        rst  3
        dw   st_title, st_play, st_over
st_title:
        lxi  h, msg_press
        call print
        ret
st_play:
        call task_run
        ret
st_over:
        xra  a
        sta  STATE
        ret
frame_end:
        lda  FRAME
        ana  a
        jz   frame_end
        jmp  loop

print:  ret

task_run:
        lda  TASK
        add  a
        mov  e, a
        mvi  d, 0
        lxi  h, task_tbl
        dad  d
        mov  e, m
        inx  h
        mov  d, m
        xchg
        pchl
task_tbl:
        dw   task_player, task_foe, task_sound

        org 0x0200
task_player:
        ret
task_foe:
        ret
task_sound:
        lxi  h, snd_tbl
        ret

        org 0x0300
msg_press:
        db   "PRESS START", 0
snd_tbl:
        db   4
        dw   song0
        db   0
        db   6
        dw   song1
        db   0
song0:  db   0x10, 0x12, 0x14, 0x15, 0x17, 0x19, 0x1B, 0x1C, 0xFF
song1:  db   0x20, 0x1E, 0x1C, 0x1B, 0x19, 0x17, 0xFF
```

1KB にそろえてアセンブルします。ここから先は、このソースを見ずに `practice.bin` だけを読み解く想定です。

```bash
p8080 asm -f practice.asm -o practice.bin -s 1024
```

## 2. コードとデータを分ける

`walk` は、エントリポイントから制御の流れを追い、たどり着けなかった範囲をデータとして出します。リセット（`0x0000`）からは自動で追うので、割り込みの入口 `RST7` を `-e` で足します。

```bash
p8080 walk -i practice.bin -e RST7
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

`0x01AB` 以降がほとんどデータになっています。原因は `RST 3` です。`0x0018` の処理は直後の表を使って飛ぶので、飛び先は実行するまで分かりません。そのうえ `walk` は `RST` を普通の呼び出しとして扱うので、直後の表（`0x019E` から）を命令として読み進めてしまいます。

`--auto-entry` を付けると、こうした分岐の定型の書き方を探して、表から飛び先を読みます。

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

`entry =` の上にある 4 行が finding lines で、見つけた分岐の形を 1 件ずつ示しています。

* `push-return`: `0x0196` で積んだ戻り先 `0x01B4`
* `rst-vector`: `0x019D` の `RST 3` の飛び先（3 × 8 = `0x0018`）
* `inline-after-rst`: `RST 3` の直後の表（`0x019E`）にある 3 つの飛び先
* `pchl`: `PCHL` で使う表（`0x01CF`）にある 3 つの飛び先

データとして残ったのは、2 つの表と、文字列・曲のデータ、あいだの空き（`0x00`）です。この出力を設定ファイルとして保存します。

```bash
p8080 walk -i practice.bin -e RST7 --auto-entry > practice_cfg.py
```

> **finding lines は確認してください。** 誤ったエントリポイントは、データをコードとして読ませてしまいます。確認できたものは、設定ファイルの `entry` に移しておきます（4 で行います）。

## 3. 逆アセンブルして眺める

```bash
p8080 disasm -i practice.bin -c practice_cfg.py
```

```
0x0190 3E 01        L_0190:  MVI a, 0x01
0x0192 32 00 E0              STA 0xE000
0x0195 FB                    EI
0x0196 21 B4 01     L_0196:  LXI h, 0x01B4
0x0199 E5                    PUSH h
0x019A 3A 01 C0              LDA 0xC001
0x019D DF                    RST 3
0x019E A4                    db 0xA4 ; [.]
0x019F 01                    db 0x01 ; [.]
0x01A0 AB                    db 0xAB ; [.]
0x01A1 01                    db 0x01 ; [.]
0x01A2 AF                    db 0xAF ; [.]
0x01A3 01                    db 0x01 ; [.]
0x01A4 21 00 03              LXI h, 0x0300
0x01A7 CD BE 01              CALL L_01BE
0x01AA C9                    RET
```

命令とデータは分かれましたが、まだ読みにくい状態です。

* アドレスが数字のまま（`0xC001` が何なのか、`0x0300` に何があるのか）
* 表が 1 バイトずつの `db` で、飛び先を指していることが分からない

## 4. 分かったことを設定ファイルに書く

読み進めて分かったことを、`practice_cfg.py` に書き足していきます。

**出力の `.asm` には手を入れません。** 逆アセンブルし直すと消えてしまうからです。名前もコメントも設定ファイルに書き、出力はいつでも作り直せるものとして扱います。

```python
# practice_cfg.py
entry = ["RST7", 0x0018, 0x01A4, 0x01AB, 0x01AF, 0x01B4, 0x0200, 0x0201, 0x0202]

data = [
    [0x0007, 0x0017],
    [0x0023, 0x0037],
    [0x0043, 0x018F],
    {"range": [0x019E, 0x01A3], "fmt": "w"},        # RST 3 直後の表
    {"range": [0x01CF, 0x01D4], "fmt": "w"},        # タスクの表
    {"range": [0x01D5, 0x01FF], "per_line": 16},
    {"range": [0x0206, 0x02FF], "per_line": 16},
    [0x0300, 0x030B],                               # "PRESS START", 0
    {"range": [0x030C, 0x0313], "fmt": "b w b"},    # 曲の表
    {"range": [0x0314, 0x0323], "per_line": 8},     # 楽譜
    {"range": [0x0324, 0x03FF], "per_line": 16},
]

labels = {
    0x0190: "Main",
    0x0196: "GameLoop",
    0x01A4: "StTitle",
    0x01AB: "StPlay",
    0x01AF: "StOver",
    0x01B4: "WaitFrame",
    0x01BE: "Print",
    0x01BF: "RunTask",
    0x01CF: "TaskTbl",
    0x0200: "TaskPlayer",
    0x0201: "TaskFoe",
    0x0202: "TaskSound",
    0x0300: "MsgPress",
    0x030C: "SongTbl",
    0x0314: "Song0",
    0x031D: "Song1",
    0x0018: {"name": "Rst3_Dispatch", "imm": False},
    0x0038: {"name": "Rst7_Interrupt", "imm": False},
}

equ = {
    0xC000: "Frame",
    0xC001: "State",
    0xC002: "Task",
    0xE000: {"w": "IntOn"},
}

comments = {
    0x0196: {"block": "メインループ: 状態ごとの処理へ分岐する"},
    0x019D: "直後の表で分岐する（戻ってこない）",
    0x030C: {"block": "曲の表: 速度, 楽譜, 未使用"},
}
```

使ったキーは次のとおりです。

| キー | 書いたこと |
| --- | --- |
| [`entry`](config.md#entry) | 2 で確認したエントリポイント。ラベルが付く |
| [`data`](config.md#data) | 表は `fmt` で `dw` に、長いバイト列は `per_line` でまとめる |
| [`labels`](config.md#labels) | ROM の中のアドレスの名前 |
| [`equ`](config.md#equ) | RAM と I/O のアドレスの名前 |
| [`comments`](config.md#comments) | アドレスでは表せない意味 |

`-n` を付けると、アドレスとバイト列の無い、組み直せる形で出ます。

```bash
p8080 disasm -i practice.bin -c practice_cfg.py -n
```

```asm
Frame: EQU 0xC000
State: EQU 0xC001
Task: EQU 0xC002
IntOn: EQU 0xE000
org 0x0000
    DI
    LXI sp, 0xC400
    JMP L_0190@Main
    ...
L_0190@Main:
    MVI a, 0x01
    STA IntOn
    EI
; メインループ: 状態ごとの処理へ分岐する
L_0196@GameLoop:
    LXI h, L_01B4@WaitFrame
    PUSH h
    LDA State
    RST 3 ; 直後の表で分岐する（戻ってこない）
    dw L_01A4@StTitle
    dw L_01AB@StPlay
    dw L_01AF@StOver
L_01A4@StTitle:
    LXI h, L_0300@MsgPress
    CALL L_01BE@Print
    RET
    ...
; 曲の表: 速度, 楽譜, 未使用
L_030C@SongTbl:
    db 0x04 ; [.]
    dw L_0314@Song0
    db 0x00 ; [.]
    db 0x06 ; [.]
    dw L_031D@Song1
    db 0x00 ; [.]
L_0314@Song0:
    db 0x10, 0x12, 0x14, 0x15, 0x17, 0x19, 0x1B, 0x1C
    db 0xFF
L_031D@Song1:
    db 0x20, 0x1E, 0x1C, 0x1B, 0x19, 0x17, 0xFF
```

RAM・I/O・ルーチン・表のアドレスが名前になり、表からは飛び先の名前が読めるようになりました。`STA IntOn` と `LDA State` のように、読み書きの向きに合わせて `equ` の名前が選ばれています（[config.md](config.md#equ)）。

## 5. 組み直して確かめる

出力をファイルに書き、アセンブルして、元の ROM と比べます。

```bash
p8080 disasm -i practice.bin -c practice_cfg.py -n -o practice_out.asm
p8080 asm -f practice_out.asm -o practice_out.bin -s 1024
python -c "import pathlib as p; print(p.Path('practice.bin').read_bytes() == p.Path('practice_out.bin').read_bytes())"
```

```
True
```

**`entry` / `data` / `labels` / `equ` / `comments` をどう書いても、出力を組み直すと元の ROM と一致します。** どれもバイト列を変えないからです。例外は 2 つあります。

* [`m1_handler`](config.md#m1_handler) で復号した ROM は、復号後のバイト列で組み直されるので一致しません。
* [`output`](config.md#output) で出力の形式を変えた場合は、その形式しだいです。

## 繰り返す

実際の解析では、3〜5 を何度も繰り返します。

* 読んで分かったことを設定ファイルに足し、逆アセンブルし直します。設定ファイルが大きくなったら[分割](config.md#設定ファイルを分割する)できます。
* データと思っていた範囲がコードだと分かったら、`entry` にアドレスを足して `walk` からやり直します。
* 割り込みの入口が分からないときは、`RST1`〜`RST7` のアドレスにコードらしいものがあるか `disasm` で眺め、あれば `entry` に足して確かめます。
* `walk` の出力に `# unresolved:` の行が出たら、`bins` に ROM ファイルを書き忘れていないか確かめてください（[cli.md](cli.md#追えなかった分岐先の報告)）。
