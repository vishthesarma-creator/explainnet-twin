"""Archive prior native root evidence after its recorded scoped cleanup."""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    done = []
    for folder in (ROOT / 'artifacts/stage11').iterdir():
        receipt = folder / 'cleanup.json'
        if not receipt.exists() or (folder / 'root_archive').exists():
            continue
        cleanup = json.loads(receipt.read_text())
        assert cleanup['owned_bridges_removed'] and cleanup['preexisting_bridges_preserved']
        expected = Path('/var/lib') / ('explainnet-stage11-' + folder.name)
        assert expected == Path(cleanup['root_state_directory']) and expected.parent == Path('/var/lib')
        if expected.exists():
            shutil.copytree(expected, folder / 'root_archive')
            done.append(folder.name)
    print(json.dumps({'prior_native_archives_copied': done}))


if __name__ == '__main__':
    main()
