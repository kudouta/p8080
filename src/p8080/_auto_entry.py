#!/usr/bin/env python3

"""walk 用エントリポイントの自動抽出（ディスパッチ定型句カタログ方式）。

`PCHL` のような間接分岐で CFG トレースは必ず停止する。分岐先はジャンプ
テーブル内の値であり、静的には辿れない。本モジュールは**手書きアセンブラの
ディスパッチは書き方の定型句が有限個しかない**という前提に立ち、到達済み
コードからその定型句を認識してテーブル基底を逆算する。

ROM 全域からアドレステーブルらしき語の並びを総当たり探索する方式は採らない。
「ROM 内を指す」「命令境界を指す」といったテーブル側の性質は必要条件にすぎず、
スプライト定義や面データが偶然これを満たすため候補が数百件出て実用にならない。
テーブル側の性質は検証にのみ使い、候補生成はディスパッチャ側の定型句から行う。

`p8080 walk --auto-entry` から利用する。
"""

import re

from p8080.walk import build_addr_map, classify_instruction, sweep_from, trace

# 逆アセンブラ出力に対するパターン
# 16 ビットアドレスの表記。`0x0120` と、disasm が label_names で名前を添えた
# `L_1240@MSG_TABLE` の両方を受ける。捕捉群は 1 つだけなので、どちらの綴りでも
# 同じ group 番号で 4 桁が取れる（呼び出し側の group 番号を変えずに済む）。
# 名前部分は `[\w.]+`。`.` は p8080 のラベルとして合法で、`StrA.D.1980` のような
# 名前が実際に書かれる（`\w` だけだとドットで切れて住所の取りこぼしが起きる）。
ADDR16 = r"(?:0x|L_)([0-9A-Fa-f]{4})(?:@[\w.]+)?"

#
# pz80 は Z80 の構文（`LD hl,nnnn` / `LD (nnnn),hl` / `JP (hl)` など）に当てていた。
# 8080 では同じ働きの命令が別のニーモニックになる（対応は docs/auto-entry-port.md）。
# 16 ビット即値のレジスタ対は Intel 表記の先頭レジスタ名（h / d / b）。
RE_LXI_IMM = re.compile(rf"^LXI\s+(h|d|b),\s*{ADDR16}$", re.I)
RE_LHLD = re.compile(rf"^LHLD\s+{ADDR16}$", re.I)
RE_SHLD = re.compile(rf"^SHLD\s+{ADDR16}$", re.I)
RE_MVI_A_IMM = re.compile(r"^MVI\s+a,\s*0x([0-9A-Fa-f]{2})$", re.I)
RE_STA = re.compile(rf"^STA\s+{ADDR16}$", re.I)
RE_PCHL = re.compile(r"^PCHL$", re.I)
RE_XTHL = re.compile(r"^XTHL$", re.I)
RE_POP_H = re.compile(r"^POP\s+h$", re.I)
RE_RST = re.compile(r"^RST\s+([0-7])$", re.I)
RE_LXI_H_IMM = re.compile(r"^LXI\s+h,\s*0x([0-9A-Fa-f]{4})$", re.I)
RE_LXI_SP = re.compile(rf"^LXI\s+sp,\s*{ADDR16}$", re.I)
# HL に値を入れる（HL を変える）命令
RE_WRITES_HL = re.compile(
    r"^(?:LXI\s+h,|LHLD\b|DAD\b|XCHG$|XTHL$|POP\s+h$|INX\s+h$|DCX\s+h$"
    r"|MOV\s+[hl],|MVI\s+[hl],|INR\s+[hl]$|DCR\s+[hl]$)",
    re.I,
)
# 無条件・条件付きのコール。group(1) がニーモニック、group(2) が飛び先の 4 桁
# （pz80 は group(1) が条件、group(2) が飛び先。番号をそろえてある）。
# `@名前` は省略可。disasm が label_names でラベルに名前を添えた出力も読めるようにする。
RE_CALL = re.compile(
    r"^(CALL|CNZ|CZ|CNC|CC|CPO|CPE|CP|CM)\s+L_([0-9A-Fa-f]{4})(?:@[\w.]+)?$", re.I
)

# 後方スライスの上限（命令数）。`_bases_near()` がテーブル基底の候補を拾うために
# 分岐地点から遡る距離で、実際は**基本ブロックの境界（無条件 RET / JP）で先に
# 止まる**（`_backward()` 参照）。つまりこれは暴走を防ぐ頭打ちでしかない。
#
# **24 に測定上の根拠は無い。** pz80 で Z80 の ROM 3 本を窓幅 1 まで狭めても、最終的な
# エントリ集合は変わらなかった。テーブル基底を積む `LXI H,nnnn` が分岐の直前に
# 来るためである。広げても候補が増えるだけで、絞り込みは後段（`in_rom` 判定と
# `MIN_TABLE`）が行うので、余裕を大きく取ってある。
BACK_WINDOW = 24
# テーブルとして採用する最小要素数
MIN_TABLE = 2
# コードらしさ判定で追う命令数
PLAUSIBLE_DEPTH = 8
# RST のベクタ先を「テーブル分岐か」判定するときに追う命令数。実物は
# `ADD A / POP H / MOV E,A / MVI D,0 / DAD D / MOV E,M / INX H /
# MOV D,M / XCHG / PCHL` の 10 命令（pz80 の Z80 版を 8080 に置き換えた形。
# 命令数は同じ）なので、少し余裕を持たせてある。
RST_BODY_WINDOW = 16
# `push-return` で「積んだ値が積まれたままか」を見る命令数
PUSH_RETURN_WINDOW = 8
# `LXI H,nn` の直後に来て nn をスタックへ積む命令と、そのときのパターン名
PUSH_RETURN_FORMS = {"PUSH H": "push-return", "XTHL": "xthl-return"}
# `rom-stack` で `LXI SP,nn` から `RET` まで追う命令数
ROM_STACK_WINDOW = 12
# スタックへ積む命令。`rom-stack` で `RET` より前にあれば、SP は戻り先の並びを指したまま
# ではなくなる（ROM には書けないので、そもそも積む前提のコードではない）
_PUSHES = (
    "PUSH",
    "CALL",
    "CNZ",
    "CZ",
    "CNC",
    "CC",
    "CPO",
    "CPE",
    "CP",
    "CM",
    "RST",
    "XTHL",
)


