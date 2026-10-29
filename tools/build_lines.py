"""Writes each profile's identity line and "never been inside" line into data/profiles.json ("lines"), so Mantella
reads them ready-made instead of working them out every talk. Run after build_profiles.py.

usage: python tools/build_lines.py        Only stdlib."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))
from lw_knowledge import hookup  # noqa: E402

PATH = os.path.join(ROOT, 'data', 'profiles.json')


def main():
    with open(PATH, encoding='utf-8') as f:
        data = json.load(f)
    for profile in data['profiles'].values():
        profile['lines'] = hookup.identity_text(profile)
    tmp = PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(tmp, PATH)
    print(f"{len(data['profiles'])} profiles with ready-made lines")


if __name__ == '__main__':
    main()
