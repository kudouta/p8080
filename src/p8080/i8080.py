#!/usr/bin/env python3


class I8080:
    """Intel 8080 CPUクラス

    pz80 の `Z80` クラスを移植したもの。命令表（`_codetbl`）は
    `i8080_opcodes.yaml` から `tools/generate_codetbl.py` で生成する。
    """

    # クラスレベルでデータを保持（インスタンス化ごとの再生成を防ぐ）
    _initialized = False
    _reserved = []
    _asm_map = {}
    _op_map = {}

    # 逆アセンブル時に使用する 0x00-0xff に 対応する文字テーブル -> 外部ファイルでカスタマイズ可能
    _strmap_default = (
        # 0    1    2    3    4    5    6    7    8    9    A    B    C    D    E    F
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",  # 00
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",  # 10
        " ",
        "!",
        '"',
        "#",
        "$",
        "%",
        "&",
        "'",
        "(",
        ")",
        "*",
        "+",
        ",",
        "-",
        ".",
        "/",  # 20
        "0",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        ":",
        ";",
        "<",
        "=",
        ">",
        "?",  # 30
        "@",
        "A",
        "B",
        "C",
        "D",
        "E",
        "F",
        "G",
        "H",
        "I",
        "J",
        "K",
        "L",
        "M",
        "N",
        "O",  # 40
        "P",
        "Q",
        "R",
        "S",
        "T",
        "U",
        "V",
        "W",
        "X",
        "Y",
        "Z",
        "[",
        " ",
        "]",
        "^",
        "_",  # 50
        "`",
        "a",
        "b",
        "c",
        "d",
        "e",
        "f",
        "g",
        "h",
        "i",
        "j",
        "k",
        "l",
        "m",
        "n",
        "o",  # 60
        "p",
        "q",
        "r",
        "s",
        "t",
        "u",
        "v",
        "w",
        "x",
        "y",
        "z",
        "{",
        "|",
        "}",
        "~",
        ".",  # 70
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",  # 80
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",  # 90
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",  # a0
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",  # b0
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",  # c0
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",  # d0
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",  # e0
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",
        ".",  # f0
    )

    # 8080コードテーブル
    # <<< BEGIN GENERATED FROM i8080_opcodes.yaml >>>
    _codetbl = [
        # 00xxxxxx: データ転送・16ビット演算・INR/DCR/MVI・ローテート
        {"code": [0x00], "bytes": 1, "asm": ["nop"]},
        {
            "code": [0x01],
            "bytes": 3,
            "asm": ["lxi", "b", ",", "0x{1}{0}"],
            "type": "word",
            "access": "imm",
        },
        {"code": [0x02], "bytes": 1, "asm": ["stax", "b"]},
        {"code": [0x03], "bytes": 1, "asm": ["inx", "b"]},
        {"code": [0x04], "bytes": 1, "asm": ["inr", "b"]},
        {"code": [0x05], "bytes": 1, "asm": ["dcr", "b"]},
        {"code": [0x06], "bytes": 2, "asm": ["mvi", "b", ",", "0x{0}"]},
        {"code": [0x07], "bytes": 1, "asm": ["rlc"]},
        {"code": [0x09], "bytes": 1, "asm": ["dad", "b"]},
        {"code": [0x0A], "bytes": 1, "asm": ["ldax", "b"]},
        {"code": [0x0B], "bytes": 1, "asm": ["dcx", "b"]},
        {"code": [0x0C], "bytes": 1, "asm": ["inr", "c"]},
        {"code": [0x0D], "bytes": 1, "asm": ["dcr", "c"]},
        {"code": [0x0E], "bytes": 2, "asm": ["mvi", "c", ",", "0x{0}"]},
        {"code": [0x0F], "bytes": 1, "asm": ["rrc"]},
        {
            "code": [0x11],
            "bytes": 3,
            "asm": ["lxi", "d", ",", "0x{1}{0}"],
            "type": "word",
            "access": "imm",
        },
        {"code": [0x12], "bytes": 1, "asm": ["stax", "d"]},
        {"code": [0x13], "bytes": 1, "asm": ["inx", "d"]},
        {"code": [0x14], "bytes": 1, "asm": ["inr", "d"]},
        {"code": [0x15], "bytes": 1, "asm": ["dcr", "d"]},
        {"code": [0x16], "bytes": 2, "asm": ["mvi", "d", ",", "0x{0}"]},
        {"code": [0x17], "bytes": 1, "asm": ["ral"]},
        {"code": [0x19], "bytes": 1, "asm": ["dad", "d"]},
        {"code": [0x1A], "bytes": 1, "asm": ["ldax", "d"]},
        {"code": [0x1B], "bytes": 1, "asm": ["dcx", "d"]},
        {"code": [0x1C], "bytes": 1, "asm": ["inr", "e"]},
        {"code": [0x1D], "bytes": 1, "asm": ["dcr", "e"]},
        {"code": [0x1E], "bytes": 2, "asm": ["mvi", "e", ",", "0x{0}"]},
        {"code": [0x1F], "bytes": 1, "asm": ["rar"]},
        {
            "code": [0x21],
            "bytes": 3,
            "asm": ["lxi", "h", ",", "0x{1}{0}"],
            "type": "word",
            "access": "imm",
        },
        {
            "code": [0x22],
            "bytes": 3,
            "asm": ["shld", "0x{1}{0}"],
            "type": "word",
            "access": "w",
        },
        {"code": [0x23], "bytes": 1, "asm": ["inx", "h"]},
        {"code": [0x24], "bytes": 1, "asm": ["inr", "h"]},
        {"code": [0x25], "bytes": 1, "asm": ["dcr", "h"]},
        {"code": [0x26], "bytes": 2, "asm": ["mvi", "h", ",", "0x{0}"]},
        {"code": [0x27], "bytes": 1, "asm": ["daa"]},
        {"code": [0x29], "bytes": 1, "asm": ["dad", "h"]},
        {
            "code": [0x2A],
            "bytes": 3,
            "asm": ["lhld", "0x{1}{0}"],
            "type": "word",
            "access": "r",
        },
        {"code": [0x2B], "bytes": 1, "asm": ["dcx", "h"]},
        {"code": [0x2C], "bytes": 1, "asm": ["inr", "l"]},
        {"code": [0x2D], "bytes": 1, "asm": ["dcr", "l"]},
        {"code": [0x2E], "bytes": 2, "asm": ["mvi", "l", ",", "0x{0}"]},
        {"code": [0x2F], "bytes": 1, "asm": ["cma"]},
        {
            "code": [0x31],
            "bytes": 3,
            "asm": ["lxi", "sp", ",", "0x{1}{0}"],
            "type": "word",
            "access": "imm",
        },
        {
            "code": [0x32],
            "bytes": 3,
            "asm": ["sta", "0x{1}{0}"],
            "type": "word",
            "access": "w",
        },
        {"code": [0x33], "bytes": 1, "asm": ["inx", "sp"]},
        {"code": [0x34], "bytes": 1, "asm": ["inr", "m"]},
        {"code": [0x35], "bytes": 1, "asm": ["dcr", "m"]},
        {"code": [0x36], "bytes": 2, "asm": ["mvi", "m", ",", "0x{0}"]},
        {"code": [0x37], "bytes": 1, "asm": ["stc"]},
        {"code": [0x39], "bytes": 1, "asm": ["dad", "sp"]},
        {
            "code": [0x3A],
            "bytes": 3,
            "asm": ["lda", "0x{1}{0}"],
            "type": "word",
            "access": "r",
        },
        {"code": [0x3B], "bytes": 1, "asm": ["dcx", "sp"]},
        {"code": [0x3C], "bytes": 1, "asm": ["inr", "a"]},
        {"code": [0x3D], "bytes": 1, "asm": ["dcr", "a"]},
        {"code": [0x3E], "bytes": 2, "asm": ["mvi", "a", ",", "0x{0}"]},
        {"code": [0x3F], "bytes": 1, "asm": ["cmc"]},
        # 01xxxxxx: MOV / HLT
        {"code": [0x40], "bytes": 1, "asm": ["mov", "b", ",", "b"]},
        {"code": [0x41], "bytes": 1, "asm": ["mov", "b", ",", "c"]},
        {"code": [0x42], "bytes": 1, "asm": ["mov", "b", ",", "d"]},
        {"code": [0x43], "bytes": 1, "asm": ["mov", "b", ",", "e"]},
        {"code": [0x44], "bytes": 1, "asm": ["mov", "b", ",", "h"]},
        {"code": [0x45], "bytes": 1, "asm": ["mov", "b", ",", "l"]},
        {"code": [0x46], "bytes": 1, "asm": ["mov", "b", ",", "m"]},
        {"code": [0x47], "bytes": 1, "asm": ["mov", "b", ",", "a"]},
        {"code": [0x48], "bytes": 1, "asm": ["mov", "c", ",", "b"]},
        {"code": [0x49], "bytes": 1, "asm": ["mov", "c", ",", "c"]},
        {"code": [0x4A], "bytes": 1, "asm": ["mov", "c", ",", "d"]},
        {"code": [0x4B], "bytes": 1, "asm": ["mov", "c", ",", "e"]},
        {"code": [0x4C], "bytes": 1, "asm": ["mov", "c", ",", "h"]},
        {"code": [0x4D], "bytes": 1, "asm": ["mov", "c", ",", "l"]},
        {"code": [0x4E], "bytes": 1, "asm": ["mov", "c", ",", "m"]},
        {"code": [0x4F], "bytes": 1, "asm": ["mov", "c", ",", "a"]},
        {"code": [0x50], "bytes": 1, "asm": ["mov", "d", ",", "b"]},
        {"code": [0x51], "bytes": 1, "asm": ["mov", "d", ",", "c"]},
        {"code": [0x52], "bytes": 1, "asm": ["mov", "d", ",", "d"]},
        {"code": [0x53], "bytes": 1, "asm": ["mov", "d", ",", "e"]},
        {"code": [0x54], "bytes": 1, "asm": ["mov", "d", ",", "h"]},
        {"code": [0x55], "bytes": 1, "asm": ["mov", "d", ",", "l"]},
        {"code": [0x56], "bytes": 1, "asm": ["mov", "d", ",", "m"]},
        {"code": [0x57], "bytes": 1, "asm": ["mov", "d", ",", "a"]},
        {"code": [0x58], "bytes": 1, "asm": ["mov", "e", ",", "b"]},
        {"code": [0x59], "bytes": 1, "asm": ["mov", "e", ",", "c"]},
        {"code": [0x5A], "bytes": 1, "asm": ["mov", "e", ",", "d"]},
        {"code": [0x5B], "bytes": 1, "asm": ["mov", "e", ",", "e"]},
        {"code": [0x5C], "bytes": 1, "asm": ["mov", "e", ",", "h"]},
        {"code": [0x5D], "bytes": 1, "asm": ["mov", "e", ",", "l"]},
        {"code": [0x5E], "bytes": 1, "asm": ["mov", "e", ",", "m"]},
        {"code": [0x5F], "bytes": 1, "asm": ["mov", "e", ",", "a"]},
        {"code": [0x60], "bytes": 1, "asm": ["mov", "h", ",", "b"]},
        {"code": [0x61], "bytes": 1, "asm": ["mov", "h", ",", "c"]},
        {"code": [0x62], "bytes": 1, "asm": ["mov", "h", ",", "d"]},
        {"code": [0x63], "bytes": 1, "asm": ["mov", "h", ",", "e"]},
        {"code": [0x64], "bytes": 1, "asm": ["mov", "h", ",", "h"]},
        {"code": [0x65], "bytes": 1, "asm": ["mov", "h", ",", "l"]},
        {"code": [0x66], "bytes": 1, "asm": ["mov", "h", ",", "m"]},
        {"code": [0x67], "bytes": 1, "asm": ["mov", "h", ",", "a"]},
        {"code": [0x68], "bytes": 1, "asm": ["mov", "l", ",", "b"]},
        {"code": [0x69], "bytes": 1, "asm": ["mov", "l", ",", "c"]},
        {"code": [0x6A], "bytes": 1, "asm": ["mov", "l", ",", "d"]},
        {"code": [0x6B], "bytes": 1, "asm": ["mov", "l", ",", "e"]},
        {"code": [0x6C], "bytes": 1, "asm": ["mov", "l", ",", "h"]},
        {"code": [0x6D], "bytes": 1, "asm": ["mov", "l", ",", "l"]},
        {"code": [0x6E], "bytes": 1, "asm": ["mov", "l", ",", "m"]},
        {"code": [0x6F], "bytes": 1, "asm": ["mov", "l", ",", "a"]},
        {"code": [0x70], "bytes": 1, "asm": ["mov", "m", ",", "b"]},
        {"code": [0x71], "bytes": 1, "asm": ["mov", "m", ",", "c"]},
        {"code": [0x72], "bytes": 1, "asm": ["mov", "m", ",", "d"]},
        {"code": [0x73], "bytes": 1, "asm": ["mov", "m", ",", "e"]},
        {"code": [0x74], "bytes": 1, "asm": ["mov", "m", ",", "h"]},
        {"code": [0x75], "bytes": 1, "asm": ["mov", "m", ",", "l"]},
        {"code": [0x76], "bytes": 1, "asm": ["hlt"]},
        {"code": [0x77], "bytes": 1, "asm": ["mov", "m", ",", "a"]},
        {"code": [0x78], "bytes": 1, "asm": ["mov", "a", ",", "b"]},
        {"code": [0x79], "bytes": 1, "asm": ["mov", "a", ",", "c"]},
        {"code": [0x7A], "bytes": 1, "asm": ["mov", "a", ",", "d"]},
        {"code": [0x7B], "bytes": 1, "asm": ["mov", "a", ",", "e"]},
        {"code": [0x7C], "bytes": 1, "asm": ["mov", "a", ",", "h"]},
        {"code": [0x7D], "bytes": 1, "asm": ["mov", "a", ",", "l"]},
        {"code": [0x7E], "bytes": 1, "asm": ["mov", "a", ",", "m"]},
        {"code": [0x7F], "bytes": 1, "asm": ["mov", "a", ",", "a"]},
        # 10xxxxxx: レジスタ・メモリと A の演算
        {"code": [0x80], "bytes": 1, "asm": ["add", "b"]},
        {"code": [0x81], "bytes": 1, "asm": ["add", "c"]},
        {"code": [0x82], "bytes": 1, "asm": ["add", "d"]},
        {"code": [0x83], "bytes": 1, "asm": ["add", "e"]},
        {"code": [0x84], "bytes": 1, "asm": ["add", "h"]},
        {"code": [0x85], "bytes": 1, "asm": ["add", "l"]},
        {"code": [0x86], "bytes": 1, "asm": ["add", "m"]},
        {"code": [0x87], "bytes": 1, "asm": ["add", "a"]},
        {"code": [0x88], "bytes": 1, "asm": ["adc", "b"]},
        {"code": [0x89], "bytes": 1, "asm": ["adc", "c"]},
        {"code": [0x8A], "bytes": 1, "asm": ["adc", "d"]},
        {"code": [0x8B], "bytes": 1, "asm": ["adc", "e"]},
        {"code": [0x8C], "bytes": 1, "asm": ["adc", "h"]},
        {"code": [0x8D], "bytes": 1, "asm": ["adc", "l"]},
        {"code": [0x8E], "bytes": 1, "asm": ["adc", "m"]},
        {"code": [0x8F], "bytes": 1, "asm": ["adc", "a"]},
        {"code": [0x90], "bytes": 1, "asm": ["sub", "b"]},
        {"code": [0x91], "bytes": 1, "asm": ["sub", "c"]},
        {"code": [0x92], "bytes": 1, "asm": ["sub", "d"]},
        {"code": [0x93], "bytes": 1, "asm": ["sub", "e"]},
        {"code": [0x94], "bytes": 1, "asm": ["sub", "h"]},
        {"code": [0x95], "bytes": 1, "asm": ["sub", "l"]},
        {"code": [0x96], "bytes": 1, "asm": ["sub", "m"]},
        {"code": [0x97], "bytes": 1, "asm": ["sub", "a"]},
        {"code": [0x98], "bytes": 1, "asm": ["sbb", "b"]},
        {"code": [0x99], "bytes": 1, "asm": ["sbb", "c"]},
        {"code": [0x9A], "bytes": 1, "asm": ["sbb", "d"]},
        {"code": [0x9B], "bytes": 1, "asm": ["sbb", "e"]},
        {"code": [0x9C], "bytes": 1, "asm": ["sbb", "h"]},
        {"code": [0x9D], "bytes": 1, "asm": ["sbb", "l"]},
        {"code": [0x9E], "bytes": 1, "asm": ["sbb", "m"]},
        {"code": [0x9F], "bytes": 1, "asm": ["sbb", "a"]},
        {"code": [0xA0], "bytes": 1, "asm": ["ana", "b"]},
        {"code": [0xA1], "bytes": 1, "asm": ["ana", "c"]},
        {"code": [0xA2], "bytes": 1, "asm": ["ana", "d"]},
        {"code": [0xA3], "bytes": 1, "asm": ["ana", "e"]},
        {"code": [0xA4], "bytes": 1, "asm": ["ana", "h"]},
        {"code": [0xA5], "bytes": 1, "asm": ["ana", "l"]},
        {"code": [0xA6], "bytes": 1, "asm": ["ana", "m"]},
        {"code": [0xA7], "bytes": 1, "asm": ["ana", "a"]},
        {"code": [0xA8], "bytes": 1, "asm": ["xra", "b"]},
        {"code": [0xA9], "bytes": 1, "asm": ["xra", "c"]},
        {"code": [0xAA], "bytes": 1, "asm": ["xra", "d"]},
        {"code": [0xAB], "bytes": 1, "asm": ["xra", "e"]},
        {"code": [0xAC], "bytes": 1, "asm": ["xra", "h"]},
        {"code": [0xAD], "bytes": 1, "asm": ["xra", "l"]},
        {"code": [0xAE], "bytes": 1, "asm": ["xra", "m"]},
        {"code": [0xAF], "bytes": 1, "asm": ["xra", "a"]},
        {"code": [0xB0], "bytes": 1, "asm": ["ora", "b"]},
        {"code": [0xB1], "bytes": 1, "asm": ["ora", "c"]},
        {"code": [0xB2], "bytes": 1, "asm": ["ora", "d"]},
        {"code": [0xB3], "bytes": 1, "asm": ["ora", "e"]},
        {"code": [0xB4], "bytes": 1, "asm": ["ora", "h"]},
        {"code": [0xB5], "bytes": 1, "asm": ["ora", "l"]},
        {"code": [0xB6], "bytes": 1, "asm": ["ora", "m"]},
        {"code": [0xB7], "bytes": 1, "asm": ["ora", "a"]},
        {"code": [0xB8], "bytes": 1, "asm": ["cmp", "b"]},
        {"code": [0xB9], "bytes": 1, "asm": ["cmp", "c"]},
        {"code": [0xBA], "bytes": 1, "asm": ["cmp", "d"]},
        {"code": [0xBB], "bytes": 1, "asm": ["cmp", "e"]},
        {"code": [0xBC], "bytes": 1, "asm": ["cmp", "h"]},
        {"code": [0xBD], "bytes": 1, "asm": ["cmp", "l"]},
        {"code": [0xBE], "bytes": 1, "asm": ["cmp", "m"]},
        {"code": [0xBF], "bytes": 1, "asm": ["cmp", "a"]},
        # 11xxxxxx: 分岐・スタック・即値演算・入出力
        {"code": [0xC0], "bytes": 1, "asm": ["rnz"], "flow": "return-cc"},
        {"code": [0xC1], "bytes": 1, "asm": ["pop", "b"]},
        {
            "code": [0xC2],
            "bytes": 3,
            "asm": ["jnz", "0x{1}{0}"],
            "jmp": 1,
            "flow": "jump-cc",
        },
        {
            "code": [0xC3],
            "bytes": 3,
            "asm": ["jmp", "0x{1}{0}"],
            "jmp": 1,
            "flow": "jump",
        },
        {
            "code": [0xC4],
            "bytes": 3,
            "asm": ["cnz", "0x{1}{0}"],
            "jmp": 1,
            "flow": "call-cc",
        },
        {"code": [0xC5], "bytes": 1, "asm": ["push", "b"]},
        {"code": [0xC6], "bytes": 2, "asm": ["adi", "0x{0}"]},
        {"code": [0xC7], "bytes": 1, "asm": ["rst", "0"], "flow": "rst"},
        {"code": [0xC8], "bytes": 1, "asm": ["rz"], "flow": "return-cc"},
        {"code": [0xC9], "bytes": 1, "asm": ["ret"], "flow": "return"},
        {
            "code": [0xCA],
            "bytes": 3,
            "asm": ["jz", "0x{1}{0}"],
            "jmp": 1,
            "flow": "jump-cc",
        },
        {
            "code": [0xCC],
            "bytes": 3,
            "asm": ["cz", "0x{1}{0}"],
            "jmp": 1,
            "flow": "call-cc",
        },
        {
            "code": [0xCD],
            "bytes": 3,
            "asm": ["call", "0x{1}{0}"],
            "jmp": 1,
            "flow": "call",
        },
        {"code": [0xCE], "bytes": 2, "asm": ["aci", "0x{0}"]},
        {"code": [0xCF], "bytes": 1, "asm": ["rst", "1"], "flow": "rst"},
        {"code": [0xD0], "bytes": 1, "asm": ["rnc"], "flow": "return-cc"},
        {"code": [0xD1], "bytes": 1, "asm": ["pop", "d"]},
        {
            "code": [0xD2],
            "bytes": 3,
            "asm": ["jnc", "0x{1}{0}"],
            "jmp": 1,
            "flow": "jump-cc",
        },
        {"code": [0xD3], "bytes": 2, "asm": ["out", "0x{0}"]},
        {
            "code": [0xD4],
            "bytes": 3,
            "asm": ["cnc", "0x{1}{0}"],
            "jmp": 1,
            "flow": "call-cc",
        },
        {"code": [0xD5], "bytes": 1, "asm": ["push", "d"]},
        {"code": [0xD6], "bytes": 2, "asm": ["sui", "0x{0}"]},
        {"code": [0xD7], "bytes": 1, "asm": ["rst", "2"], "flow": "rst"},
        {"code": [0xD8], "bytes": 1, "asm": ["rc"], "flow": "return-cc"},
        {
            "code": [0xDA],
            "bytes": 3,
            "asm": ["jc", "0x{1}{0}"],
            "jmp": 1,
            "flow": "jump-cc",
        },
        {"code": [0xDB], "bytes": 2, "asm": ["in", "0x{0}"]},
        {
            "code": [0xDC],
            "bytes": 3,
            "asm": ["cc", "0x{1}{0}"],
            "jmp": 1,
            "flow": "call-cc",
        },
        {"code": [0xDE], "bytes": 2, "asm": ["sbi", "0x{0}"]},
        {"code": [0xDF], "bytes": 1, "asm": ["rst", "3"], "flow": "rst"},
        {"code": [0xE0], "bytes": 1, "asm": ["rpo"], "flow": "return-cc"},
        {"code": [0xE1], "bytes": 1, "asm": ["pop", "h"]},
        {
            "code": [0xE2],
            "bytes": 3,
            "asm": ["jpo", "0x{1}{0}"],
            "jmp": 1,
            "flow": "jump-cc",
        },
        {"code": [0xE3], "bytes": 1, "asm": ["xthl"]},
        {
            "code": [0xE4],
            "bytes": 3,
            "asm": ["cpo", "0x{1}{0}"],
            "jmp": 1,
            "flow": "call-cc",
        },
        {"code": [0xE5], "bytes": 1, "asm": ["push", "h"]},
        {"code": [0xE6], "bytes": 2, "asm": ["ani", "0x{0}"]},
        {"code": [0xE7], "bytes": 1, "asm": ["rst", "4"], "flow": "rst"},
        {"code": [0xE8], "bytes": 1, "asm": ["rpe"], "flow": "return-cc"},
        {"code": [0xE9], "bytes": 1, "asm": ["pchl"], "flow": "jump-indirect"},
        {
            "code": [0xEA],
            "bytes": 3,
            "asm": ["jpe", "0x{1}{0}"],
            "jmp": 1,
            "flow": "jump-cc",
        },
        {"code": [0xEB], "bytes": 1, "asm": ["xchg"]},
        {
            "code": [0xEC],
            "bytes": 3,
            "asm": ["cpe", "0x{1}{0}"],
            "jmp": 1,
            "flow": "call-cc",
        },
        {"code": [0xEE], "bytes": 2, "asm": ["xri", "0x{0}"]},
        {"code": [0xEF], "bytes": 1, "asm": ["rst", "5"], "flow": "rst"},
        {"code": [0xF0], "bytes": 1, "asm": ["rp"], "flow": "return-cc"},
        {"code": [0xF1], "bytes": 1, "asm": ["pop", "psw"]},
        {
            "code": [0xF2],
            "bytes": 3,
            "asm": ["jp", "0x{1}{0}"],
            "jmp": 1,
            "flow": "jump-cc",
        },
        {"code": [0xF3], "bytes": 1, "asm": ["di"]},
        {
            "code": [0xF4],
            "bytes": 3,
            "asm": ["cp", "0x{1}{0}"],
            "jmp": 1,
            "flow": "call-cc",
        },
        {"code": [0xF5], "bytes": 1, "asm": ["push", "psw"]},
        {"code": [0xF6], "bytes": 2, "asm": ["ori", "0x{0}"]},
        {"code": [0xF7], "bytes": 1, "asm": ["rst", "6"], "flow": "rst"},
        {"code": [0xF8], "bytes": 1, "asm": ["rm"], "flow": "return-cc"},
        {"code": [0xF9], "bytes": 1, "asm": ["sphl"]},
        {
            "code": [0xFA],
            "bytes": 3,
            "asm": ["jm", "0x{1}{0}"],
            "jmp": 1,
            "flow": "jump-cc",
        },
        {"code": [0xFB], "bytes": 1, "asm": ["ei"]},
        {
            "code": [0xFC],
            "bytes": 3,
            "asm": ["cm", "0x{1}{0}"],
            "jmp": 1,
            "flow": "call-cc",
        },
        {"code": [0xFE], "bytes": 2, "asm": ["cpi", "0x{0}"]},
        {"code": [0xFF], "bytes": 1, "asm": ["rst", "7"], "flow": "rst"},
    ]
    # <<< END GENERATED >>>

    def __init__(self):
        """I8080クラスを初期化します。"""
        self._strmap = self._strmap_default
        if not I8080._initialized:
            I8080._build_maps()

    @classmethod
    def _build_maps(cls):
        """クラスレベルのマップ（予約語、命令マップなど）を構築します。

        Raises:
            ValueError: 命令表の中で、アセンブラ用のキー（`asm` のトークン列）
                または逆アセンブラ用のキー（オペコード）が重複している場合。
        """
        # 予約語テーブルを生成
        r = set()

        # レジスター追加
        # Intel 表記ではレジスタ対を先頭のレジスタ名（b / d / h）で書くので、
        # Z80 の bc / de / hl にあたる名前は無い。m は (HL) が指すメモリ、
        # psw は A とフラグの組（PUSH / POP 専用）。
        r.update(
            {
                "a",
                "b",
                "c",
                "d",
                "e",
                "h",
                "l",
                "m",
                "sp",
                "psw",
            }
        )

        # 条件指定は追加しない。
        # Intel 表記では条件がニーモニックの一部（jnz / cz / rpe など）で、
        # オペランドとして現れないため。ニーモニックは下の「オペコード追加」で入る。

        # 疑似命令追加
        r.update(
            {
                "org",
                "equ",
                "end",
                "ds",
                "defs",
                "align",
                "db",
                "defb",
                "dw",
                "defw",
                "if",
                "else",
                "elseif",
                "endif",
            }
        )

        # オペコード追加
        for p in cls._codetbl:
            r.add(p["asm"][0])

        cls._reserved = sorted(r)

        # 高速検索用マップの生成
        cls._asm_map = {}
        cls._op_map = {}

        for item in cls._codetbl:
            # アセンブラ用マップ (ニーモニック -> 命令情報)
            # e.g) cls._asm_map[("inx", "b")] = {"code": [0x03], "bytes": 1, "asm": ["inx", "b"]}
            asm_key = tuple(item["asm"])
            if asm_key in cls._asm_map:
                raise ValueError(f"Duplicate asm key in _codetbl: {asm_key}")
            cls._asm_map[asm_key] = item

            # 逆アセンブラ用マップ (オペコード -> 命令情報)
            # e.g) cls._op_map[(0x03,)] = {"code": [0x03], "bytes": 1, "asm": ["inx", "b"]}
            # 8080 はプレフィックスを持たないので、キーは常にオペコード 1 バイト。
            op_key = tuple(item["code"])
            if op_key in cls._op_map:
                raise ValueError(f"Duplicate opcode in _codetbl: {op_key}")
            cls._op_map[op_key] = item

        cls._initialized = True

    @property
    def codetbl(self):
        """8080命令コードテーブルを取得します。

        Returns:
            list[dict]: 命令ごとの定義（`i8080_opcodes.yaml` から作ったもの）。
        """
        return self._codetbl

    @property
    def reserved(self):
        """予約語リストを取得します。

        Returns:
            list[str]: 小文字のニーモニック・レジスタ名・疑似命令を昇順に並べたもの。
        """
        return self._reserved

    @property
    def asm_map(self):
        """アセンブラ用マップ（ニーモニック -> 命令情報）を取得します。

        Returns:
            dict[tuple[str, ...], dict]: 命令表の `asm`（例: `("lxi", "b", ",", "0x{1}{0}")`）を
                キーとする命令情報。
        """
        return self._asm_map

    @property
    def op_map(self):
        """逆アセンブラ用マップ（オペコード -> 命令情報）を取得します。

        Returns:
            dict[tuple[int], dict]: オペコード 1 バイト（例: `(0x3E,)`）をキーとする命令情報。
        """
        return self._op_map

    @property
    def strmap(self):
        """文字変換テーブルを取得します。

        設定は `strmap = 表` で行います（設定ファイルの `chr` と同じ形）。

        Returns:
            tuple[str, ...]: 256 要素。バイト値ごとの `; [文字]` の文字。
        """
        return self._strmap

    @strmap.setter
    def strmap(self, p):
        """文字変換テーブルを設定します。

        Args:
            p (tuple[str, ...] | list[str]): 256 要素。バイト値ごとの `; [文字]` の文字。
        """
        self._strmap = p
