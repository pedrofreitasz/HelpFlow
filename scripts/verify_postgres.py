"""Isolated optional PostgreSQL validation. Never installs an OS service or touches external databases."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, text, select, func
from sqlalchemy.engine import URL
from helpflow import create_app
from helpflow.extensions import db
from helpflow.models import Company, Ticket, User
from scripts.transfer_database import transfer


def main():
    root = Path(__file__).resolve().parents[1]
    work = root / 'work'
    runtime = work / 'pg-runtime'
    runtime.mkdir(exist_ok=True)
    with zipfile.ZipFile(work / 'postgresql-17.11-binaries.zip') as archive:
        for info in archive.infolist():
            parts = Path(info.filename).parts
            if len(parts) > 2 and parts[0] == 'pgsql' and parts[1] in ('bin', 'lib', 'share') and '..' not in parts:
                destination = runtime.joinpath(*parts)
                if not destination.exists():
                    if info.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(archive.read(info))
    binary = runtime / 'pgsql' / 'bin'
    run_dir = work / ('pg-check-' + secrets.token_hex(4))
    run_dir.mkdir()
    data_dir = run_dir / 'data'
    data_dir.mkdir()
    password = secrets.token_urlsafe(32)
    pw_file = run_dir / '.password'
    pw_file.write_text(password, encoding='utf-8')
    # PostgreSQL's Windows bootstrap has locale-sensitive handling of accented paths.
    import ctypes
    def short(path):
        buffer = ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer)):
            raise OSError('Não foi possível resolver o caminho curto do teste PostgreSQL.')
        return buffer.value
    base = URL.create('postgresql+psycopg', username='hfcheck', password=password,
                      host='127.0.0.1', port=55439, database='postgres')
    subprocess.run([short(binary / 'initdb.exe'), '-D', short(data_dir), '-U', 'hfcheck',
                    '--auth=scram-sha-256', '--pwfile', short(pw_file), '--encoding=UTF8', '--locale=C'], check=True)
    subprocess.run([short(binary / 'pg_ctl.exe'), '-D', short(data_dir), '-l', short(run_dir) + '/postgres.log',
                    '-o', '-h 127.0.0.1 -p 55439', '-w', 'start'], check=True)
    try:
        admin = create_engine(base, isolation_level='AUTOCOMMIT')
        with admin.connect() as conn:
            conn.execute(text('CREATE DATABASE hf_transfer'))
            print(conn.execute(text('SELECT version()')).scalar_one(), flush=True)
        pg_url = base.set(database='hf_transfer').render_as_string(hide_password=False)
        source = 'sqlite:///' + (root / 'instance/helpflow.db').as_posix()
        counts = transfer(source, pg_url)
        assert counts['ticket'] >= 5
        app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': pg_url,
                          'WTF_CSRF_ENABLED': False, 'RATELIMIT_ENABLED': False})
        with app.app_context():
            saved = db.session.scalar(select(func.count(Ticket.id)))
            company = Company(name='Validação PostgreSQL', slug='pg-sequence-check')
            db.session.add(company)
            db.session.commit()
            assert company.id > 2
            assert db.session.scalar(select(User).where(User.email == 'marina@aurora.com.br')).check_password('HelpFlow2026!')
            db.session.remove()
            db.engine.dispose()
        copied_back = transfer(pg_url, 'sqlite:///' + (run_dir / 'returned.db').as_posix())
        assert copied_back['ticket'] == saved and copied_back['company'] == counts['company'] + 1
        print('SQLite -> PostgreSQL -> SQLite: dados, IDs, sequencias e senhas verificados.', flush=True)
        env = dict(os.environ, TEST_POSTGRESQL_URL=base.render_as_string(hide_password=False))
        result = subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=root, env=env)
        if result.returncode:
            raise RuntimeError('A suíte PostgreSQL apresentou falhas.')
        admin.dispose()
    finally:
        subprocess.run([short(binary / 'pg_ctl.exe'), '-D', short(data_dir), '-m', 'fast', '-w', 'stop'], check=True)
        pw_file.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
