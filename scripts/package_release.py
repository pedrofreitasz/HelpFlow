"""Export source only; never include local databases, uploads, secrets or dependencies."""
import argparse
from pathlib import Path
import zipfile


def package(destination):
    root = Path(__file__).resolve().parents[1]
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('O destino já existe. Escolha outro nome.')
    files = [root / name for name in ['README.md', 'requirements.txt', 'requirements.lock.txt',
        'run.py', 'start.ps1', 'Dockerfile', 'compose.yaml', '.env.example', '.gitignore', '.dockerignore']]
    for folder in ['helpflow', 'migrations', 'scripts', 'tests', 'docs']:
        files.extend(path for path in (root / folder).rglob('*') if path.is_file()
                     and '__pycache__' not in path.parts and path.suffix != '.pyc')
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, 'HelpFlow/' + path.relative_to(root).as_posix())
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip():
            raise RuntimeError('O arquivo exportado não passou na verificação.')
    return len(files)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination')
    args = parser.parse_args()
    print(f'{package(args.destination)} arquivos exportados e verificados.')
