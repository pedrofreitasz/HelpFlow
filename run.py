import argparse
import os
import threading
from dotenv import load_dotenv
from helpflow import create_app
from flask_migrate import upgrade
from waitress import serve

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description='HelpFlow — servidor Flask')
    parser.add_argument('--demo', action='store_true', help='Cria dados demo usando DEMO_PASSWORD')
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', '5000')))
    parser.add_argument('--host', default=os.getenv('HOST', '127.0.0.1'))
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        if os.getenv('AUTO_MIGRATE', 'true').lower() == 'true':
            upgrade()
        if args.demo or os.getenv('SEED_DEMO', 'false').lower() == 'true':
            from helpflow.cli import seed_demo
            seed_demo(os.getenv('DEMO_PASSWORD', ''))
    print(f'HelpFlow: http://{args.host}:{args.port}', flush=True)
    if os.getenv('RUN_JOBS_INLINE', 'true').lower() == 'true':
        def jobs():
            from helpflow.cli import check_overdue, check_documents, deliver_mail
            from helpflow.extensions import db
            import time
            while True:
                with app.app_context():
                    try:
                        check_overdue()
                        check_documents()
                        deliver_mail()
                    except Exception:
                        db.session.rollback()
                        app.logger.exception('Falha no processamento de alertas')
                    finally:
                        db.session.remove()
                time.sleep(30)
        threading.Thread(target=jobs, name='helpflow-jobs', daemon=True).start()
    serve(app, host=args.host, port=args.port, threads=4)


if __name__ == '__main__':
    main()
