"""Copy a stopped HelpFlow database into an EMPTY target; preserve IDs and source."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, inspect, select, func, text
from flask_migrate import upgrade
from alembic.script import ScriptDirectory
from helpflow import create_app
from helpflow.extensions import db


def normalize(uri):
    if uri.startswith(('postgres://', 'postgresql://')):
        return 'postgresql+psycopg://' + uri.split('://', 1)[1]
    return uri


def transfer(source_uri, target_uri):
    source_uri, target_uri = normalize(source_uri), normalize(target_uri)
    if source_uri == target_uri:
        raise ValueError('Origem e destino devem ser diferentes.')
    source = create_engine(source_uri, pool_pre_ping=True)
    target = create_engine(target_uri, pool_pre_ping=True)
    root = Path(__file__).resolve().parents[1]
    head = ScriptDirectory(str(root / 'migrations')).get_current_head()
    try:
        if source.url == target.url:
            raise ValueError('Origem e destino devem ser diferentes.')
        with source.connect() as conn:
            version = conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
            if version != head:
                raise ValueError('Atualize as migrações da origem antes de copiar.')
        allowed = set(db.metadata.tables) | {'alembic_version'}
        tables = inspect(target).get_table_names()
        if set(tables) - allowed:
            raise ValueError('O destino contém tabelas de outro sistema.')
        with target.connect() as conn:
            for name in tables:
                if name != 'alembic_version' and conn.execute(select(func.count()).select_from(db.metadata.tables[name])).scalar_one():
                    raise ValueError('O destino já contém dados. Nada foi substituído.')
        app = create_app({'SQLALCHEMY_DATABASE_URI': target_uri, 'RATELIMIT_ENABLED': False})
        with app.app_context():
            upgrade()
            db.session.remove()
            db.engine.dispose()
        totals = {}
        with source.connect() as src, target.begin() as dest:
            if source.dialect.name == 'sqlite':
                src.exec_driver_sql('BEGIN')
            else:
                src = src.execution_options(isolation_level='REPEATABLE READ')
                src.begin()
            for table in db.metadata.sorted_tables:
                rows = [dict(row) for row in src.execute(select(table)).mappings()]
                if table.name == 'location':
                    pending, rows, inserted = rows, [], set()
                    while pending:
                        ready = [r for r in pending if r['parent_id'] is None or r['parent_id'] in inserted]
                        if not ready:
                            raise ValueError('Hierarquia de locais inválida na origem.')
                        rows.extend(ready)
                        inserted.update(r['id'] for r in ready)
                        pending = [r for r in pending if r['id'] not in inserted]
                # Sequential rows keep self-referential location FKs valid on both engines.
                for row in rows:
                    dest.execute(table.insert().values(**row))
                count = dest.execute(select(func.count()).select_from(table)).scalar_one()
                if count != len(rows):
                    raise ValueError(f'Contagem divergente em {table.name}.')
                totals[table.name] = count
                if target.dialect.name == 'postgresql' and rows:
                    quoted = target.dialect.identifier_preparer.quote(table.name)
                    dest.execute(text("SELECT setval(pg_get_serial_sequence(:table_name, 'id'), :last_id, true)"),
                                 {'table_name': quoted, 'last_id': max(r['id'] for r in rows)})
            src.rollback()
        return totals
    finally:
        source.dispose()
        target.dispose()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-stopped', action='store_true', help='Confirma que web e worker estão parados durante a cópia')
    args = parser.parse_args()
    if not args.confirm_stopped:
        parser.error('Pare web/worker, faça backup e use --confirm-stopped.')
    if not os.getenv('SOURCE_DATABASE_URL') or not os.getenv('TARGET_DATABASE_URL'):
        parser.error('Configure SOURCE_DATABASE_URL e TARGET_DATABASE_URL. Credenciais não são impressas.')
    try:
        for table, count in transfer(os.environ['SOURCE_DATABASE_URL'], os.environ['TARGET_DATABASE_URL']).items():
            print(f'{table}: {count} registros verificados')
        print('Cópia concluída. Origem preservada. Copie também instance/uploads e só então altere DATABASE_URL.')
    except Exception as error:
        print(f'Cópia interrompida ({type(error).__name__}). Confira versões, destino vazio e conexão. Origem preservada.', file=sys.stderr)
        sys.exit(1)