def _rst_vector(asm):
    """`RST n` の飛び先アドレスを返す。

    8080 は `RST 7` と番号で書き、飛び先は n × 8（User's Manual p.4-11）。
    pz80 の Z80 は `RST 0x38` とアドレスで書くので、オペランドをそのまま使っていた。
    計算は walk の `classify_instruction()` に任せ、RST の定義を 1 か所に保つ。

    Args:
        asm (str): 逆アセンブル済み命令文字列。
            例: "RST 7"

    Returns:
        int | None: 飛び先アドレス。例: 0x0038。
    """
    _continues, target = classify_instruction(asm)
    return target


class Finding:
    """1 件の抽出結果。

    Attributes:
        pattern (str): 認識した定型句の識別子。
        site (int): 定型句を検出したアドレス。
        base (int | None): ジャンプテーブルの基底アドレス。解決不能なら None。
        stride (int): テーブルの 1 要素のバイト数 (2=dw, 3=JMP 命令列)。
        targets (list[int]): 抽出したエントリポイント。
        note (str): 補足（解決不能な場合の理由など）。
    """

    def __init__(self, pattern, site, base=None, stride=2, targets=None, note=""):
        """Finding を初期化します。

        Args:
            pattern (str): 認識した定型句の識別子。
            site (int): 定型句を検出したアドレス。
            base (int | None): ジャンプテーブルの基底アドレス。テーブルの無い定型句は None。
            stride (int): テーブルの 1 要素のバイト数 (2=dw, 3=JMP 命令列)。
            targets (list[int] | None): 抽出したエントリポイント。None なら空のリスト。
            note (str): 補足（解決不能な場合の理由など）。
        """
        self.pattern = pattern
        self.site = site
        self.base = base
        self.stride = stride
        self.targets = targets or []
        self.note = note

    def format(self):
        """1 行の説明文を返す。

        テーブルが無い定型句（`rst-vector` / `sphl-ret`）でも、分岐先が分かって
        いれば `-> ...` を出します。以前は `note` だけを見ていたため
        `rst-vector` の行が `@0x0006` で終わり、ベクタアドレスが読めませんでした。

        Returns:
            str: `[pattern] @0xSITE table=0xBASE stride=N -> 0x.... ...` の形。テーブルが
                無ければ `[pattern] @0xSITE -> 0x.... 補足` の形。
        """
        if self.base is None:
            targets = " ".join(f"0x{t:04X}" for t in self.targets)
            tail = " ".join(
                x for x in (f"-> {targets}" if targets else "", self.note) if x
            )
            return f"[{self.pattern}] @0x{self.site:04X} {tail}"
        targets = " ".join(f"0x{t:04X}" for t in self.targets)
        return (
            f"[{self.pattern}] @0x{self.site:04X} table=0x{self.base:04X} "
            f"stride={self.stride} -> {targets}"
        )

    def __repr__(self):
        """デバッグ表示用の文字列を返す。

        Returns:
            str: `<Finding ...>` の形。中身は `format()` と同じ。
        """
        return f"<Finding {self.format()}>"


