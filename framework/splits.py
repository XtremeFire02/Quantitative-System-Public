"""
Temporal train / validation / test split.

2-year dataset: 2023-01-01 to 2024-12-31

  Train  : 2023-01-01 to 2023-12-31  (12 months, ~60%)
  Val    : 2024-01-01 to 2024-06-30  (6 months,  ~25%)
  Test   : 2024-07-01 to 2024-12-31  (6 months,  ~25%)

No shuffling — temporal order must be preserved.
"""
import pandas as pd
from typing import Tuple

TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
VAL_END   = pd.Timestamp("2024-07-01", tz="UTC")

SPLIT_LABELS = {
    "train": (None,       TRAIN_END),
    "val":   (TRAIN_END,  VAL_END),
    "test":  (VAL_END,    None),
}


def split(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (train, val, test) DataFrames. Index must be DatetimeTZDtype UTC."""
    train = df[df.index <  TRAIN_END]
    val   = df[(df.index >= TRAIN_END) & (df.index < VAL_END)]
    test  = df[df.index >= VAL_END]
    return train, val, test


def get_split(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """name: 'train' | 'val' | 'test'"""
    start, end = SPLIT_LABELS[name]
    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= df.index >= start
    if end is not None:
        mask &= df.index < end
    return df[mask]


def describe_splits(df: pd.DataFrame) -> None:
    train, val, test = split(df)
    total = len(df)
    for name, part in [("train", train), ("val", val), ("test", test)]:
        print(
            f"  {name:5s}: {len(part):>8,} rows  "
            f"{part.index.min().date()} to {part.index.max().date()}  "
            f"({len(part)/total:.1%})"
        )


if __name__ == "__main__":
    import pandas as pd
    from pathlib import Path
    df = pd.read_parquet(Path("data/processed/funding_premium.parquet"))
    print(f"Full dataset: {len(df):,} rows")
    describe_splits(df)
    print()
    df8 = pd.read_parquet(Path("data/processed/funding_8h.parquet"))
    print(f"8h funding events: {len(df8):,} rows")
    describe_splits(df8)
