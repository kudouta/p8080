#!/usr/bin/env python3

import re

from p8080 import disasm, i8080

# 後方互換のため walk 名前空間からも参照できるようにしておく
# （実体は _vectors.py。walk -> disasm -> _vectors の依存を一方向に保つため）
from p8080._vectors import VECTOR_ALIASES, parse_entry

__all__ = [
    "VECTOR_ALIASES",
    "address_set",
    "build_addr_map",
    "classify_instruction",
    "merge_ranges",
    "parse_entry",
    "sweep_from",
    "trace",
    "walk",
]

_RE_LABEL = re.compile(r"\bL_([0-9A-Fa-f]{4})\b")


def _build_flow_by_mnemonic():
    """命令表から「ニーモニック → flow」の対応を作る。

    Intel 表記では条件がニーモニックの一部（`jnz` / `cz` / `rpe`）なので、
    ニーモニックだけで flow が 1 つに決まる。念のため、同じニーモニックの命令に
    違う flow が付いていないかを確かめる（`mov` のように flow を持たない命令が、
    一部だけ flow を持つ場合も食い違いとして扱う）。

    Returns:
        dict: 大文字のニーモニックから flow への対応。flow を持たない命令は入らない。
            例: {"JMP": "jump", "JNZ": "jump-cc", "JP": "jump-cc", "CALL": "call",
                 "RET": "return", "PCHL": "jump-indirect", "RST": "rst", ...}

    Raises:
        ValueError: 同じニーモニックの命令に違う flow が付いている場合。
    """
    flow_of = {}
    for entry in i8080.I8080().codetbl:
        mnemonic = entry["asm"][0].upper()
        flow = entry.get("flow")
        if mnemonic in flow_of and flow_of[mnemonic] != flow:
            raise ValueError(
                f"Inconsistent flow for {mnemonic}: {flow_of[mnemonic]!r} and {flow!r}"
            )
        flow_of[mnemonic] = flow
    return {mnemonic: flow for mnemonic, flow in flow_of.items() if flow is not None}


_FLOW_BY_MNEMONIC = _build_flow_by_mnemonic()


def merge_ranges(sorted_addrs):
    """ソート済みアドレスリストを連続レンジのリストにまとめる。

    Args:
        sorted_addrs (list[int]): ソート済みアドレスリスト。

    Returns:
        list[list[int]]: [[start, end], ...] 形式のレンジリスト。
    """
    if not sorted_addrs:
        return []
    ranges = []
    start = end = sorted_addrs[0]
    for addr in sorted_addrs[1:]:
        if addr == end + 1:
            end = addr
        else:
            ranges.append([start, end])
            start = end = addr
    ranges.append([start, end])
    return ranges


def _get_branch_target(asm_str):
    """asm文字列から分岐先アドレスを抽出する。

    Args:
        asm_str (str): 逆アセンブルした命令。例: "JMP L_0100"

    Returns:
        int | None: `L_xxxx` のアドレス。ラベルが無ければ None。
    """
    m = _RE_LABEL.search(asm_str)
    return int(m.group(1), 16) if m else None


def _rst_vector(tokens):
    """`RST n` の飛び先アドレスを返す。

    User's Manual p.4-11 の RST の定義は `(PC) ← 8 * (NNN)`。オペランドの n
    （0〜7）を 8 倍したアドレスへ飛ぶ。pz80 の Z80 は `RST 0x38` とアドレスそのものを
    書くので、オペランドをそのまま飛び先にしていた。

    Args:
        tokens (list): 大文字にして空白で分けた命令。
            例: ["RST", "7"]

    Returns:
        int | None: 飛び先アドレス。例: 0x0038。オペランドが読めなければ None。
    """
    try:
        n = int(tokens[1], 0)
    except (IndexError, ValueError):
        return None
    if not 0 <= n <= 7:
        return None
    return n * 8


