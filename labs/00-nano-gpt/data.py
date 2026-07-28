"""字符级 tokenizer + 数据准备。

产出 data/train.npy / data/val.npy / data/meta.json，供 train.py 使用。
"""

import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
DATA = HERE / "data"


def build(src: str = "tinyshakespeare.txt", val_ratio: float = 0.1) -> None:
    text = (DATA / src).read_text(encoding="utf-8")

    # 字符级词表：语料里出现过的所有字符，排序后按下标编号
    chars = sorted(set(text))
    stoi = {c: i for i, c in enumerate(chars)}
    itos = {i: c for c, i in stoi.items()}

    # 整份语料编码成一维 token 序列。uint16 够用（词表 < 65536），
    # 相比 int64 省 4 倍内存 —— 到了 TinyStories 这个差别就不是小事了。
    ids = np.array([stoi[c] for c in text], dtype=np.uint16)

    # 按位置切分而不是随机切分：语言模型的样本是滑动窗口，
    # 随机切会让验证集的上文出现在训练集里，泄漏。
    split = int(len(ids) * (1 - val_ratio))
    np.save(DATA / "train.npy", ids[:split])
    np.save(DATA / "val.npy", ids[split:])
    (DATA / "meta.json").write_text(
        json.dumps({"vocab_size": len(chars), "itos": itos, "stoi": stoi}, ensure_ascii=False)
    )

    print(f"语料字符数   : {len(text):,}")
    print(f"词表大小     : {len(chars)}")
    print(f"词表内容     : {''.join(chars)!r}")
    print(f"train tokens : {split:,}")
    print(f"val   tokens : {len(ids) - split:,}")
    print(f"每 token 平均覆盖字符数 : {len(text) / len(ids):.2f}")


def load_meta() -> dict:
    meta = json.loads((DATA / "meta.json").read_text())
    meta["itos"] = {int(k): v for k, v in meta["itos"].items()}
    return meta


def encode(s: str, stoi: dict) -> list[int]:
    return [stoi[c] for c in s]


def decode(ids, itos: dict) -> str:
    return "".join(itos[int(i)] for i in ids)


if __name__ == "__main__":
    build()
