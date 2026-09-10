"""Validate and extract a SQLite backup to a NEW directory only."""
import argparse
from pathlib import Path, PurePosixPath
import sqlite3
import zipfile
from contextlib import closing


def restore(archive_path, target_path):
    target = Path(target_path).resolve()
    if target.exists():
        raise ValueError('O destino já existe. Escolha uma pasta nova para validar a restauração.')
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if 'helpflow.db' not in archive.namelist():
            raise ValueError('O backup não contém helpflow.db.')
        total = 0
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if '\\' in entry.filename or path.is_absolute() or '..' in path.parts or not (
                entry.filename == 'helpflow.db' or (len(path.parts) == 2 and path.parts[0] == 'uploads')):
                raise ValueError('O arquivo contém um caminho não permitido.')
            total += entry.file_size
            if total > 2 * 1024**3:
                raise ValueError('Backup acima de 2 GB; use restauração administrativa.')
        target.mkdir(parents=True)
        for entry in entries:
            destination = target.joinpath(*PurePosixPath(entry.filename).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, destination.open('xb') as output:
                import shutil
                shutil.copyfileobj(source, output)
    with closing(sqlite3.connect(target / 'helpflow.db')) as database:
        if database.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('O banco restaurado não passou na verificação de integridade.')
        if database.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('O banco restaurado contém referências inválidas.')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup')
    parser.add_argument('new_directory')
    args = parser.parse_args()
    print(f'Backup validado em: {restore(args.backup, args.new_directory)}')
    print('O banco atual não foi modificado. Veja README para iniciar pela cópia restaurada.')
