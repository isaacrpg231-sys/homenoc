"""
Descoberta da rede: varre a sub-rede, identifica cada aparelho e mantém o
inventário salvo no banco.

Cada aparelho é identificado pelo MAC (quando conhecido), então ele continua
sendo o mesmo aparelho, com o mesmo apelido e histórico, mesmo que o roteador
troque o IP dele.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from . import rede, upnp

log = logging.getLogger("homenoc")

TIPOS = {
    "roteador": "Roteador", "este_pc": "Este computador", "computador": "Computador",
    "celular": "Celular ou tablet", "tv": "TV ou streaming", "impressora": "Impressora",
    "camera": "Câmera", "iot": "Dispositivo IoT", "servidor": "Servidor", "desconhecido": "Aparelho",
}
REVARRER_PORTAS_S = 6 * 3600     # portas mudam pouco: testa de novo a cada 6 h
AUSENCIAS_PARA_SAIR = 2          # varreduras seguidas sem aparecer antes de dizer que saiu


def nome_exibicao(d: dict) -> str:
    """O melhor nome disponível: apelido > UPnP > DNS > tipo + fabricante."""
    if d.get("apelido"):
        return d["apelido"]
    u = d.get("upnp") or {}
    if u.get("nome"):
        return u["nome"]
    if d.get("nome_dns"):
        return d["nome_dns"].split(".")[0]
    tipo = TIPOS.get(d.get("tipo") or "desconhecido", "Aparelho")
    fab = d.get("fabricante")
    if fab and not fab.startswith("MAC aleatório"):
        return f"{tipo} {fab.split()[0]}"
    final = (d.get("ip") or "").rsplit(".", 1)[-1]
    return f"{tipo} .{final}" if final else tipo


@dataclass
class Varredura:
    rede: dict
    hosts: dict[str, dict]          # ip -> {ms, ttl, responde_ping, mac, nome_dns, portas}
    caminho: list[dict] = field(default_factory=list)
    upnp: dict[str, dict] = field(default_factory=dict)
    inicio: float = 0.0
    fim: float = 0.0


class Scanner:
    """Faz a varredura: ping em toda a sub-rede, tabela ARP, nomes, portas, UPnP e tracert."""

    def __init__(self, progresso: Callable[[str, int], None] | None = None) -> None:
        self.progresso = progresso or (lambda etapa, pct: None)

    def varrer(self, testar_portas: Callable[[str, str | None], bool] | bool = True) -> Varredura:
        inicio = time.time()
        self.progresso("lendo a configuração da rede", 2)
        info = rede.rede_local()
        alvos = [str(h) for h in ipaddress.ip_network(info["rede"]).hosts()]

        caminho: list[dict] = []
        aparelhos: dict[str, dict] = {}
        t_tracert = threading.Thread(target=lambda: caminho.extend(rede.tracert()), daemon=True)
        t_upnp = threading.Thread(target=lambda: aparelhos.update(upnp.descobrir_aparelhos()), daemon=True)
        t_tracert.start()
        t_upnp.start()

        respostas: dict[str, tuple] = {}
        with ThreadPoolExecutor(max_workers=64) as pool:
            futuros = {pool.submit(rede.ping, ip, 800): ip for ip in alvos}
            for n, fut in enumerate(as_completed(futuros), 1):
                ok, ms, ttl = fut.result()
                if ok:
                    respostas[futuros[fut]] = (ms, ttl)
                if n % 16 == 0 or n == len(alvos):
                    self.progresso(f"pingando {n} de {len(alvos)} endereços", 5 + int(55 * n / len(alvos)))

        arp = rede.tabela_arp()             # pega também quem bloqueia ping mas respondeu ao ARP
        conjunto = set(alvos)
        vivos = sorted(set(respostas) | {ip for ip in arp if ip in conjunto} | {info["ip"]},
                       key=lambda ip: tuple(int(p) for p in ip.split(".")))
        macs = {ip: arp.get(ip) for ip in vivos}
        macs[info["ip"]] = info.get("mac")

        self.progresso("identificando os aparelhos", 62)
        escanear = [ip for ip in vivos
                    if (testar_portas(ip, macs.get(ip)) if callable(testar_portas) else testar_portas)]
        with ThreadPoolExecutor(max_workers=32) as pool:
            nomes = dict(zip(vivos, pool.map(rede.nome_dns, vivos), strict=True))
            portas = dict(zip(escanear, pool.map(rede.portas_abertas, escanear), strict=True))

        self.progresso("ouvindo anúncios UPnP", 80)
        t_upnp.join(timeout=10)
        self.progresso("traçando o caminho até a internet", 88)
        t_tracert.join(timeout=70)
        if not info.get("gateway") and caminho and caminho[0].get("ip") in vivos:
            info["gateway"] = caminho[0]["ip"]   # sem rota padrão legível: o 1º salto é o roteador

        hosts = {}
        for ip in vivos:
            ms, ttl = respostas.get(ip, (None, None))
            if ip == info["ip"]:
                ms = 0.0
            hosts[ip] = {"ms": ms, "ttl": ttl, "responde_ping": ip in respostas or ip == info["ip"],
                         "mac": macs.get(ip), "nome_dns": nomes.get(ip), "portas": portas.get(ip)}
        return Varredura(info, hosts, list(caminho), dict(aparelhos), inicio, time.time())


class Inventario:
    """Junta cada varredura ao inventário e registra aparelho novo, que saiu ou que voltou."""

    def __init__(self, banco, fabricantes=None, relogio=time.time) -> None:
        self.banco = banco
        self.fabricantes = fabricantes
        self.relogio = relogio

    def precisa_portas(self, ip: str, mac: str | None) -> bool:
        id_ = f"mac:{mac}" if mac else None
        d = (self.banco.dispositivo(id_) if id_ else None) or next(
            (x for x in self.banco.dispositivos() if x.get("ip") == ip), None)
        return not d or not d.get("portas_em") or self.relogio() - d["portas_em"] > REVARRER_PORTAS_S

    def aplicar(self, v: Varredura) -> dict:
        agora = self.relogio()
        existentes = {d["id"]: d for d in self.banco.dispositivos()}
        primeira = not existentes
        por_ip: dict[str, dict] = {}
        for d in sorted(existentes.values(), key=lambda x: x.get("ultima_vez") or 0):
            if d.get("ip"):
                por_ip[d["ip"]] = d               # o visto mais recentemente fica com o IP
        gateway, eu = v.rede.get("gateway"), v.rede.get("ip")
        vistos, novos, pares = set(), [], []

        for ip, h in v.hosts.items():
            mac = h.get("mac")
            id_ = f"mac:{mac}" if mac else None
            d = existentes.get(id_) if id_ else None
            if d is None:
                antigo = por_ip.get(ip)
                if antigo and antigo["id"] not in vistos and (not id_ or antigo["id"].startswith("ip:")):
                    d = antigo                    # mesmo aparelho, visto antes sem MAC (ou agora sem MAC)
                    if id_ and d["id"] != id_:
                        self.banco.renomear_dispositivo(d["id"], id_)
                        self._renomear_transicao(d["id"], id_)
                        existentes.pop(d["id"], None)
                        d["id"] = id_
            novo = d is None
            if novo:
                d = {"id": id_ or f"ip:{ip}", "primeira_vez": agora, "alertar": False, "online": False,
                     "ausencias": 0}
            d = dict(d)
            d["ip"] = ip
            if mac:
                d["mac"] = mac
            d["mac_aleatorio"] = rede.mac_aleatorio(d.get("mac"))
            fabricante = self.fabricantes.nome(d.get("mac")) if self.fabricantes else None
            d["fabricante"] = fabricante or d.get("fabricante")
            d["nome_dns"] = h.get("nome_dns") or d.get("nome_dns")
            d["upnp"] = v.upnp.get(ip) or d.get("upnp")
            if h.get("ttl") is not None:
                d["ttl"] = h["ttl"]
            d["so"] = rede.palpite_so(d.get("ttl"))
            if h.get("portas") is not None:
                d["portas"], d["portas_em"] = h["portas"], agora
            d["responde_ping"] = bool(h.get("responde_ping"))
            d["ausencias"] = 0
            d["ultima_vez"] = agora
            if not d.get("alertar") or ip == eu:      # quem tem "avisar" é acompanhado pelo monitor
                if not d.get("online"):
                    d["mudou_em"] = agora
                    if not novo:
                        self.banco.evento("voltou", f"{nome_exibicao(d)} voltou para a rede", ip,
                                          alvo=f"dispositivo:{d['id']}", gravidade="info", ts=agora)
                d["online"] = True
                d["latencia"] = h.get("ms")
                if h.get("responde_ping"):
                    pares.append((f"dispositivo:{d['id']}", h.get("ms")))
            d["tipo"], d["motivos"] = rede.classificar(d, gateway, eu)
            if novo and ip == gateway:
                d["alertar"] = True                    # o roteador já começa monitorado
                self._iniciar_transicao(d["id"], True, agora)
            self.banco.salvar_dispositivo(d)
            vistos.add(d["id"])
            if novo:
                novos.append(d)
                if not primeira:
                    detalhe = ", ".join(filter(None, [ip, d.get("mac"), d.get("fabricante")]))
                    self.banco.evento("novo", f"Novo aparelho: {nome_exibicao(d)}", detalhe,
                                      alvo=f"dispositivo:{d['id']}", gravidade="aviso", ts=agora)

        for id_, d in existentes.items():
            if id_ in vistos or d.get("alertar") or d.get("ip") == eu:
                continue
            ausencias = (d.get("ausencias") or 0) + 1
            campos = {"ausencias": ausencias}
            if d.get("online") and ausencias >= AUSENCIAS_PARA_SAIR:
                campos.update(online=False, mudou_em=agora, latencia=None)
                self.banco.evento("saiu", f"{nome_exibicao(d)} saiu da rede", d.get("ip") or "",
                                  alvo=f"dispositivo:{id_}", gravidade="info", ts=agora)
                pares.append((f"dispositivo:{id_}", None))
            self.banco.atualizar_dispositivo(id_, **campos)

        self.banco.registrar_amostras(agora, pares)
        if primeira and novos:
            achados = f"{len(novos)} aparelho encontrado" if len(novos) == 1 else f"{len(novos)} aparelhos encontrados"
            self.banco.evento("sistema", f"Primeira varredura: {achados}",
                              v.rede.get("rede", ""), gravidade="info", ts=agora)
        online = sum(1 for d in self.banco.dispositivos() if d.get("online"))
        return {"novos": novos, "total": len(self.banco.dispositivos()), "online": online, "primeira": primeira}

    # ----- integração com o monitor (estado de cada aparelho monitorado) -----

    def _iniciar_transicao(self, id_: str, online: bool, agora: float) -> None:
        trans = self.banco.estado("monitor.transicoes", {}) or {}
        trans.setdefault(f"dispositivo:{id_}", {"status": "online" if online else "offline", "desde": agora})
        self.banco.definir_estado("monitor.transicoes", trans)

    def _renomear_transicao(self, antigo: str, novo: str) -> None:
        trans = self.banco.estado("monitor.transicoes", {}) or {}
        if f"dispositivo:{antigo}" in trans:
            trans[f"dispositivo:{novo}"] = trans.pop(f"dispositivo:{antigo}")
            self.banco.definir_estado("monitor.transicoes", trans)

    def definir_alertar(self, id_: str, alertar: bool) -> dict | None:
        """Liga/desliga o "avisar quando cair" sem disparar um alerta falso na hora."""
        d = self.banco.dispositivo(id_)
        if not d:
            return None
        trans = self.banco.estado("monitor.transicoes", {}) or {}
        chave = f"dispositivo:{id_}"
        if alertar:
            trans[chave] = {"status": "online" if d.get("online") else "offline",
                            "desde": d.get("mudou_em") or self.relogio()}
        else:
            trans.pop(chave, None)
        self.banco.definir_estado("monitor.transicoes", trans)
        self.banco.atualizar_dispositivo(id_, alertar=bool(alertar))
        return self.banco.dispositivo(id_)
