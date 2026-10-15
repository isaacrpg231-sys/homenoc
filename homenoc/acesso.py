"""
Acesso pelo celular: senha guardada como hash PBKDF2 (nunca em texto) e
sessões por cookie. Quem acessa do próprio computador não precisa de senha.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time

ITERACOES = 200_000
DURACAO_SESSAO_S = 30 * 86400
TENTATIVAS_MAX = 8
BLOQUEIO_S = 300


def hash_senha(senha: str, sal: str | None = None) -> tuple[str, str]:
    sal = sal or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), bytes.fromhex(sal), ITERACOES)
    return h.hex(), sal


def conferir_senha(senha: str, senha_hash: str, sal: str) -> bool:
    if not senha_hash or not sal:
        return False
    calculado, _ = hash_senha(senha, sal)
    return hmac.compare_digest(calculado, senha_hash)


def eh_local(ip: str) -> bool:
    return ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1")


class Sessoes:
    """Sessões guardadas como hash do token (o token em si só existe no cookie)."""

    def __init__(self, banco=None, relogio=time.time) -> None:
        self.banco = banco
        self.relogio = relogio
        self.lock = threading.Lock()
        self.falhas: dict[str, list[float]] = {}
        self.ativas: dict[str, float] = (banco.estado("acesso.sessoes", {}) if banco else {}) or {}

    @staticmethod
    def _h(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _persistir(self) -> None:
        if self.banco:
            self.banco.definir_estado("acesso.sessoes", self.ativas)

    def criar(self) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            agora = self.relogio()
            self.ativas = {k: v for k, v in self.ativas.items() if v > agora}
            self.ativas[self._h(token)] = agora + DURACAO_SESSAO_S
            self._persistir()
        return token

    def valida(self, token: str | None) -> bool:
        if not token:
            return False
        with self.lock:
            expira = self.ativas.get(self._h(token))
            return bool(expira and expira > self.relogio())

    def encerrar(self, token: str | None) -> None:
        if token:
            with self.lock:
                self.ativas.pop(self._h(token), None)
                self._persistir()

    def encerrar_todas(self) -> None:
        with self.lock:
            self.ativas = {}
            self._persistir()

    def bloqueado(self, ip: str) -> bool:
        with self.lock:
            recentes = [t for t in self.falhas.get(ip, []) if t > self.relogio() - BLOQUEIO_S]
            self.falhas[ip] = recentes
            return len(recentes) >= TENTATIVAS_MAX

    def registrar_falha(self, ip: str) -> None:
        with self.lock:
            self.falhas.setdefault(ip, []).append(self.relogio())
