"""
Servidor web do HomeNOC: entrega a interface e a API JSON.

Segurança:
- por padrão só escuta no próprio computador (127.0.0.1);
- o acesso pelo celular é opcional, exige senha e sessão por cookie;
- pedidos que alteram algo precisam do cabeçalho X-HomeNOC (bloqueia sites
  maliciosos abertos no navegador de enviar comandos: CSRF);
- o cabeçalho Host é conferido (bloqueia "DNS rebinding").
"""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import socket
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, acesso
from .config import ErroConfig
from .rede import WINDOWS

log = logging.getLogger("homenoc")
WEB = Path(__file__).resolve().parent / "web"
COOKIE = "homenoc_sessao"
TIPOS = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".woff2": "font/woff2",
         ".webmanifest": "application/manifest+json", ".png": "image/png", ".json": "application/json"}
ABERTAS = {"/api/saude", "/api/sessao", "/api/login"}     # respondem sem login
MAX_CORPO = 64 * 1024


class ErroHTTP(Exception):
    def __init__(self, codigo: int, mensagem: str) -> None:
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


class Servidor(ThreadingHTTPServer):
    daemon_threads = True
    # No Windows, SO_REUSEADDR deixaria duas cópias do HomeNOC na mesma porta.
    allow_reuse_address = not WINDOWS


_cache_hosts: dict = {"em": 0.0, "nomes": set()}


def hosts_permitidos(app) -> set[str]:
    """Nomes pelos quais o HomeNOC pode ser acessado (o resto é bloqueado)."""
    if time.monotonic() - _cache_hosts["em"] < 60:
        nomes = set(_cache_hosts["nomes"])
    else:
        nomes = {"127.0.0.1", "localhost", "::1", "[::1]"}
        try:
            host = socket.gethostname()
            nomes.update({host.lower(), f"{host.lower()}.local", f"{host.lower()}.lan"})
            nomes.update(socket.gethostbyname_ex(host)[2])
        except OSError:
            pass
        _cache_hosts.update(em=time.monotonic(), nomes=set(nomes))
    ip = (app.rede_info or {}).get("ip")
    if ip:
        nomes.add(ip)
    return nomes


