"""
Alertas: Telegram, Discord e o "vigia externo" Healthchecks.io.

Todo alerta entra numa fila salva no banco e só sai quando algum canal confirma
o envio. Se a internet caiu (justamente o que se quer avisar), a mensagem espera
e é entregue assim que a conexão voltar, marcada como enviada com atraso.
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

log = logging.getLogger("homenoc")
USER_AGENT = f"HomeNOC/{__version__}"   # sem User-Agent próprio o Discord (Cloudflare) responde 403
TIMEOUT_S = 10


def http(url: str, dados: bytes | None = None, tipo: str | None = None, timeout: float = TIMEOUT_S) -> bytes:
    cabecalhos = {"User-Agent": USER_AGENT}
    if tipo:
        cabecalhos["Content-Type"] = tipo
    req = urllib.request.Request(url, data=dados, headers=cabecalhos)
    with urllib.request.urlopen(req, timeout=timeout) as resposta:
        return resposta.read()


def descrever_erro(exc: Exception) -> str:
    """Resumo curto do erro, sem expor a URL (que contém o token)."""
    if isinstance(exc, urllib.error.HTTPError):
        detalhe = ""
        try:
            corpo = json.loads(exc.read().decode("utf-8"))
            detalhe = corpo.get("description") or corpo.get("message") or ""
        except Exception:  # noqa: BLE001 - corpo ilegível: usa só o código
            pass
        return f"HTTP {exc.code} {detalhe or exc.reason}".strip()
    if isinstance(exc, urllib.error.URLError):
        return f"sem conexão ({exc.reason})"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "tempo esgotado"
    return f"{type(exc).__name__}: {exc}"


def dica_erro(canal: str, exc: Exception) -> str | None:
    codigo = exc.code if isinstance(exc, urllib.error.HTTPError) else None
    dicas = {
        ("Telegram", 401): "Token inválido: copie de novo o token enviado pelo @BotFather.",
        ("Telegram", 404): "Token inválido: copie de novo o token enviado pelo @BotFather.",
        ("Telegram", 400): "chat_id errado, ou você ainda não mandou /start para o bot.",
        ("Telegram", 403): "O bot está bloqueado nessa conversa: desbloqueie e mande /start.",
        ("Discord", 401): "Webhook inválido ou excluído: gere outro nas configurações do canal.",
        ("Discord", 404): "Webhook inválido ou excluído: gere outro nas configurações do canal.",
    }
    dica = dicas.get((canal, codigo))
    if dica is None and codigo is None and isinstance(exc, (urllib.error.URLError, OSError)):
        dica = "Sem acesso à internet, ou firewall/proxy bloqueando a saída."
    return dica


class Canal:
    """Um canal de alerta. Para criar outro (e-mail, ntfy), herde e implemente enviar()."""

    nome = "?"

    def enviar(self, texto: str) -> None:  # levanta exceção se falhar
        raise NotImplementedError


class Telegram(Canal):
    nome = "Telegram"
    api_base = "https://api.telegram.org"

    def __init__(self, token: str, chat_id: str) -> None:
        self.token = urllib.parse.quote(token, safe=":")
        self.chat_id = chat_id

    def enviar(self, texto: str) -> None:
        corpo = urllib.parse.urlencode({"chat_id": self.chat_id, "text": texto[:4000]}).encode()
        http(f"{self.api_base}/bot{self.token}/sendMessage", corpo, "application/x-www-form-urlencoded")


class Discord(Canal):
    nome = "Discord"

    def __init__(self, webhook: str) -> None:
        self.webhook = webhook

    def enviar(self, texto: str) -> None:
        http(self.webhook, json.dumps({"content": texto[:2000]}).encode(), "application/json")


def canais_de(cfg: dict) -> list[Canal]:
    a = cfg["alertas"]
    canais: list[Canal] = []
    if a["telegram"]["token"] and a["telegram"]["chat_id"]:
        canais.append(Telegram(a["telegram"]["token"], a["telegram"]["chat_id"]))
    if a["discord"]["webhook"]:
        canais.append(Discord(a["discord"]["webhook"]))
    return canais


def descobrir_chat_ids(token: str) -> list[dict]:
    """Conversas que mandaram mensagem ao bot (para escolher o chat_id)."""
    seguro = urllib.parse.quote(token, safe=":")
    dados = json.loads(http(f"{Telegram.api_base}/bot{seguro}/getUpdates"))
    chats: dict[int, str] = {}
    for update in dados.get("result", []):
        for tipo in ("message", "edited_message", "channel_post", "my_chat_member"):
            chat = (update.get(tipo) or {}).get("chat") or {}
            if "id" in chat:
                nome = " ".join(filter(None, (chat.get("first_name"), chat.get("last_name"))))
                chats[chat["id"]] = chat.get("title") or nome or chat.get("username") or ""
    return [{"id": str(i), "nome": n} for i, n in chats.items()]


class Alertas:
    MAX_FILA = 20
    ATRASO_S = 120

    def __init__(self, banco, config, relogio=time.time, canais=None) -> None:
        self.banco = banco
        self.config = config
        self.relogio = relogio
        self._canais_fixos = canais        # usado nos testes
        self.status = {"ultimo_envio": None, "ultimo_erro": None, "healthchecks": None}

    def canais(self) -> list[Canal]:
        return self._canais_fixos if self._canais_fixos is not None else canais_de(self.config.get())

    def enfileirar(self, texto: str, resumo: str) -> bool:
        if not self.canais():
            return False                     # sem canal: o evento já ficou registrado
        self.banco.fila_adicionar(self.relogio(), resumo, texto)
        self.banco.fila_cortar(self.MAX_FILA)
        return True

    def _enviar_em_todos(self, texto: str, canais: list[Canal]) -> tuple[bool, str | None]:
        entregue, erros = False, []
        for canal in canais:
            try:
                canal.enviar(texto)
                entregue = True
            except Exception as exc:  # noqa: BLE001 - um canal com problema não derruba o monitor
                erro = descrever_erro(exc)
                erros.append(f"{canal.nome}: {erro}")
                log.warning("ALERTA | falha no %s: %s", canal.nome, erro)
        return entregue, "; ".join(erros) or None

    def enviar_fila(self) -> int:
        """Envia a fila em ordem; para no primeiro que falhar (tenta de novo no próximo ciclo)."""
        canais = self.canais()
        if not canais:
            self.banco.fila_limpar()
            return 0
        enviados = 0
        for item in self.banco.fila():
            texto = item["texto"]
            if self.relogio() - item["criado_em"] > self.ATRASO_S:
                texto += "\n\n⏳ Enviado com atraso: não havia conexão no momento do evento."
            entregue, erro = self._enviar_em_todos(texto, canais)
            if not entregue:
                self.banco.fila_erro(item["id"], erro or "falha")
                if erro != self.status["ultimo_erro"]:
                    self.banco.evento("alerta", "Falha ao enviar alerta", erro or "", gravidade="aviso",
                                      ts=self.relogio())
                self.status["ultimo_erro"] = erro
                return enviados
            self.banco.fila_remover(item["id"])
            enviados += 1
            self.status.update(ultimo_envio=self.relogio(), ultimo_erro=erro)
            log.info("ALERTA | enviado: %s", item.get("resumo") or "?")
            self.banco.evento("alerta", "Alerta enviado", item.get("resumo") or "", gravidade="info",
                              ts=self.relogio())
        return enviados

    def sinal_de_vida(self) -> None:
        """Avisa o Healthchecks.io que o HomeNOC está vivo. Se o sinal parar, ELE te avisa."""
        url = self.config.get()["alertas"]["healthchecks"]["url"]
        if not url:
            self.status["healthchecks"] = None
            return
        try:
            http(url)
            self.status["healthchecks"] = {"ok": True, "em": self.relogio()}
        except Exception as exc:  # noqa: BLE001
            self.status["healthchecks"] = {"ok": False, "em": self.relogio(), "erro": descrever_erro(exc)}

    def testar(self, cfg: dict | None = None) -> list[dict]:
        """Manda uma mensagem de teste em cada canal configurado e diz o que deu certo."""
        cfg = cfg or self.config.get()
        texto = ("✅ Teste do HomeNOC: os alertas estão funcionando!\n\n"
                 f"🕒 {time.strftime('%d/%m/%Y %H:%M:%S')}\n📍 Monitor: {socket.gethostname()}")
        resultados = []
        for canal in canais_de(cfg):
            try:
                canal.enviar(texto)
                resultados.append({"canal": canal.nome, "ok": True, "mensagem": "Mensagem enviada. Confira o app."})
            except Exception as exc:  # noqa: BLE001
                resultados.append({"canal": canal.nome, "ok": False, "mensagem": descrever_erro(exc),
                                   "dica": dica_erro(canal.nome, exc)})
        url = cfg["alertas"]["healthchecks"]["url"]
        if url:
            try:
                http(url)
                resultados.append({"canal": "Healthchecks.io", "ok": True, "mensagem": "Sinal recebido."})
            except Exception as exc:  # noqa: BLE001
                resultados.append({"canal": "Healthchecks.io", "ok": False, "mensagem": descrever_erro(exc)})
        return resultados

    def resumo(self) -> dict:
        return {"canais": [c.nome for c in self.canais()], "fila": len(self.banco.fila()),
                "healthchecks_configurado": bool(self.config.get()["alertas"]["healthchecks"]["url"]),
                **self.status}
