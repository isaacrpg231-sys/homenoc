"""
Monitoramento de perto (a cada minuto): a internet e os aparelhos marcados com
"Avisar quando cair".

A cada ciclo:
  1. pinga os servidores externos e os aparelhos monitorados, em paralelo;
  2. se algo que estava no ar parece ter caído, espera alguns segundos e testa
     de novo antes de acusar (evita alarme falso por um pacote perdido);
  3. grava a latência no histórico;
  4. compara com o ciclo anterior e registra o que caiu e o que voltou;
  5. manda o alerta (ou deixa na fila, se a internet estiver fora).

A internet só é considerada fora do ar se NENHUM servidor externo responder.
"""

from __future__ import annotations

import logging
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from . import rede
from .descoberta import nome_exibicao

log = logging.getLogger("homenoc")
CHAVE_INTERNET = "internet"
ESTADO_TRANSICOES = "monitor.transicoes"


@dataclass
class Alvo:
    chave: str          # 'wan:8.8.8.8' ou 'dispositivo:<id>'
    nome: str
    host: str
    tipo: str           # 'wan' ou 'lan'
    dispositivo_id: str | None = None

    @property
    def rotulo(self) -> str:
        return f"{self.nome} ({self.host})"


@dataclass
class Resultado:
    alvo: Alvo
    online: bool
    ms: float | None = None
    tentativas: int = 1


@dataclass
class Mudanca:
    chave: str
    rotulo: str
    online: bool                 # estado novo
    duracao_s: float | None      # quanto tempo ficou no estado anterior (None = 1ª verificação)
    ms: float | None = None
    detalhe: str = ""


class Pinger:
    def __init__(self, tentativas: int = 2, timeout_ms: int = 1000, ping_fn=None) -> None:
        self.tentativas = tentativas
        self.timeout_ms = timeout_ms
        self.ping_fn = ping_fn

    def pingar(self, alvos: list[Alvo]) -> dict[str, Resultado]:
        if not alvos:
            return {}

        def um(alvo: Alvo) -> Resultado:
            ok, ms, _, n = rede.ping_tentativas(alvo.host, self.tentativas, self.timeout_ms, ping_fn=self.ping_fn)
            return Resultado(alvo, ok, ms, n)

        with ThreadPoolExecutor(max_workers=min(16, len(alvos))) as pool:
            return {r.alvo.chave: r for r in pool.map(um, alvos)}


def formatar_duracao(segundos: float | None) -> str:
    if segundos is None:
        return "?"
    minutos = round(segundos / 60)
    if minutos < 1:
        return "menos de 1 min"
    horas, minutos = divmod(minutos, 60)
    dias, horas = divmod(horas, 24)
    if dias:
        return f"{dias} d {horas} h"
    if horas:
        return f"{horas} h {minutos:02d} min"
    return f"{minutos} min"