def criar_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"HomeNOC/{__version__}"
        protocol_version = "HTTP/1.1"

        # ---------------- utilitários ----------------

        def log_message(self, formato, *args):    # silencioso: o log do app já registra o que importa
            pass

        @property
        def cliente(self) -> str:
            return self.client_address[0]

        @property
        def local(self) -> bool:
            return acesso.eh_local(self.cliente)

        def _cookie(self) -> str | None:
            bruto = self.headers.get("Cookie")
            if not bruto:
                return None
            try:
                c = SimpleCookie(bruto)
            except Exception:  # noqa: BLE001
                return None
            return c[COOKIE].value if COOKIE in c else None

        def _enviar(self, codigo: int, corpo: bytes, tipo: str, extras: dict | None = None) -> None:
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            for k, v in (extras or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(corpo)

        def _json(self, codigo: int, dados, extras: dict | None = None) -> None:
            corpo = json.dumps(dados, ensure_ascii=False, default=str).encode("utf-8")
            self._enviar(codigo, corpo, "application/json; charset=utf-8",
                         {"Cache-Control": "no-store", **(extras or {})})

        def _ler_bruto(self) -> bytes:
            """Lê o corpo logo no início: assim uma resposta de erro não deixa bytes perdidos na conexão."""
            try:
                tamanho = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                tamanho = -1
            if tamanho < 0 or tamanho > MAX_CORPO:
                self.close_connection = True
                if tamanho > MAX_CORPO:
                    raise ErroHTTP(413, "Pedido grande demais.")
                raise ErroHTTP(400, "Pedido inválido.")
            return self.rfile.read(tamanho) if tamanho else b""

        def _corpo(self) -> dict:
            if not self._bruto:
                return {}
            try:
                dados = json.loads(self._bruto.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise ErroHTTP(400, "JSON inválido.") from None
            if not isinstance(dados, dict):
                raise ErroHTTP(400, "Esperava um objeto JSON.")
            return dados

        def _checar_host(self) -> None:
            host = (self.headers.get("Host") or "").strip().lower()
            if not host:
                return
            nome = host.rsplit(":", 1)[0] if not host.endswith("]") else host
            if nome not in hosts_permitidos(app):
                raise ErroHTTP(403, "Endereço não permitido.")

        def _autenticado(self) -> bool:
            return self.local or app.sessoes.valida(self._cookie())

        # ---------------- roteamento ----------------

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            self._tratar("GET")

        def do_POST(self):
            self._tratar("POST")

        def _tratar(self, metodo: str) -> None:
            self._bruto = b""
            try:
                if metodo == "POST":
                    self._bruto = self._ler_bruto()
                self._checar_host()
                url = urllib.parse.urlsplit(self.path)
                caminho = url.path
                params = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}
                if not caminho.startswith("/api/"):
                    if metodo != "GET":
                        raise ErroHTTP(405, "Método não permitido.")
                    return self._estatico(caminho)
                if not self.local and not app.config.get()["acesso"]["rede_local"]:
                    raise ErroHTTP(403, "Acesso pela rede desativado.")
                if caminho not in ABERTAS and not self._autenticado():
                    raise ErroHTTP(401, "login")
                if metodo == "POST" and self.headers.get("X-HomeNOC") != "1":
                    raise ErroHTTP(403, "Pedido sem o cabeçalho do HomeNOC.")
                corpo = self._corpo() if metodo == "POST" else {}
                self._api(metodo, caminho, params, corpo)
            except ErroHTTP as e:
                self._json(e.codigo, {"erro": e.mensagem})
            except ErroConfig as e:
                self._json(400, {"erro": str(e)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                log.exception("Erro na API: %s %s", metodo, self.path)
                try:
                    self._json(500, {"erro": "Erro interno. Veja o arquivo dados/homenoc.log."})
                except OSError:
                    pass

        def _estatico(self, caminho: str) -> None:
            nome = "index.html" if caminho in ("/", "/index.html") else caminho.lstrip("/")
            if not re.fullmatch(r"(fonts/)?[\w.-]+", nome):
                raise ErroHTTP(404, "Não encontrado.")
            arquivo = (WEB / nome).resolve()
            if WEB.resolve() not in arquivo.parents or not arquivo.is_file():
                raise ErroHTTP(404, "Não encontrado.")
            tipo = TIPOS.get(arquivo.suffix, mimetypes.guess_type(arquivo.name)[0] or "application/octet-stream")
            cache = "public, max-age=604800" if arquivo.suffix == ".woff2" else "no-cache"
            self._enviar(200, arquivo.read_bytes(), tipo, {"Cache-Control": cache})

        def _api(self, metodo: str, caminho: str, params: dict, corpo: dict) -> None:
            r = (metodo, caminho)
            if r == ("GET", "/api/saude"):
                return self._json(200, {"app": "HomeNOC", "versao": __version__})
            if r == ("GET", "/api/sessao"):
                cfg = app.config.get()["acesso"]
                return self._json(200, {"local": self.local, "autenticado": self._autenticado(),
                                        "senha_definida": bool(cfg["senha_hash"])})
            if r == ("POST", "/api/login"):
                return self._login(corpo)
            if r == ("POST", "/api/sair"):
                app.sessoes.encerrar(self._cookie())
                return self._json(200, {"ok": True}, {"Set-Cookie": f"{COOKIE}=; Max-Age=0; Path=/; SameSite=Strict"})
            if r == ("GET", "/api/estado"):
                return self._json(200, app.estado(local=self.local))
            if r == ("GET", "/api/historico"):
                return self._json(200, app.historico(params.get("alvo", "internet"), _periodo(params)))
            if r == ("GET", "/api/trafego"):
                return self._json(200, app.dados_trafego(_periodo(params)))
            if r == ("GET", "/api/eventos"):
                tipos = [t for t in (params.get("tipos") or "").split(",") if t] or None
                antes = int(params["antes"]) if (params.get("antes") or "").isdigit() else None
                limite = int(params["limite"]) if (params.get("limite") or "").isdigit() else 60
                return self._json(200, app.banco.eventos(limite, antes, tipos, params.get("alvo") or None))
            if r == ("GET", "/api/dispositivos.csv"):
                corpo_csv = app.inventario_csv().encode("utf-8-sig")
                return self._enviar(200, corpo_csv, "text/csv; charset=utf-8",
                                    {"Content-Disposition": 'attachment; filename="homenoc-aparelhos.csv"',
                                     "Cache-Control": "no-store"})
            if r == ("GET", "/api/config"):
                return self._json(200, app.config.mascarado())
            if r == ("POST", "/api/config"):
                return self._json(200, app.salvar_config(corpo, local=self.local))
            if r == ("POST", "/api/varrer"):
                app.varrer_agora()
                return self._json(202, {"ok": True})
            if r == ("POST", "/api/alertas/teste"):
                return self._json(200, {"resultados": app.testar_alertas(corpo)})
            if r == ("POST", "/api/alertas/chat-id"):
                return self._json(200, app.descobrir_chat_id(corpo))
            if r == ("POST", "/api/zabbix/teste"):
                return self._json(200, app.testar_zabbix(corpo))
            if r == ("POST", "/api/acesso"):
                if not self.local:
                    raise ErroHTTP(403, "O acesso pela rede só pode ser alterado no computador do HomeNOC.")
                return self._json(200, app.definir_acesso(corpo))
            if r == ("POST", "/api/autostart"):
                if not self.local:
                    raise ErroHTTP(403, "Só pode ser alterado no computador do HomeNOC.")
                return self._json(200, app.definir_autostart(bool(corpo.get("ativo"))))
            if r == ("POST", "/api/encerrar"):
                if not self.local:
                    raise ErroHTTP(403, "Só pode ser feito no computador do HomeNOC.")
                self._json(200, {"ok": True})
                return app.encerrar_em_breve()
            m = re.fullmatch(r"/api/dispositivos/([^/]+)(/portas)?", caminho)
            if m and metodo == "POST":
                id_ = urllib.parse.unquote(m.group(1))
                if m.group(2):
                    if not app.escanear_portas(id_):
                        raise ErroHTTP(404, "Aparelho não encontrado.")
                    return self._json(202, {"ok": True})
                dispositivo = app.atualizar_dispositivo(id_, corpo)
                if dispositivo is None:
                    raise ErroHTTP(404, "Aparelho não encontrado.")
                return self._json(200, dispositivo)
            raise ErroHTTP(404, "Rota não encontrada.")

        def _login(self, corpo: dict) -> None:
            cfg = app.config.get()["acesso"]
            if app.sessoes.bloqueado(self.cliente):
                raise ErroHTTP(429, "Muitas tentativas. Espere 5 minutos.")
            if not acesso.conferir_senha(str(corpo.get("senha") or ""), cfg["senha_hash"], cfg["sal"]):
                app.sessoes.registrar_falha(self.cliente)
                time.sleep(0.8)
                raise ErroHTTP(401, "Senha incorreta.")
            token = app.sessoes.criar()
            cookie = (f"{COOKIE}={token}; Max-Age={acesso.DURACAO_SESSAO_S}; Path=/; HttpOnly; SameSite=Strict")
            return self._json(200, {"ok": True}, {"Set-Cookie": cookie})

    return Handler


def _periodo(params: dict) -> int:
    try:
        valor = int(params.get("periodo") or 86400)
    except ValueError:
        valor = 86400
    return max(600, min(valor, 31 * 86400))


class ServidorWeb:
    """Liga o servidor e permite trocar de 127.0.0.1 para a rede (e de volta) sem reiniciar o app."""

    def __init__(self, app, porta: int) -> None:
        self.app = app
        self.porta = porta
        self.httpd: Servidor | None = None
        self.host: str | None = None
        self.lock = threading.Lock()

    def iniciar(self, host: str) -> None:
        httpd = Servidor((host, self.porta), criar_handler(self.app))
        self.httpd, self.host = httpd, host
        threading.Thread(target=httpd.serve_forever, name="web", daemon=True).start()
        log.info("Interface em http://%s:%d", "127.0.0.1" if host == "127.0.0.1" else host, self.porta)

    def trocar_host(self, host: str) -> None:
        def trocar():
            time.sleep(0.6)                       # deixa a resposta atual sair
            with self.lock:
                if host == self.host:
                    return
                antigo = self.httpd
                if antigo:
                    antigo.shutdown()
                    antigo.server_close()
                try:
                    self.iniciar(host)
                except OSError as exc:
                    log.error("Não consegui escutar em %s:%d (%s); voltando ao modo local.", host, self.porta, exc)
                    self.iniciar("127.0.0.1")
        threading.Thread(target=trocar, daemon=True).start()

    def parar(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