def classify_instruction(asm_str):
    """命令を分類して (次アドレス継続フラグ, 分岐先アドレスorNone) を返す。

    分類は命令表の `flow` で決める（docs/opcode-table-fields.md）。

        flow            継続    分岐先          命令
        jump            止まる  オペランド      JMP
        jump-cc         続く    オペランド      JNZ JZ JNC JC JPO JPE JP JM
        call            続く    オペランド      CALL
        call-cc         続く    オペランド      CNZ CZ CNC CC CPO CPE CP CM
        return          止まる  なし            RET
        return-cc       続く    なし            RNZ RZ RNC RC RPO RPE RP RM
        jump-indirect   止まる  なし            PCHL
        rst             続く    n × 8           RST 0〜7
        （flow 無し）   続く    なし            上記以外。`db` の行も含む

    pz80 は Z80 のニーモニックの一覧で判定していたため、8080 の出力では
    12 件中 8 件を誤った。とくに `JP`（jump on positive）と `CP`（call on
    positive）は Z80 の同じ綴りの命令と意味が違う。表から引けば取り違えない。

    Args:
        asm_str (str): 逆アセンブル済み命令文字列。
            例: "JNZ L_0008"、"RST 7"、"db 0xC3 ; Invalid Opcode"

    Returns:
        tuple[bool, int | None]: (継続フラグ, 分岐先アドレス)。
            継続フラグが False の場合、現在のトレースパスを停止する。
            例: "JMP L_1234" -> (False, 0x1234)、"RST 7" -> (True, 0x0038)
    """
    tokens = asm_str.upper().split()
    if not tokens:
        return True, None
    flow = _FLOW_BY_MNEMONIC.get(tokens[0])

    # HLT は flow を持たないので、下の「制御を変えない命令」として次へ進む。
    # 8080 の HLT は割り込み（INTR）か RESET で抜ける。`EI; HLT` で割り込みを
    # 待つ形では、割り込みから RET で戻ると HLT の次の命令へ進む。
    # 本当に止まるのは `DI; HLT` のときだけだが、そこでも次のバイトを
    # コードとして読むだけで、追跡を取りこぼすことはない。

    if flow == "jump":
        return False, _get_branch_target(asm_str)

    if flow == "jump-cc":
        return True, _get_branch_target(asm_str)

    if flow == "call":
        return True, _get_branch_target(asm_str)

    if flow == "call-cc":
        return True, _get_branch_target(asm_str)

    if flow == "return":
        return False, None

    if flow == "return-cc":
        return True, None

    if flow == "jump-indirect":
        # 飛び先は実行時の HL。静的には分からないので追跡を止める。
        # 飛び先の推定は `_auto_entry` の役目。
        return False, None

    if flow == "rst":
        # サブルーチン呼び出しなので、次の命令へも進む。
        return True, _rst_vector(tokens)

    return True, None


def address_set(start, size, valid_ranges=None):
    """解析対象となる有効アドレスの集合を返す。

    Args:
        start (int): ロードアドレス。valid_ranges 指定時は無視される。
        size (int): データ長。
        valid_ranges (list[list[int]] | None): 有効なアドレス範囲 [[start, end], ...]。

    Returns:
        set[int]: 有効アドレスの集合。
    """
    if valid_ranges is None:
        return set(range(start, start + size))
    addrs = set()
    for r in valid_ranges:
        addrs.update(range(r[0], r[1] + 1))
    return addrs


def build_addr_map(data, start=0, m1_handler=None, valid_ranges=None):
    """バイナリを逆アセンブルして アドレス → 命令 のマップを構築する。

    Args:
        data (bytes | list[int]): 解析対象のバイナリデータ。
        start (int): ロードアドレス。valid_ranges 指定時は 0 基点として扱う。
        m1_handler (callable | None): M1サイクル復号ハンドラー。
        valid_ranges (list[list[int]] | None): 有効なアドレス範囲。
            指定時はギャップ領域の命令をマップから除外する。

    Returns:
        dict[int, dict]: アドレスをキーとする逆アセンブル結果。
    """
    size = len(data)
    if size == 0:
        return {}

    disasm_start = 0 if valid_ranges is not None else start

    ope = disasm.Disasm()
    if m1_handler:
        ope.m1_handler = m1_handler
    out = ope.exec(disasm_start, list(data), size)
    addr_map = {p["address"]: p for p in out if p.get("opcode")}

    if valid_ranges is not None:
        valid = address_set(start, size, valid_ranges)
        addr_map = {a: p for a, p in addr_map.items() if a in valid}
    return addr_map