class Monitor:
    def __init__(self, banco, config, alertas, pinger=None, relogio=time.time, dormir=time.sleep,
                 hostname: str | None = None) -> None:
        self.banco = banco
        self.config = config
        self.alertas = alertas
        self.pinger = pinger
        self.relogio = relogio
        self.dormir = dormir
        self.hostname = hostname or socket.gethostname()
        self.ip_local_fn = rede.ip_local
        self.status: dict = {"ultimo_ciclo": None, "internet": None, "monitorados": 0}

    # ---------- alvos ----------

    def alvos(self, cfg: dict) -> tuple[list[Alvo], list[Alvo]]:
        wan = [Alvo(f"wan:{h}", rede.NOMES_CONHECIDOS.get(h, h), h, "wan") for h in cfg["internet"]["alvos"]]
        meu_ip = self.ip_local_fn()
        lan = [Alvo(f"dispositivo:{d['id']}", nome_exibicao(d), d["ip"], "lan", d["id"])
               for d in self.banco.dispositivos()
               if d["alertar"] and d.get("ip") and d["ip"] != meu_ip]
        return wan, lan

    def _pinger(self, cfg: dict):
        if self.pinger is not None:
            return self.pinger
        return Pinger(cfg["monitor"]["tentativas"], cfg["monitor"]["timeout_ms"])

    # ---------- ciclo ----------

    def ciclo(self) -> None:
        cfg = self.config.get()
        pinger = self._pinger(cfg)
        trans = self.banco.estado(ESTADO_TRANSICOES, {}) or {}
        wan, lan = self.alvos(cfg)
        resultados = pinger.pingar(wan + lan)
        resultados = self._confirmar(resultados, wan, lan, trans, cfg, pinger)
        internet = any(resultados[a.chave].online for a in wan) if wan else None
        melhor = min((resultados[a.chave].ms for a in wan
                      if resultados[a.chave].online and resultados[a.chave].ms is not None), default=None)
        agora = self.relogio()

        pares = [(a.chave if a.tipo == "wan" else f"dispositivo:{a.dispositivo_id}",
                  resultados[a.chave].ms if resultados[a.chave].online else None) for a in wan + lan]
        if wan:
            pares.append((CHAVE_INTERNET, melhor if internet else None))
        self.banco.registrar_amostras(agora, pares)

        mudancas: list[Mudanca] = []
        for a in lan:
            r = resultados[a.chave]
            m = self._transicao(trans, a.chave, a.rotulo, r.online, agora, r.ms)
            campos = {"online": r.online, "latencia": r.ms, "mudou_em": trans[a.chave]["desde"]}
            if r.online:
                campos["ultima_vez"] = agora
                campos["ausencias"] = 0
            self.banco.atualizar_dispositivo(a.dispositivo_id, **campos)
            if m:
                mudancas.append(m)
        if internet is not None:
            m = self._transicao(trans, CHAVE_INTERNET, "Internet", internet, agora, melhor)
            if m:
                if not m.online:
                    m.detalhe = "nenhum servidor externo respondeu"
                mudancas.append(m)
        self.banco.definir_estado(ESTADO_TRANSICOES, trans)
        self._registrar_log(resultados, wan, lan, internet)
        for m in mudancas:
            self._registrar_evento(m, agora)

        avisar = [m for m in mudancas if m.chave != CHAVE_INTERNET or cfg["internet"]["alertar"]]
        if avisar:
            self.alertas.enfileirar(self._formatar(avisar, resultados, lan, agora), self._resumo(avisar))
        if internet is False:   # sem internet não adianta tentar enviar (e o DNS pode demorar a falhar)
            pendentes = len(self.banco.fila())
            if pendentes:
                log.info("ALERTA | %d na fila, aguardando a internet voltar.", pendentes)
        else:
            self.alertas.enviar_fila()
            self.alertas.sinal_de_vida()

        estado_internet = None
        if internet is not None:
            estado_internet = {
                "online": internet, "ms": melhor, "desde": trans[CHAVE_INTERNET]["desde"],
                "servidores": [{"host": a.host, "nome": a.nome, "online": resultados[a.chave].online,
                                "ms": resultados[a.chave].ms} for a in wan],
            }
        self.status = {"ultimo_ciclo": agora, "internet": estado_internet, "monitorados": len(lan)}

    def ciclo_seguro(self) -> bool:
        try:
            self.ciclo()
            return True
        except Exception:  # um erro inesperado não pode derrubar o monitor
            log.exception("Erro inesperado no ciclo do monitor")
            return False

    # ---------- etapas ----------

    def _confirmar(self, resultados, wan, lan, trans, cfg, pinger):
        """Antes de alertar uma queda, espera e testa de novo os suspeitos."""
        estava = lambda chave: trans.get(chave, {}).get("status", "online") == "online"  # noqa: E731
        suspeitos = [a for a in lan if not resultados[a.chave].online and estava(a.chave)]
        nomes = [a.nome for a in suspeitos]
        if wan and estava(CHAVE_INTERNET) and not any(resultados[a.chave].online for a in wan):
            suspeitos += wan
            nomes.append("Internet")
        espera = cfg["monitor"]["confirmacao_s"]
        if not suspeitos or espera <= 0:
            return resultados
        log.info("Possível queda (%s); testando de novo em %g s antes de alertar...", ", ".join(nomes), espera)
        self.dormir(espera)
        segunda = pinger.pingar(suspeitos)
        for a in suspeitos:
            if segunda[a.chave].online:
                log.info("%s respondeu na confirmação (falha momentânea).", a.rotulo)
        return {**resultados, **segunda}

    @staticmethod
    def _transicao(trans: dict, chave: str, rotulo: str, online: bool, agora: float,
                   ms: float | None) -> Mudanca | None:
        status = "online" if online else "offline"
        anterior = trans.get(chave) or {}
        if anterior.get("status") == status:
            return None
        trans[chave] = {"status": status, "desde": agora}
        if not anterior:                      # primeira vez: só avisa se já começou fora
            return None if online else Mudanca(chave, rotulo, online, None)
        desde = anterior.get("desde")
        duracao = agora - desde if isinstance(desde, (int, float)) else None
        return Mudanca(chave, rotulo, online, duracao, ms)

    def _registrar_log(self, resultados, wan, lan, internet) -> None:
        for a in wan + lan:
            r = resultados[a.chave]
            situacao = f"ONLINE  {r.ms:7.1f} ms" if r.online and r.ms is not None else (
                "ONLINE " if r.online else f"OFFLINE (sem resposta em {r.tentativas} tentativa(s))")
            log.info("%s | %-18s | %-15s | %s", a.tipo.upper(), a.nome[:18], a.host, situacao)
        if internet is not None:
            respondeu = sum(resultados[a.chave].online for a in wan)
            log.info("WAN | %-18s | %-15s | %s | %d de %d servidores responderam", "INTERNET", "-",
                     "ONLINE " if internet else "OFFLINE", respondeu, len(wan))

    def _registrar_evento(self, m: Mudanca, agora: float) -> None:
        alvo = m.chave                        # "internet" ou "dispositivo:<id>"
        if m.online:
            detalhe = f"Ficou fora por {formatar_duracao(m.duracao_s)}." if m.duracao_s is not None else ""
            log.info("EVENTO | %s VOLTOU (ficou fora por %s)", m.rotulo, formatar_duracao(m.duracao_s))
            self.banco.evento("volta", f"{m.rotulo} voltou", detalhe, alvo=alvo, gravidade="ok", ts=agora)
        else:
            log.warning("EVENTO | %s CAIU", m.rotulo)
            self.banco.evento("queda", f"{m.rotulo} caiu", m.detalhe, alvo=alvo, gravidade="critico", ts=agora)

    @staticmethod
    def _resumo(mudancas: list[Mudanca]) -> str:
        quedas = [m.rotulo for m in mudancas if not m.online]
        voltas = [m.rotulo for m in mudancas if m.online]
        partes = ([f"QUEDA: {', '.join(quedas)}"] if quedas else []) + \
                 ([f"RESTAURADA: {', '.join(voltas)}"] if voltas else [])
        return " | ".join(partes)

    def _formatar(self, mudancas: list[Mudanca], resultados: dict, lan: list[Alvo], agora: float) -> str:
        quedas = [m for m in mudancas if not m.online]
        voltas = [m for m in mudancas if m.online]
        titulo = ("🟡 MUDANÇA NA REDE" if quedas and voltas else
                  "🔴 ALERTA DE REDE" if quedas else "🟢 REDE RESTAURADA")
        linhas = [titulo, ""]
        for m in quedas:
            linhas.append(f"🔴 {m.rotulo}: OFFLINE" + (f" ({m.detalhe})" if m.detalhe else ""))
        for m in voltas:
            extras = []
            if m.duracao_s is not None:
                extras.append(f"ficou fora por {formatar_duracao(m.duracao_s)}")
            if m.ms is not None:
                extras.append(f"{m.ms:.0f} ms")
            linhas.append(f"🟢 {m.rotulo}: ONLINE" + (f" ({', '.join(extras)})" if extras else ""))
        dica = self._diagnostico(quedas, resultados, lan)
        if dica:
            linhas += ["", f"💡 {dica}"]
        linhas += ["", f"🕒 {datetime.fromtimestamp(agora):%d/%m/%Y %H:%M:%S}", f"📍 Monitor: {self.hostname}"]
        return "\n".join(linhas)

    @staticmethod
    def _diagnostico(quedas: list[Mudanca], resultados: dict, lan: list[Alvo]) -> str | None:
        """Uma dica rápida de onde está o problema, como um técnico faria."""
        if not quedas:
            return None
        if resultados and not any(r.online for r in resultados.values()):
            return ("Nada respondeu: pode ser o roteador (energia ou cabos) "
                    "ou a própria conexão deste computador.")
        fora = [a.nome for a in lan if not resultados[a.chave].online]
        if fora:
            return f"Confira energia e cabos de: {', '.join(fora)}."
        if any(resultados[a.chave].online for a in lan):
            return "A rede local responde, então a falha parece ser da operadora. Vale reiniciar o modem/ONT."
        return None