class AutoEntry:
    """ディスパッチ定型句からエントリポイントを反復抽出する。

    Args:
        data (bytes | list[int]): ROM イメージ。
        start (int): ロードアドレス。valid_ranges 指定時は 0 基点として扱う。
        m1_handler (callable | None): M1サイクル復号ハンドラー。
        valid_ranges (list[list[int]] | None): 有効なアドレス範囲 [[start, end], ...]。
    """

    def __init__(self, data, start=0, m1_handler=None, valid_ranges=None):
        """AutoEntry を初期化し、ROM 全体を先頭から走査した命令マップを作ります。"""
        self.data = list(data)
        self.size = len(self.data)
        self.start = 0 if valid_ranges is not None else start
        self.valid_ranges = valid_ranges

        self.m1_handler = m1_handler
        self.amap = build_addr_map(self.data, start, m1_handler, valid_ranges)
        self.order = sorted(self.amap)
        self.index = {a: i for i, a in enumerate(self.order)}

        # 直後へ戻らないと分かった命令のアドレス（RST 直後にテーブルを埋め込む形）。
        # `trace()` に渡して、テーブルのバイトをコードにしないために使う。
        # `run()` のあと呼び出し側が読む（`__main__` が `walk()` へ渡す）。
        self.no_fallthrough = set()

    # ------------------------------------------------------------------ 基本部品

    def in_rom(self, addr):
        """アドレスが ROM 範囲（かつ valid_ranges 内）かを返す。

        Args:
            addr (int): 調べるアドレス。

        Returns:
            bool: ROM のある範囲なら True。
        """
        if not (self.start <= addr < self.start + self.size):
            return False
        if self.valid_ranges is None:
            return True
        return any(r[0] <= addr <= r[1] for r in self.valid_ranges)

    def byte(self, addr):
        """アドレスの生バイトを返す。範囲外なら None。

        Args:
            addr (int): 読むアドレス。

        Returns:
            int | None: そのアドレスのバイト。ROM の無いアドレスなら None。
        """
        if not self.in_rom(addr):
            return None
        return self.data[addr - self.start]

    def resweep(self, addr):
        """`amap` に無い分岐先から走査し直して命令マップを返す。

        先頭からの走査が作った命令境界に分岐先が乗らないことがあります
        （詳細は `walk.sweep_from()`）。これを渡さないと追跡が静かに止まり、
        到達できるコードをデータと誤判定します。

        Args:
            addr (int): 走査を始めるアドレス。

        Returns:
            dict[int, dict]: アドレスをキーとする逆アセンブル結果。
        """
        if not self.in_rom(addr):
            return {}
        found = sweep_from(self.data, addr, self.start, self.m1_handler)
        return {a: p for a, p in found.items() if self.in_rom(a)}

    def trace(self, entries):
        """CFG トレースし (到達バイト集合, 命令先頭集合) を返す。

        `resweep` で見つかった命令は `self.amap` に加わるため、
        アドレス順の索引を作り直します。

        Args:
            entries (iterable[int]): 追跡を始めるエントリポイント。

        Returns:
            tuple[set[int], set[int]]: (到達したバイトのアドレス, 命令の先頭アドレス)。
        """
        before = len(self.amap)
        result = trace(
            self.amap, entries, resweep=self.resweep, stop_after=self.no_fallthrough
        )
        if len(self.amap) != before:
            self.order = sorted(self.amap)
            self.index = {a: i for i, a in enumerate(self.order)}
        return result

    def _ensure_mapped(self, addr):
        """`amap` に無いアドレスなら、そこから走査し直して埋める。

        **先頭からの走査が作った命令境界に、分岐先が乗るとは限りません**
        （`walk.sweep_from()`）。`trace()` は `resweep` でこれを回避しますが、
        テーブルの読み出しは `scan()` の中で `amap` を直接引くため、同じ手当てが
        必要です。無いまま `False` を返すと、**実在するテーブルが不成立になります**。

        Args:
            addr (int): 対象アドレス。

        Returns:
            bool: `amap` に載っていれば True。
        """
        if addr in self.amap:
            return True
        if not self.in_rom(addr):
            return False
        before = len(self.amap)
        for a, p in self.resweep(addr).items():
            self.amap.setdefault(a, p)
        if len(self.amap) != before:
            self.order = sorted(self.amap)
            self.index = {a: i for i, a in enumerate(self.order)}
        return addr in self.amap

    def plausible(self, addr, depth=PLAUSIBLE_DEPTH):
        """addr からコードとして素直に復号できるかを返す。

        Args:
            addr (int): 調べるアドレス。
            depth (int): 先へ読む命令の数の上限。この数を読み切っても True。

        Returns:
            bool: ROM 内で、`RET` / `JMP` などで終わるか depth 命令まで続けて読めれば True。
        """
        if not self.in_rom(addr) or not self._ensure_mapped(addr):
            return False
        a = addr
        for _ in range(depth):
            p = self.amap.get(a)
            if p is None:
                return False
            continues, _target = classify_instruction(p["asm"])
            if not continues:
                return True  # RET/JMP で素直に終端した
            a += len(p["opcode"])
            if not self.in_rom(a):
                return False
        return True

    def _consistent(self, addr, code, heads):
        """既に確定したコードの命令途中に着地していないかを返す。

        Args:
            addr (int): 調べるアドレス（テーブルの要素が指す先など）。
            code (set[int]): 到達済みのバイトのアドレス。
            heads (set[int]): 到達済みの命令の先頭アドレス。

        Returns:
            bool: 命令の途中でなければ True。
        """
        return not (addr in code and addr not in heads)

    def read_table(self, base, code, heads):
        """base から始まるジャンプテーブルを読み出す。

        dw 形式 (stride 2) と JMP 命令の並び (stride 3) の両方を扱う。

        Args:
            base (int): テーブル基底アドレス。
            code (set[int]): 現時点で確定している到達バイト集合。
            heads (set[int]): 現時点で確定している命令先頭集合。

        Returns:
            tuple[list[int], int]: (エントリ列, stride)。不成立時は ([], 0)。
        """
        if not self.in_rom(base):
            return [], 0

        # JMP nnnn の並び: テーブル自体が命令なので、スロット先頭をエントリにする
        # （0xC3 は Z80 の JP nn と同じオペコードなので、判定は pz80 のまま使える）
        if self.byte(base) == 0xC3:
            slots = []
            a = base
            while self.in_rom(a + 2) and self.byte(a) == 0xC3:
                target = self.byte(a + 1) | self.byte(a + 2) << 8
                if not self.plausible(target):
                    break
                if not self._consistent(target, code, heads):
                    break
                slots.append(a)
                a += 3
            return (slots, 3) if len(slots) >= MIN_TABLE else ([], 0)

        # dw LABEL の並び
        words = []
        a = base
        targets = self._branch_targets(heads)
        # テーブルより後ろを指す分岐先の最小値。そこに達したらテーブルの終わり。
        # **テーブルは自分の分岐先に食い込めない。** ハンドラがテーブルの直後に
        # 並ぶ配置（RST 直後に埋め込むテーブルで多い）では、この規則が無いと
        # ハンドラのバイトを語として読み続ける。
        #
        # **前を指す分岐先を混ぜてはいけない。** 混ぜると `a >= forward_min` が
        # 初回から成立してテーブルを 1 件で打ち切る。
        forward_min = None
        while self.in_rom(a + 1):
            if forward_min is not None and a >= forward_min:
                break
            # **到達したコードの分岐先から先は表にしない。** 表のすぐ後ろに CALL で
            # 呼ばれるルーチンが続く配置では、以前はその先頭の 2 バイト（`LXI H` など）を
            # 表の要素として読み、その先のデータまでコードとして読んでいた。「到達した
            # コードのバイト」では広すぎる: CALL や RST の直後の表は、`no_fallthrough` が
            # 効くまで、直前の命令から続くコードとして読まれている
            if a != base and (a in targets or a + 1 in targets):
                break
            w = self.byte(a) | self.byte(a + 1) << 8
            if w == 0:
                # 0x0000 はリセットベクタなので `plausible()` を通ってしまうが、
                # ディスパッチテーブルの要素としては詰め物である。テーブルの
                # 末尾に 0 埋めが続く配置で、それを要素として数えてしまう。
                break
            # 直前と同じ語なら打ち切る（0 埋めなどのデータ）。
            #
            # **離れた位置での重複は許す。** ディスパッチテーブルでは同じハンドラを
            # 複数の添字に割り当てるのが普通である。以前は `w in words` で
            # 「一度でも出た語」を打ち切っていたため、19 件のテーブルが 9 件目
            # （3 件目と同じハンドラ）で切れていた。
            if words and w == words[-1]:
                break
            if not self.plausible(w):
                break
            if not self._consistent(w, code, heads):
                break
            words.append(w)
            if w > base and (forward_min is None or w < forward_min):
                forward_min = w
            a += 2
        return (words, 2) if len(words) >= MIN_TABLE else ([], 0)

    def _branch_targets(self, heads):
        """到達した命令の分岐先（JMP・CALL・RST・条件付きのものを含む）を返す。

        `heads` が変わらない間は作り直さない（`read_table()` は 1 回の走査で何度も呼ぶ）。

        Args:
            heads (set[int]): 到達済みの命令の先頭アドレス。

        Returns:
            set[int]: 分岐先のアドレス。
        """
        # heads そのものを持っておく（id() だけだと、解放された別の集合と取り違えうる）
        cached = getattr(self, "_targets_heads", None)
        if cached is not heads or self._targets_len != len(heads):
            targets = set()
            for a in heads:
                p = self.amap.get(a)
                if p is None:
                    continue
                _continues, target = classify_instruction(p["asm"])
                if target is not None:
                    targets.add(target)
            self._targets_heads, self._targets_len, self._targets = (
                heads,
                len(heads),
                targets,
            )
        return self._targets

    def _backward(self, site, heads, window=BACK_WINDOW):
        """site の直前の到達済み命令を新しい順に返す（基本ブロック内で打ち切る）。

        Args:
            site (int): 起点の命令のアドレス。
            heads (set[int]): 到達済みの命令の先頭アドレス。
            window (int): 遡る命令の数の上限。

        Returns:
            list[dict]: 命令（`amap` の値）を、site に近い順に並べたもの。
        """
        i = self.index.get(site)
        if i is None:
            return []
        res = []
        j = i - 1
        while j >= 0 and len(res) < window:
            a = self.order[j]
            j -= 1
            if a not in heads:
                continue
            p = self.amap[a]
            continues, _target = classify_instruction(p["asm"])
            if not continues:
                break  # 無条件 RET/JMP/PCHL を越えたら別ブロック
            res.append(p)
        return res

    # ------------------------------------------------- テーブル基底の逆算パターン

    def _bases_from_ram(self, ram):
        """RAM アドレス ram に書き込まれる定数ポインタを ROM 全体から探す。

        `LXI H,mmmm` → `SHLD ram` 形式と、
        `MVI A,LL` → `STA ram` / `MVI A,HH` → `STA ram+1` のバイト分割形式に対応。

        Args:
            ram (int): ポインタを置く RAM のアドレス。

        Returns:
            set[int]: 書き込まれる値（テーブル基底の候補）。
        """
        bases = set()
        lo = hi = None
        for i, a in enumerate(self.order):
            asm = self.amap[a]["asm"]

            m = RE_SHLD.match(asm)
            if m and int(m.group(1), 16) == ram:
                # **SHLD まで HL を変えずに届く `LXI H` の値だけを採る**（6 命令前まで）。
                # 以前は 6 命令前までの `LXI H` をすべて採っていたため、
                # `LXI H,a / SHLD ram1 / LXI H,b / SHLD ram2` で、別の RAM（ram1）へ
                # 書いた a まで ram2 の値としていた。一方、「直前の 1 つだけ」では、
                # `LXI H,a / JMP store / LXI H,b / store: SHLD ram` のように、2 つの道から
                # 同じ SHLD へ届く値の片方を落とす
                for j in range(i - 1, max(-1, i - 7), -1):
                    prev = self.amap[self.order[j]]["asm"].strip()
                    m2 = RE_LXI_IMM.match(prev)
                    if (
                        m2
                        and m2.group(1).lower() == "h"
                        and self._hl_reaches(self.order[j], a)
                    ):
                        bases.add(int(m2.group(2), 16))

            m = RE_STA.match(asm)
            if m:
                dst = int(m.group(1), 16)
                if dst in (ram, ram + 1):
                    for j in range(max(0, i - 3), i):
                        m2 = RE_MVI_A_IMM.match(self.amap[self.order[j]]["asm"])
                        if not m2:
                            continue
                        if dst == ram:
                            lo = int(m2.group(1), 16)
                        else:
                            hi = int(m2.group(1), 16)
        if lo is not None and hi is not None:
            bases.add(hi << 8 | lo)
        return bases

    def _hl_reaches(self, start, site, window=8):
        """start の命令で HL に入れた値が、HL を変えずに site まで届くかを返す。

        start の次の命令から順に進む。無条件の `JMP` は飛び先へ進み、条件付きの分岐は
        そのまま次の命令へ進む（飛ばない道をたどる）。HL を変える命令か、`RET` などの
        戻らない命令に当たったら届かない。

        Args:
            start (int): `LXI H` の命令のアドレス。
            site (int): `SHLD` の命令のアドレス。
            window (int): 進む命令の数の上限。

        Returns:
            bool: 届けば True。
        """
        p = self.amap.get(start)
        if p is None:
            return False
        a = start + len(p["opcode"])
        for _ in range(window):
            if a == site:
                return True
            p = self.amap.get(a)
            if p is None:
                return False
            asm = p["asm"].strip()
            if RE_WRITES_HL.match(asm):
                return False
            continues, target = classify_instruction(asm)
            if not continues:
                if target is None or not asm.upper().startswith("JMP"):
                    return False
                a = target
                continue
            a += len(p["opcode"])
        return False

    def _bases_near(self, site, heads):
        """site の直前から、テーブル基底になりうる定数を集める。

        **`XTHL` より前に HL へ入れた値は除く。** `XTHL` で HL の値はスタックへ
        移り、HL にはスタックの先頭が入る。`LXI H,resume / XTHL / PUSH D / PCHL` は
        戻り先を積んで DE を呼ぶ形で、これを除かないと `resume` のコードを表として
        読み、空き領域（0xFF = `RST 7`）を指す語から `rst-vector` が大量に出る。
        積んだ戻り先のほうは `_p_push_return()` が `xthl-return` として拾う。

        Args:
            site (int): 分岐する命令（`PCHL` など）のアドレス。
            heads (set[int]): 到達済みの命令の先頭アドレス。

        Returns:
            set[int]: テーブル基底の候補。
        """
        bases = set()
        hl_swapped = False
        for p in self._backward(site, heads):
            asm = p["asm"]

            if RE_XTHL.match(asm):
                hl_swapped = True
                continue

            m = RE_LXI_IMM.match(asm)
            if m and not (hl_swapped and m.group(1).lower() == "h"):
                v = int(m.group(2), 16)
                if self.in_rom(v):
                    bases.add(v)

            m = RE_LHLD.match(asm)
            if m and not hl_swapped:
                ram = int(m.group(1), 16)
                if self.in_rom(ram):
                    bases.add(ram)  # ROM 内なら直接テーブル
                else:
                    bases |= self._bases_from_ram(ram)  # RAM 経由の間接
        return bases

    # ---------------------------------------------------------- 定型句カタログ

    def scan(self, code, heads):
        """到達済みコードからディスパッチ定型句を探し Finding のリストを返す。

        Args:
            code (set[int]): 到達済みのバイトのアドレス。
            heads (set[int]): 到達済みの命令の先頭アドレス。

        Returns:
            list[Finding]: 見つかった定型句。
        """
        findings = []
        findings += self._p_pchl(code, heads)
        findings += self._p_push_ret(code, heads)
        findings += self._p_sphl_ret(code, heads)
        findings += self._p_rom_stack(code, heads)
        findings += self._p_inline_after_call(code, heads)
        findings += self._p_inline_after_rst(code, heads)
        findings += self._p_push_return(code, heads)
        findings += self._p_rst(code, heads)
        return findings

    def _emit(self, pattern, site, bases, code, heads):
        """基底候補群からテーブルを読み出して Finding 化する。

        Args:
            pattern (str): 定型句の識別子。
            site (int): 定型句を検出したアドレス。
            bases (iterable[int]): テーブル基底の候補。
            code (set[int]): 到達済みのバイトのアドレス。
            heads (set[int]): 到達済みの命令の先頭アドレス。

        Returns:
            list[Finding]: テーブルとして読めた候補ごとに 1 件。
        """
        out = []
        for b in sorted(bases):
            targets, stride = self.read_table(b, code, heads)
            if targets:
                out.append(Finding(pattern, site, b, stride, targets))
        return out

    def _p_pchl(self, code, heads):
        """PCHL 直前のテーブル引き（pz80 の jp-indirect）。

        Args:
            code (set[int]): 到達済みのバイトのアドレス。
            heads (set[int]): 到達済みの命令の先頭アドレス。

        Returns:
            list[Finding]: 見つかった `pchl`。
        """
        out = []
        for a in sorted(heads):
            if not RE_PCHL.match(self.amap[a]["asm"]):
                continue
            direct = self._pchl_ram_targets(a, code, heads)
            if direct is not None:
                if direct:
                    out.append(Finding("pchl-ram", a, targets=direct))
                continue
            out += self._emit("pchl", a, self._bases_near(a, heads), code, heads)
        return out

    def _pchl_ram_targets(self, site, code, heads):
        """`LHLD ram` → `PCHL` で、RAM に置いた飛び先へそのまま飛ぶ形なら、飛び先を返す。

        HL に最後に値を入れた命令が `LHLD ram`（ram は RAM）で、そのあと HL を変えずに
        `PCHL` するなら、ram に書いた値は**表の先頭ではなく飛び先そのもの**である。
        状態機械の「次の状態」の置き場所によくある形で、`LHLD ram / PCHL` の ram へ
        `LXI H,next / SHLD ram` などと書く。以前は書いた値を表の先頭として読み、
        飛び先のコードを語の並びとして読んでいた。

        Args:
            site (int): `PCHL` のアドレス。
            code (set[int]): 到達済みのバイトのアドレス。
            heads (set[int]): 到達済みの命令の先頭アドレス。

        Returns:
            list[int] | None: この形なら、コードとして読める飛び先（昇順。空のこともある）。
                この形でなければ None（表を引く `pchl` として扱う）。
        """
        for p in self._backward(site, heads):
            asm = p["asm"].strip()
            if not RE_WRITES_HL.match(asm):
                continue
            m = RE_LHLD.match(asm)
            if not m or self.in_rom(int(m.group(1), 16)):
                return None
            values = self._bases_from_ram(int(m.group(1), 16))
            return sorted(
                v
                for v in values
                if self.in_rom(v)
                and self.plausible(v)
                and self._consistent(v, code, heads)
            )
        return None

    def _p_push_ret(self, code, heads):
        """PUSH H の直後の RET で分岐する形式。

        Args:
            code (set[int]): 到達済みのバイトのアドレス。
            heads (set[int]): 到達済みの命令の先頭アドレス。

        Returns:
            list[Finding]: 見つかった `push-ret`。
        """
        out = []
        for a in sorted(heads):
            if self.amap[a]["asm"].strip().upper() != "PUSH H":
                continue
            nxt = a + len(self.amap[a]["opcode"])
            # PUSH H と RET の間に 2 命令まで許容
            for _ in range(3):
                p = self.amap.get(nxt)
                if p is None or nxt not in heads:
                    break
                if p["asm"].strip().upper() == "RET":
                    out += self._emit(
                        "push-ret", a, self._bases_near(a, heads), code, heads
                    )
                    break
                continues, _target = classify_instruction(p["asm"])
                if not continues:
                    break
                nxt += len(p["opcode"])
        return out

    def _p_sphl_ret(self, code, heads):
        """SPHL + RET によるタスク再開（pz80 の sp-ret）。

        復帰先は実行時のスタック内容なので静的には解決できない。
        取りこぼしの可能性がある箇所として報告のみ行う。

        Args:
            code (set[int]): 到達済みのバイトのアドレス。
            heads (set[int]): 到達済みの命令の先頭アドレス。

        Returns:
            list[Finding]: 見つかった `sphl-ret`（分岐先は空で、理由を note に書く）。
        """
        out = []
        for a in sorted(heads):
            if self.amap[a]["asm"].strip().upper() != "SPHL":
                continue
            nxt = a + len(self.amap[a]["opcode"])
            for _ in range(12):
                p = self.amap.get(nxt)
                if p is None or nxt not in heads:
                    break
                if p["asm"].strip().upper() == "RET":
                    out.append(
                        Finding(
                            "sphl-ret",
                            a,
                            # 出力は英語で揃える。他の CLI メッセージ・ヘルプ・
                            # エラーはすべて英語なので、ここだけ日本語だと
                            # 日本語を読まない利用者が面食らう。
                            note=(
                                "task resume: return address depends on the "
                                "runtime stack; cannot be resolved statically"
                            ),
                        )
                    )
                    break
                continues, _target = classify_instruction(p["asm"])
                if not continues:
                    break
                nxt += len(p["opcode"])
        return out

    def _p_rom_stack(self, code, heads):
        """SP を ROM の中に向けて `RET` する形（スタックを ROM に置いた戻り先の並び）。

        RAM を確かめる前の起動処理は、RAM のスタックを使えない。そこで
        `LXI SP,nn`（nn は ROM の中）で SP を ROM の中の語の並びに向け、`RET` で
        1 つ目の語へ飛ぶ。飛んだ先の処理も `RET` で終わり、次の語へ進む。nn からの
        語の並びは、そのまま飛び先の表になる。たとえばリセット直後の
        `DI / LXI SP,chain / RET` で、chain に語が並び、1 つ目の飛び先が表の直後から
        始まる。

        `LXI SP,nn` から `RET` までの間に積む命令（`PUSH`・`CALL`・`RST` など）が
        あれば採らない。積めば SP の指す先がずれ、ROM には書けないので、戻り先の
        並びとして使うコードではない。表の終わりは `read_table()` の規則で決める
        （表の後ろを指す飛び先の最小値に達したら終わり。上の例では 1 つ目の飛び先）。

        Args:
            code (set[int]): 到達済みのバイトのアドレス。
            heads (set[int]): 到達済みの命令の先頭アドレス。

        Returns:
            list[Finding]: 見つかった `rom-stack`。
        """
        out = []
        for a in sorted(heads):
            m = RE_LXI_SP.match(self.amap[a]["asm"].strip())
            if not m:
                continue
            base = int(m.group(1), 16)
            if not self.in_rom(base):
                continue
            nxt = a + len(self.amap[a]["opcode"])
            for _ in range(ROM_STACK_WINDOW):
                p = self.amap.get(nxt)
                if p is None or nxt not in heads:
                    break
                mnemonic = p["asm"].strip().split()[0].upper()
                if mnemonic == "RET":
                    out += self._emit("rom-stack", a, {base}, code, heads)
                    break
                if mnemonic in _PUSHES:
                    break
                continues, _target = classify_instruction(p["asm"])
                if not continues:
                    break
                nxt += len(p["opcode"])
        return out

    def _p_inline_after_call(self, code, heads):
        """CALL 直後にテーブルを埋め込む形式。

        呼ばれる側が POP H / POP D で戻りアドレスを取り出していれば、
        CALL 命令の直後がテーブル本体になる。

        Args:
            code (set[int]): 到達済みのバイトのアドレス。
            heads (set[int]): 到達済みの命令の先頭アドレス。

        Returns:
            list[Finding]: 見つかった `inline-after-call`。
        """
        pop_routines = {
            a
            for a in heads
            if self.amap[a]["asm"].strip().upper() in ("POP H", "POP D")
        }
        if not pop_routines:
            return []

        out = []
        for a in sorted(heads):
            m = RE_CALL.match(self.amap[a]["asm"])
            if not m:
                continue
            if int(m.group(2), 16) not in pop_routines:
                continue
            base = a + len(self.amap[a]["opcode"])
            out += self._emit("inline-after-call", a, {base}, code, heads)
        return out

    def _rst_dispatches_via_table(self, vec, heads):
        """RST のベクタ先が「戻りアドレスを取り出してテーブルで飛ぶ」形かを返す。

        `inline-after-call` と同じ判定をベクタ先に当てはめたもの。`POP H`
        で戻りアドレスを取り、`PCHL` に至れば、その RST の
        直後がテーブル本体になる。

        Args:
            vec (int): RST のベクタアドレス。
            heads (set[int]): 到達済みの命令先頭集合。

        Returns:
            bool: テーブル分岐なら True。
        """
        a = vec
        popped = False
        for _ in range(RST_BODY_WINDOW):
            p = self.amap.get(a)
            if p is None or a not in heads:
                return False
            if RE_POP_H.match(p["asm"].strip()):
                popped = True
            if RE_PCHL.match(p["asm"].strip()):
                return popped
            continues, _target = classify_instruction(p["asm"])
            if not continues:
                return False
            a += len(p["opcode"])
        return False

    def _p_inline_after_rst(self, code, heads):
        """RST 直後にテーブルを埋め込む形式。

        `classify_instruction()` は RST を「呼んで次の命令へ戻る」ものとして
        扱うため、直後のテーブルを命令として読んでしまう。ベクタ先が戻りアドレスを
        取り出す形なら戻ってこないので、`no_fallthrough` に site を積んで
        追跡側に伝える（`trace()` の `stop_after`）。これでテーブルのバイトは
        コードにならず、自然にデータへ落ちる。

        Args:
            code (set[int]): 到達済みのバイトのアドレス。
            heads (set[int]): 到達済みの命令の先頭アドレス。

        Returns:
            list[Finding]: 見つかった `inline-after-rst`。
        """
        out = []
        verdict = {}
        for a in sorted(heads):
            if not RE_RST.match(self.amap[a]["asm"].strip()):
                continue
            vec = _rst_vector(self.amap[a]["asm"])
            if vec not in verdict:
                verdict[vec] = self.in_rom(vec) and self._rst_dispatches_via_table(
                    vec, heads
                )
            if not verdict[vec]:
                continue
            # **テーブルが読めたかに関わらず積む。** 戻ってこないことはベクタ先の
            # 形だけで決まる。成否に連動させると循環する: テーブルを読むには
            # 直後のバイトがコードでない必要があり、コードでなくするには
            # 「戻らない」と決める必要がある。pz80 では実際にこれで 2 つのテーブルが
            # 読めなかった（先頭の語が、命令として読まれたバイトの途中を指す）。
            self.no_fallthrough.add(a)
            base = a + len(self.amap[a]["opcode"])
            out += self._emit("inline-after-rst", a, {base}, code, heads)
        return out

    def _p_push_return(self, code, heads):
        """`LXI H, nn` の直後に `PUSH H` がある形（戻り先をスタックへ積む）。

        `push-ret`（`PUSH H` の直後に `RET`）とは別の形で、積んでから途中に
        分岐を挟み、あとで `RET` で戻る。積んだ `nn` がそのまま戻り先になる。

        **積んだ値がアドレスとは限りません。** pz80 で測った Z80 の実 ROM には、
        8080 の命令で書けば

            LXI H, 0x0100 / PUSH H / POP H / DCX H / MOV A,H / ORA L / JNZ …

        という遅延ループがあり、この 0x0100 は**回数**です。`plausible()` だけでは
        通ってしまい（コードとして素直に読めてしまう）、pz80 では実 ROM 2 本で
        誤検出しました。すぐ `POP` で戻しているかを見て弾きます。
        **積んだ値を戻すなら、それは戻り先ではない。**

        それでも誤検出の余地は残るため、根拠を `# auto-entry:` の行に出して
        利用者が判断できるようにしている。

        **`PUSH H` の代わりに `XTHL` でも積める**（`xthl-return`）。`XTHL` は
        スタックの先頭と HL を入れ替えるので、`LXI H,nn / XTHL` は、先に積んで
        あった値を HL へ戻しつつ `nn` を積む。`LXI H,resume / XTHL / PUSH D / PCHL` は
        戻り先を積んで DE を呼ぶ形。
        確認は `push-return` と同じ（コードらしさ、すぐ `POP` で戻さないこと）。

        Args:
            code (set[int]): 到達済みのバイトのアドレス。
            heads (set[int]): 到達済みの命令の先頭アドレス。

        Returns:
            list[Finding]: 見つかった `push-return` と `xthl-return`。
        """
        out = []
        for a in sorted(heads):
            m = RE_LXI_H_IMM.match(self.amap[a]["asm"].strip())
            if not m:
                continue
            nxt = a + len(self.amap[a]["opcode"])
            p = self.amap.get(nxt)
            if p is None or nxt not in heads:
                continue
            pattern = PUSH_RETURN_FORMS.get(p["asm"].strip().upper())
            if pattern is None:
                continue
            target = int(m.group(1), 16)
            if not (self.in_rom(target) and self.plausible(target)):
                continue
            if not self._pushed_value_is_kept(nxt + len(p["opcode"]), heads):
                continue
            out.append(Finding(pattern, a, targets=[target]))
        return out

    def _pushed_value_is_kept(self, after, heads):
        """積んだ値が積まれたまま残るか（すぐ `POP` で戻されないか）を返す。

        `POP` に当たったら False。無条件分岐・`RET`・テーブル分岐（`RST` を
        `no_fallthrough` に積んだもの）まで届いたら True。**戻り先として積んだなら、
        その先の `RET` で使われるので自分では戻さない**、という見分け方である。

        Args:
            after (int): `PUSH` の直後のアドレス。
            heads (set[int]): 到達済みの命令先頭集合。

        Returns:
            bool: 積まれたままなら True。
        """
        a = after
        for _ in range(PUSH_RETURN_WINDOW):
            p = self.amap.get(a)
            if p is None or a not in heads:
                return False
            if p["asm"].strip().upper().startswith("POP"):
                return False
            continues, _target = classify_instruction(p["asm"])
            if not continues or a in self.no_fallthrough:
                return True
            a += len(p["opcode"])
        return True

    def _p_rst(self, code, heads):
        """到達コード中に RST n が実在する場合のみベクタを採用する。

        Args:
            code (set[int]): 到達済みのバイトのアドレス。
            heads (set[int]): 到達済みの命令の先頭アドレス。

        Returns:
            list[Finding]: ベクタが ROM 内にある `rst-vector`。
        """
        out = []
        for a in sorted(heads):
            if not RE_RST.match(self.amap[a]["asm"]):
                continue
            vec = _rst_vector(self.amap[a]["asm"])
            if self.in_rom(vec):
                out.append(Finding("rst-vector", a, targets=[vec]))
        return out

    # ------------------------------------------------------------------- 反復

    def default_vectors(self):
        """初期エントリとして採用する固定ベクタを返す。

        8080 では開始アドレス（RESET）だけ。pz80 はコードらしければ Z80 の NMI
        （0x0066）も加えていたが、8080 には NMI が無い。

        **割り込みの入口は自動では加えない。** 8080 の割り込みは、INTR に応答して
        外部回路がデータバスに置く命令（普通は `RST n`）で受ける。どの RST が
        割り込みに使われるかは基板の配線で決まり、ROM の中には現れないので、
        利用者が `RST1` などのエントリとして与える。pz80 は到達したコードに
        IM 1 / IM 0 があれば 0x0038 を自分で足すが、8080 には割り込みモードを
        選ぶ命令が無く、ROM の中に手がかりが無い。
        コード中に `RST n` が実在する場合は `_p_rst()` が拾う。

        Returns:
            set[int]: 開始アドレスだけを入れた集合。
        """
        return {self.start}

    def run(self, seed_entries=None, max_iter=8):
        """不動点に達するまでエントリ抽出を反復する。

        Args:
            seed_entries (iterable[int] | None): 追加の初期エントリ。
                開始アドレス（RESET）は常に含まれる。
            max_iter (int): 最大反復回数。

        Returns:
            tuple[set[int], list[Finding]]: (エントリ集合, 抽出結果)。
        """
        entries = self.default_vectors() | set(seed_entries or ())

        findings = {}
        for _ in range(max_iter):
            code, heads = self.trace(entries)
            # 次の `trace()` の結果を変えるものは 2 つある。エントリが増えたか、
            # **`no_fallthrough` が増えたか**。後者を見ないと 1 回早く収束する。
            # 「戻らない RST」が増えると直後のバイトがコードでなくなり、そこで
            # 初めて読めるテーブルがある。pz80 では実 ROM でテーブル 2 個を落としていた。
            stops = len(self.no_fallthrough)
            new = set()
            for f in self.scan(code, heads):
                findings[(f.pattern, f.site, f.base)] = f
                new |= set(f.targets)
            if new <= entries and len(self.no_fallthrough) == stops:
                break
            entries |= new

        return entries, sorted(findings.values(), key=lambda f: (f.site, f.base or 0))
