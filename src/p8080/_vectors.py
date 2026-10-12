#!/usr/bin/env python3

"""8080 固定ベクタアドレスとエントリポイント表記の解決。

`walk.py` と `disasm.py` の両方がエントリポイント表記を解決する必要がある。
`walk` は `disasm` に依存するため、この機能を `walk` に置くと循環参照になる
（実際、以前は `disasm` 側が関数内 import で回避していた）。依存を持たない
このモジュールに置くことで、双方が素直に import できる。
"""

# 8080 固定ベクタアドレスのエイリアス
# Z80 の IM1 / NMI は載せない。8080 には NMI 端子が無く、割り込みは INTR に
# 応答して外部回路がデータバスに置く命令（普通は RST n）で受けるため、
# 固定の割り込みアドレスは RST のベクタだけになる。
VECTOR_ALIASES = {
    "RESET": 0x0000,
    "RST0": 0x0000,
    "RST1": 0x0008,
    "RST2": 0x0010,
    "RST3": 0x0018,
    "RST4": 0x0020,
    "RST5": 0x0028,
    "RST6": 0x0030,
    "RST7": 0x0038,
}


def parse_entry(value):
    """エントリポイントをアドレスに変換する。

    Args:
        value (str | int): シンボル名 (RESET/RST0-7)、数値文字列 (0x0038 等)、
            または整数アドレス。

    Returns:
        int: アドレス値。

    Raises:
        ValueError: 変換できない文字列の場合。
    """
    if isinstance(value, int):
        return value
    upper = value.upper()
    if upper in VECTOR_ALIASES:
        return VECTOR_ALIASES[upper]
    return int(value, 0)