def sweep_from(data, addr, base=0, m1_handler=None):
    """指定アドレスから線形に逆アセンブルして アドレス → 命令 のマップを返す。

    `build_addr_map()` が作るのは**先頭から 1 回走査したときの命令境界**だけです。
    分岐先がその境界に乗らないことがあります。

        0x0005  C3 3E 30   先頭からの走査は JMP L_303E と 3 バイト読む
        0x0006             ここが本当の命令先頭だが、境界になっていない

    `0x0000: JMP L_0006` が実在するのに、0x0006 が map に無いため `trace()` が
    無言で追跡を打ち切り、その先がまるごとデータ扱いになっていました。
    linear sweep で境界を先に決めてしまうと recursive descent が入れない、という
    衝突です。分岐先から走査し直して境界を作るために使います。
    （この形は 9 バイトの合成イメージでテストに固定してあります）

    Args:
        data (bytes | list[int]): 解析対象のバイナリデータ。
        addr (int): 走査を始めるアドレス。
        base (int): `data[0]` が置かれているアドレス。
        m1_handler (callable | None): M1サイクル復号ハンドラー。

    Returns:
        dict[int, dict]: アドレスをキーとする逆アセンブル結果。範囲外なら空。
    """
    offset = addr - base
    if offset < 0 or offset >= len(data):
        return {}

    ope = disasm.Disasm()
    if m1_handler:
        ope.m1_handler = m1_handler
    out = ope.exec(addr, list(data)[offset:], len(data) - offset)
    return {p["address"]: p for p in out if p.get("opcode")}


def trace(addr_map, entries, resweep=None, unresolved=None, stop_after=None):
    """エントリポイントからCFGをトレースする。

    Args:
        addr_map (dict[int, dict]): build_addr_map() の戻り値。
        entries (iterable[int]): エントリポイントアドレス。
        resweep (callable | None): `addr_map` に無いアドレスに当たったとき、
            そこから走査し直して追加の命令マップを返す関数（`sweep_from()` を
            束縛したもの）。**与えないと、境界に乗らない分岐先で追跡が静かに
            止まります**。
        unresolved (set | None): 復号できなかった分岐先を書き出す集合。
            イメージの外（RAM・I/O）へ飛ぶ場合はここに残ります。
        stop_after (set[int] | None): **直後の命令へ進まない**アドレスの集合。
            分岐先は従来どおり追います。`RST` の直後にジャンプテーブルを
            埋め込む形（呼ばれた側が戻りアドレスを取り出して飛ぶ）で使います。
            命令の形だけでは「戻ってこない」と分からないので、外から教えます。
            渡すとテーブルのバイトがコードにならず、そのままデータへ落ちます。

    Returns:
        tuple[set[int], set[int]]: (到達したバイトの集合, 命令先頭アドレスの集合)。
            命令先頭集合は、あるアドレスが命令の途中かどうかの判定に使う。

    Note:
        `resweep` で見つけた命令は **`addr_map` へ追加します**（呼び出し側の
        辞書を書き換えます）。返す命令先頭集合にそれらのアドレスが含まれるので、
        呼び出し側が `addr_map[a]` を引けないと辻褄が合わなくなるためです。
    """
    code_addrs = set()
    heads = set()
    to_visit = set(entries)
    visited_starts = set()

    while to_visit:
        addr = to_visit.pop()
        if addr in visited_starts:
            continue
        visited_starts.add(addr)

        while True:
            p = addr_map.get(addr)
            if p is None and resweep is not None:
                # 先頭からの走査が作った境界に乗らない分岐先。そこから読み直す。
                for a, q in resweep(addr).items():
                    addr_map.setdefault(a, q)
                p = addr_map.get(addr)
            if p is None:
                if unresolved is not None:
                    unresolved.add(addr)
                break

            if addr in code_addrs:
                break

            instr_len = len(p["opcode"])
            heads.add(addr)
            for i in range(instr_len):
                code_addrs.add(addr + i)

            continues, branch_target = classify_instruction(p["asm"])

            if branch_target is not None:
                to_visit.add(branch_target)

            if stop_after and addr in stop_after:
                continues = False

            if not continues:
                break

            addr += instr_len

    return code_addrs, heads


