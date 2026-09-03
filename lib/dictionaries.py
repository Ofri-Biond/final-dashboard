from collections import Counter
from pathlib import Path

import yaml


class Dictionary:
    """One canonical-value map, built from a YAML file. Records what it could not map."""

    def __init__(self, name: str, mapping: dict[str, list[str]]):
        self.name = name
        self._canonical_by_raw: dict[str, str] = {}
        for canonical, raw_values in mapping.items():
            for raw in raw_values:
                self._canonical_by_raw[raw.strip().lower()] = canonical
        self.unmapped: Counter[str] = Counter()

    def map(self, raw: str) -> str:
        canonical = self._canonical_by_raw.get(raw.strip().lower())
        if canonical is None:
            self.unmapped[raw] += 1
            return raw
        return canonical


def load_dictionaries(dictionaries_dir: Path) -> dict[str, Dictionary]:
    dictionaries = {}
    for path in sorted(dictionaries_dir.glob("*.yaml")):
        with open(path) as f:
            mapping = yaml.safe_load(f)
        dictionaries[path.stem] = Dictionary(path.stem, mapping)
    return dictionaries


def write_unmapped_log(dictionaries: dict[str, Dictionary], path: Path) -> None:
    rows = [
        {"dictionary": name, "value": value, "count": count}
        for name, dictionary in dictionaries.items()
        for value, count in dictionary.unmapped.most_common()
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write("dictionary,value,count\n")
        for row in rows:
            value = row["value"].replace('"', '""')
            f.write(f'{row["dictionary"]},"{value}",{row["count"]}\n')
