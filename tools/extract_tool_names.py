"""Regenerate src/bbr_ripper/tool_names_generated.py from BattleBit's assets.

BattleBit assigns each ToolItem its index in `Tools.AllTools` at load time.  That
index is the key used by the `/Player/GetStats` per-tool records.  This script
reads the `Tools` ScriptableObject from `resources.assets`, walks the PPtr array,
resolves each entry to its asset name, and writes the mapping.

Usage:
    pip install UnityPy
    python tools/extract_tool_names.py
    python tools/extract_tool_names.py --game-dir "D:\\SteamLibrary\\steamapps\\common\\BattleBit Remastered"
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _load_unitypy():
    try:
        import UnityPy  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "UnityPy is required. Install it with:\n  pip install UnityPy"
        ) from exc
    return UnityPy


def find_tools_asset(env):
    candidates = []
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            name = obj.peek_name()
        except Exception:
            continue
        if name == "Tools":
            candidates.append(obj)
    if not candidates:
        raise SystemExit("Could not find a MonoBehaviour named 'Tools' in resources.assets")
    # The known build uses path_id 37929; prefer it, otherwise the first.
    for obj in candidates:
        if obj.path_id == 37929:
            return obj
    return candidates[0]


def extract_names(env) -> dict[int, str | None]:
    tools = find_tools_asset(env)
    raw = tools.get_raw_data()
    name_len = struct.unpack_from("<I", raw, 28)[0]
    pos = 32 + ((name_len + 3) // 4) * 4
    # EmptyGun and EmptyGadget are two PPtrs (12 bytes each) before AllTools.
    pos += 24
    count = struct.unpack_from("<I", raw, pos)[0]
    pos += 4
    if count > 1000:
        raise SystemExit(f"Implausible AllTools count {count}; the layout changed.")

    by_id = {obj.path_id: obj for obj in env.objects}
    names: dict[int, str | None] = {}
    missing = 0
    for index in range(count):
        _file_id, path_id = struct.unpack_from("<iq", raw, pos)
        pos += 12
        target = by_id.get(path_id)
        if target is None:
            names[index] = None
            missing += 1
            continue
        try:
            names[index] = target.peek_name()
        except Exception:
            names[index] = None
            missing += 1
    if missing:
        print(f"Warning: {missing} AllTools entries had no resolvable name.")
    return names


def pretty(name: str | None) -> str | None:
    if not name or name == "NULL":
        return None
    name = re.sub(r"^\d+_", "", name)
    return name.replace("_", " ")


def write_module(names: dict[int, str | None], output: Path) -> None:
    lines = [
        '"""Generated from BattleBit\'s Tools.AllTools asset. Do not edit by hand.\n',
        "\n",
        "Regenerate with: python tools/extract_tool_names.py\n",
        '"""\n\n',
        "TOOL_NAMES: dict[int, str | None] = {\n",
    ]
    for key in sorted(names):
        lines.append(f"    {key}: {pretty(names[key])!r},\n")
    lines.append("}\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, default=None, help="BattleBit install directory")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "src" / "bbr_ripper" / "tool_names_generated.py",
        help="Output module",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print names without writing")
    args = parser.parse_args()

    if args.game_dir:
        install = args.game_dir
    else:
        from bbr_ripper.steam import find_battlebit

        install = find_battlebit()

    assets = install / "BattleBit_Data" / "resources.assets"
    if not assets.is_file():
        raise SystemExit(f"Not found: {assets}")

    UnityPy = _load_unitypy()
    print(f"Loading {assets} ...")
    env = UnityPy.load(str(assets))
    names = extract_names(env)
    print(f"Extracted {len(names)} tool IDs.")
    for check in (34, 17, 119, 116):
        print(f"  {check:3d} -> {pretty(names.get(check))}")
    if args.dry_run:
        for key in sorted(names):
            print(f"  {key:3d} {pretty(names[key])}")
        return 0
    write_module(names, args.output)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
