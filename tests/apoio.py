"""Dublês e utilitários compartilhados pelos testes (nada aqui toca a sua rede)."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,127.0.0.2,localhost"

from homenoc.alertas import Canal
from homenoc.banco import Banco
from homenoc.config import Config
from homenoc.monitor import Resultado


def pasta_temporaria() -> Path:
    return Path(tempfile.mkdtemp(prefix="homenoc-teste-"))


class Relogio:
    """Relógio controlado pelo teste (segundos desde a época)."""

    def __init__(self, inicio: float = 1_791_000_000.0) -> None:
        self.agora = inicio

    def __call__(self) -> float:
        return self.agora

    def avancar(self, minutos: float = 0, segundos: float = 0) -> None:
        self.agora += minutos * 60 + segundos


class PingerFalso:
    """Responde conforme o conjunto `no_ar`. Hosts em `instaveis` falham uma vez e depois respondem."""

    def __init__(self, no_ar: set[str]) -> None:
        self.no_ar = set(no_ar)
        self.instaveis: set[str] = set()
        self.chamadas: list[list[str]] = []

    def pingar(self, alvos):
        self.chamadas.append([a.host for a in alvos])
        resultados = {}
        for a in alvos:
            online = a.host in self.no_ar
            if a.host in self.instaveis:
                online = False
                self.instaveis.discard(a.host)
            resultados[a.chave] = Resultado(a, online, 12.5 if online else None)
        return resultados


class CanalFalso(Canal):
    nome = "Falso"

    def __init__(self) -> None:
        self.enviadas: list[str] = []
        self.quebrado = False

    def enviar(self, texto: str) -> None:
        if self.quebrado:
            raise urllib.error.URLError("rede inacessível")
        self.enviadas.append(texto)


def config_e_banco(pasta: Path | None = None) -> tuple[Config, Banco]:
    pasta = pasta or pasta_temporaria()
    return Config(pasta / "config.json"), Banco(pasta / "homenoc.db")


class ServidorHTTPFalso:
    """Servidor HTTP local que grava os pedidos e responde o que o teste mandar."""

    def __init__(self) -> None:
        self.pedidos: list[dict] = []
        self.status = 200
        self.resposta: bytes = b'{"ok":true}'
        self.tipo = "application/json"
        externo = self

        class Handler(BaseHTTPRequestHandler):
            def _responder(self):
                tamanho = int(self.headers.get("Content-Length", 0))
                externo.pedidos.append({"metodo": self.command, "caminho": self.path,
                                        "cabecalhos": {k.lower(): v for k, v in self.headers.items()},
                                        "corpo": self.rfile.read(tamanho).decode("utf-8", "replace")})
                corpo = externo.resposta(self) if callable(externo.resposta) else externo.resposta
                self.send_response(externo.status)
                self.send_header("Content-Type", externo.tipo)
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            do_GET = do_POST = _responder

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def fechar(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
