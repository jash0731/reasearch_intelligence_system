import os
from waitress import serve
from research.app import create_app

app = create_app()

if __name__ == '__main__':
    host = os.getenv('APP_HOST', '127.0.0.1')
    port = int(os.getenv('APP_PORT', '5000'))
    print(f'VIT Research Intelligence System: http://{host}:{port}', flush=True)
    serve(app, host=host, port=port)