def walk(
    data,
    start=0,
    extra_entries=None,
    valid_ranges=None,
    m1_handler=None,
    unresolved=None,
    stop_after=None,
):
    """CFGトレースによりデータ領域を検出する。

    バイナリデータを逆アセンブルし、エントリポイントから制御フローをトレースする。
    到達できなかったアドレス範囲をデータ領域として返す。

    Args:
        data (bytes | list[int]): 解析対象のバイナリデータ。
        start (int): メインエントリポイントアドレス (デフォルト: 0x0000)。
            valid_ranges が None の場合はロードアドレスも兼ねる。
        extra_entries (list[str | int] | None): 追加エントリポイントのリスト。
            文字列 (RESET/RST0-7) または整数アドレスを指定する。
        valid_ranges (list[list[int]] | None): 有効なアドレス範囲 [[start, end], ...]。
            指定時は data をアドレス 0 基点の配列として扱い、ギャップ領域を出力から除外する。
            複数ファイルを異なるアドレスに配置する場合に使用する。
        m1_handler (callable | None): M1サイクル復号ハンドラー。
            (address: int, byte: int) -> int の形式。暗号化ROMのCFGトレースに使用する。
        unresolved (set | None): 復号できなかった分岐先を書き出す集合。
            イメージの外や `valid_ranges` の隙間へ飛ぶものがここに残る。

            **出たら飛び先を確かめる。** いちばん多い原因は `bins` の指定漏れか、
            ROM ファイルの欠落。ただし、拡張 ROM を確かめてから飛ぶコードや、RAM に
            写したコードのように、本物のコードも外へ飛ぶ。エントリがデータを指して
            いて、データの中の「分岐」が外を指していることもある。
        stop_after (set[int] | None): **直後の命令へ進まない**アドレスの集合。
            `RST` の直後にジャンプテーブルを埋め込む形で使う。詳細は `trace()`。
            `AutoEntry.no_fallthrough` をそのまま渡せる。

    Returns:
        list[list[int]]: データ領域の [[start, end], ...] リスト。

    Raises:
        ValueError: extra_entries に無効な値が含まれる場合。

    Example:
        >>> with open("rom.bin", "rb") as f:
        ...     binary = f.read()
        >>> regions = walk(binary, start=0x0000, extra_entries=["RST1", "RST7"])
        >>> print(regions)
        [[0x1000, 0x12FF], [0x2000, 0x2FFF]]
    """
    size = len(data)
    if size == 0:
        return []

    all_addrs = address_set(start, size, valid_ranges)

    # エントリポイント収集
    entry_points = {start}
    for e in extra_entries or []:
        entry_points.add(parse_entry(e))

    addr_map = build_addr_map(data, start, m1_handler, valid_ranges)

    # 分岐先が先頭からの走査の命令境界に乗らないことがある。そこから読み直せる
    # ようにしておく（詳細は sweep_from()）。valid_ranges 指定時は data を
    # アドレス 0 基点として扱うので、基点の取り方を build_addr_map と揃える。
    base = 0 if valid_ranges is not None else start
    valid = address_set(start, size, valid_ranges)

    def resweep(addr):
        """`addr_map` に無い分岐先から読み直し、ROM のある範囲の命令だけを返す。

        Args:
            addr (int): 読み直しを始めるアドレス。

        Returns:
            dict[int, dict]: アドレスをキーとする命令。addr に ROM が無ければ空。
        """
        if addr not in valid:
            return {}
        return {
            a: p
            for a, p in sweep_from(data, addr, base, m1_handler).items()
            if a in valid
        }

    code_addrs, _heads = trace(
        addr_map,
        entry_points,
        resweep=resweep,
        unresolved=unresolved,
        stop_after=stop_after,
    )

    # データ領域 = 有効アドレス全体 - コード領域
    return merge_ranges(sorted(all_addrs - code_addrs))
