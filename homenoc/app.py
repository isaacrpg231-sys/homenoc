"""
HomeNOC: junta tudo num app só.

Rotinas em segundo plano (cada uma na sua thread):
  descoberta  varre a rede a cada N minutos e atualiza o inventário
  monitor     testa a internet e os aparelhos monitorados a cada minuto
  tráfego     lê os contadores do roteador por UPnP a cada 30 s
  zabbix      busca o estado no Zabbix (se configurado) a cada minuto
  limpeza     apaga o histórico antigo de hora em hora

A interface é servida em http://127.0.0.1:8765 e abre sozinha no navegador.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import logging.handlers
import socket
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

from . import __version__, acesso, alertas, autostart, rede, upnp, zabbix
from .alertas import Alertas
from .banco import Banco
from .config import Config, ErroConfig, normalizar_url_zabbix
from .descoberta import TIPOS, Inventario, Scanner, nome_exibicao
from .fabricantes import Fabricantes
from .monitor import CHAVE_INTERNET, Monitor
from .servidor import ServidorWeb
from .trafego import Trafego

log = logging.getLogger("homenoc")
RAIZ = Path(__file__).resolve().parent.parent
PORTA_PADRAO = 8765
ORDEM_TIPOS = ["roteador", "este_pc", "computador", "servidor", "tv", "celular", "impressora", "camera",
               "iot", "desconhecido"]


def pasta_de_dados(escolhida: str | None = None) -> Path:
    """dados/ ao lado do programa; se não der para escrever lá, a pasta do usuário."""
    candidatos = [Path(escolhida)] if escolhida else [RAIZ / "dados", Path.home() / ".homenoc"]
    for pasta in candidatos:
        try:
            pasta.mkdir(parents=True, exist_ok=True)
            teste = pasta / ".escrita"
            teste.write_text("ok", encoding="utf-8")
            teste.unlink()
            return pasta
        except OSError:
            continue
    return Path(tempfile.mkdtemp(prefix="homenoc-"))


def configurar_log(pasta: Path, console: bool) -> None:
    formato = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")
    log.handlers.clear()
    arquivo = logging.handlers.RotatingFileHandler(pasta / "homenoc.log", maxBytes=1_000_000, backupCount=5,
                                                   encoding="utf-8")
    arquivo.setFormatter(formato)
    log.addHandler(arquivo)
    if console and sys.stderr is not None:
        tela = logging.StreamHandler()
        tela.setFormatter(formato)
        log.addHandler(tela)
    log.setLevel(logging.INFO)
    log.propagate = False


class App:
    def __init__(self, pasta: Path, porta: int = PORTA_PADRAO, baixar_fabricantes: bool = True) -> None:
        self.pasta = Path(pasta)
        self.porta = porta
        self.config = Config(self.pasta / "config.json")
        if self.config.aviso:
            log.warning(self.config.aviso)
        self.banco = Banco(self.pasta / "homenoc.db")
        self.fabricantes = Fabricantes(self.pasta, baixar=baixar_fabricantes)
        self.rede_info: dict = self.banco.estado("rede.info", {}) or {}
        self.caminho: list = self.banco.estado("rede.caminho", []) or []
        self.varredura = {"ativa": False, "etapa": "aguardando", "progresso": 0, "ultima": None,
                          "proxima": None, "duracao_s": None, "erro": None}
        self.scanner = Scanner(progresso=self._progresso)
        self.inventario = Inventario(self.banco, self.fabricantes)
        self.alertas = Alertas(self.banco, self.config)
        self.monitor = Monitor(self.banco, self.config, self.alertas)
        self.roteador = upnp.Roteador(gateway_fn=lambda: self.rede_info.get("gateway"))
        self.trafego = Trafego(self.banco, self.config, self.roteador)
        self.zabbix = zabbix.MonitorZabbix(self.config)
        self.sessoes = acesso.Sessoes(self.banco)
        self.web: ServidorWeb | None = None
        self.escaneando: set[str] = set()
        self.parar = threading.Event()
        self.acordar = {nome: threading.Event() for nome in ("descoberta", "monitor", "trafego", "zabbix")}
        self.iniciado_em = time.time()

    # =================================================================
    # Rotinas
    # =================================================================

    def iniciar_rotinas(self) -> None:
        rotinas = {
            "descoberta": (self.varrer, lambda: self.config.get()["descoberta"]["intervalo_min"] * 60),
            "monitor": (self.monitor.ciclo_seguro, lambda: self.config.get()["monitor"]["intervalo_s"]),
            "trafego": (self.trafego.amostrar, self._intervalo_trafego),
            "zabbix": (self.zabbix.atualizar, lambda: 60 if self.zabbix.configurado() else 300),
        }
        for nome, (funcao, intervalo) in rotinas.items():
            threading.Thread(target=self._laco, args=(nome, funcao, intervalo), name=nome, daemon=True).start()
        threading.Thread(target=self._limpeza, name="limpeza", daemon=True).start()

    def _laco(self, nome: str, funcao, intervalo) -> None:
        while not self.parar.is_set():
            try:
                funcao()
            except Exception:  # uma rotina com erro não derruba o app
                log.exception("Erro na rotina %s", nome)
            evento = self.acordar[nome]
            evento.wait(max(5, intervalo()))
            evento.clear()

    def _intervalo_trafego(self) -> float:
        estado = self.trafego.status["estado"]
        if estado == "indisponivel":
            return 300                          # sem UPnP: tenta de novo a cada 5 min
        if estado == "desligado":
            return 60
        return self.config.get()["trafego"]["intervalo_s"]

    def _limpeza(self) -> None:
        espera = 60                              # a primeira limpeza logo depois de abrir
        while not self.parar.wait(espera):
            try:
                self.banco.limpar(self.config.get()["retencao_dias"])
            except Exception:
                log.exception("Erro na limpeza do histórico")
            espera = 3600

    def _progresso(self, etapa: str, pct: int) -> None:
        self.varredura.update(etapa=etapa, progresso=pct)

    def varrer(self) -> None:
        cfg = self.config.get()
        self.varredura.update(ativa=True, etapa="começando", progresso=0, erro=None)
        try:
            testar = (self.inventario.precisa_portas if cfg["descoberta"]["testar_portas"] else False)
            v = self.scanner.varrer(testar)
            self.rede_info, self.caminho = v.rede, v.caminho
            self.banco.definir_estado("rede.info", v.rede)
            self.banco.definir_estado("rede.caminho", v.caminho)
            resultado = self.inventario.aplicar(v)
            log.info("Varredura: %d aparelhos online (%d novos) em %.0f s", resultado["online"],
                     len(resultado["novos"]), v.fim - v.inicio)
            if cfg["descoberta"]["avisar_novos"] and not resultado["primeira"]:
                for d in resultado["novos"]:
                    self.alertas.enfileirar(self._texto_novo(d), f"NOVO: {nome_exibicao(d)}")
                if resultado["novos"]:
                    self.alertas.enviar_fila()
            self.varredura.update(ultima=time.time(), duracao_s=round(v.fim - v.inicio, 1))
            self.acordar["monitor"].set()         # o roteador pode ter acabado de entrar no monitor
        except Exception as exc:
            self.varredura["erro"] = str(exc)
            raise
        finally:
            intervalo = cfg["descoberta"]["intervalo_min"] * 60
            self.varredura.update(ativa=False, etapa="pronto", progresso=100, proxima=time.time() + intervalo)

    @staticmethod
    def _texto_novo(d: dict) -> str:
        linhas = ["🆕 NOVO APARELHO NA REDE", "", nome_exibicao(d), f"IP: {d.get('ip')}"]
        if d.get("mac"):
            linhas.append(f"MAC: {d['mac']}" + (f" ({d['fabricante']})" if d.get("fabricante") else ""))
        linhas += ["", f"🕒 {datetime.now():%d/%m/%Y %H:%M:%S}", f"📍 Monitor: {socket.gethostname()}"]
        return "\n".join(linhas)

    def varrer_agora(self) -> None:
        if not self.varredura["ativa"]:
            self.acordar["descoberta"].set()

    def escanear_portas(self, id_: str) -> bool:
        d = self.banco.dispositivo(id_)
        if not d or not d.get("ip"):
            return False

        def escanear():
            self.escaneando.add(id_)
            try:
                portas = rede.portas_abertas(d["ip"])
                atual = self.banco.dispositivo(id_) or d
                atual.update(portas=portas, portas_em=time.time())
                atual["tipo"], atual["motivos"] = rede.classificar(atual, self.rede_info.get("gateway"),
                                                                   self.rede_info.get("ip"))
                self.banco.salvar_dispositivo(atual)
            finally:
                self.escaneando.discard(id_)

        threading.Thread(target=escanear, daemon=True).start()
        return True

    # =================================================================
    # Ações vindas da interface
    # =================================================================

    def atualizar_dispositivo(self, id_: str, corpo: dict) -> dict | None:
        if not self.banco.dispositivo(id_):
            return None
        if "apelido" in corpo:
            apelido = " ".join(str(corpo.get("apelido") or "").split())[:40] or None
            self.banco.atualizar_dispositivo(id_, apelido=apelido)
        if "alertar" in corpo:
            self.inventario.definir_alertar(id_, bool(corpo["alertar"]))
            self.acordar["monitor"].set()
        return self._para_tela(self.banco.dispositivo(id_))

    def salvar_config(self, corpo: dict, local: bool) -> dict:
        corpo = {k: v for k, v in corpo.items() if k != "acesso"}
        self.config.atualizar(corpo)
        if "monitor" in corpo or "internet" in corpo:
            self.acordar["monitor"].set()
        if "trafego" in corpo:
            self.acordar["trafego"].set()
        if "zabbix" in corpo:
            self.acordar["zabbix"].set()
        return self.config.mascarado()

    def testar_alertas(self, corpo: dict) -> list[dict]:
        cfg = self.config.previa({"alertas": corpo}) if corpo else self.config.get()
        resultados = self.alertas.testar(cfg)
        if not resultados:
            raise ErroConfig("Preencha o Telegram, o Discord ou o Healthchecks antes de testar.")
        return resultados

    def descobrir_chat_id(self, corpo: dict) -> dict:
        token = str(corpo.get("token") or "")
        if not token or token.startswith("••••"):
            token = self.config.get()["alertas"]["telegram"]["token"]
        if not token:
            raise ErroConfig("Cole primeiro o token que o @BotFather enviou.")
        try:
            chats = alertas.descobrir_chat_ids(token)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "erro": alertas.descrever_erro(exc), "dica": alertas.dica_erro("Telegram", exc)}
        if not chats:
            return {"ok": False, "erro": "Nenhuma conversa encontrada.",
                    "dica": "No Telegram, abra o seu bot, envie /start e tente de novo."}
        return {"ok": True, "chats": chats}

    def testar_zabbix(self, corpo: dict) -> dict:
        salvo = self.config.get()["zabbix"]
        url = normalizar_url_zabbix(str(corpo.get("url") or salvo["url"]))
        token = str(corpo.get("token") or "")
        if not token or token.startswith("••••"):
            token = salvo["token"]
        if not url or not token:
            raise ErroConfig("Preencha o endereço e o token do Zabbix.")
        return zabbix.testar(url, token)

    def definir_acesso(self, corpo: dict) -> dict:
        cfg = self.config.get()["acesso"]
        rede_local = bool(corpo.get("rede_local"))
        senha = corpo.get("senha")
        novo_hash = sal = None
        if senha:
            senha = str(senha)
            if len(senha) < 6:
                raise ErroConfig("A senha precisa ter pelo menos 6 caracteres.")
            novo_hash, sal = acesso.hash_senha(senha)
        if rede_local and not (novo_hash or cfg["senha_hash"]):
            raise ErroConfig("Defina uma senha para liberar o acesso pelo celular.")
        self.config.definir_acesso(rede_local, novo_hash, sal)
        if novo_hash:
            self.sessoes.encerrar_todas()        # senha nova: quem estava logado entra de novo
        if self.web:
            self.web.trocar_host("0.0.0.0" if rede_local else "127.0.0.1")
        return {"ok": True, "rede_local": rede_local, "urls": self._urls_celular(rede_local)}

    def definir_autostart(self, ativo: bool) -> dict:
        ok, mensagem = autostart.ativar() if ativo else autostart.desativar()
        return {"ok": ok, "mensagem": mensagem, "ativo": autostart.ativo()}

    def encerrar_em_breve(self) -> None:
        def encerrar():
            time.sleep(0.5)
            self.encerrar()
        threading.Thread(target=encerrar, daemon=True).start()

    def encerrar(self) -> None:
        log.info("HomeNOC encerrado pela interface.")
        self.parar.set()
        for evento in self.acordar.values():
            evento.set()
        if self.web:
            self.web.parar()

    # =================================================================
    # Dados para a interface
    # =================================================================

    def _urls_celular(self, rede_local: bool) -> list[str]:
        ip = self.rede_info.get("ip")
        return [f"http://{ip}:{self.porta}"] if rede_local and ip and ip != "127.0.0.1" else []

    def _para_tela(self, d: dict, zbx: dict | None = None) -> dict:
        d = dict(d)
        d["nome"] = nome_exibicao(d)
        d["tipo_nome"] = TIPOS.get(d.get("tipo") or "desconhecido", "Aparelho")
        d["zabbix"] = (zbx if zbx is not None else self.zabbix.status.get("por_ip", {})).get(d.get("ip"))
        d["escaneando"] = d["id"] in self.escaneando
        d["este_pc"] = d.get("ip") == self.rede_info.get("ip")
        return d

    def _consumo_hoje(self) -> dict:
        meia_noite = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        r = self.banco.resumo_trafego(meia_noite, time.time())
        return {"rx_bytes": r["rx_bytes"], "tx_bytes": r["tx_bytes"]}

    def _veredito(self, cfg: dict, internet: dict | None, dispositivos: list[dict]) -> dict:
        monitorados = [d for d in dispositivos if d["alertar"] and not d["este_pc"]]
        fora = sorted((d for d in monitorados if not d["online"]), key=lambda d: d.get("tipo") != "roteador")
        if internet is None and not self.monitor.status["ultimo_ciclo"]:
            return {"estado": "iniciando", "titulo": "Verificando a rede", "detalhe": "Primeiro teste em andamento.",
                    "desde": None}
        roteador_fora = next((d for d in fora if d.get("tipo") == "roteador"), None)
        if roteador_fora:
            return {"estado": "critico", "titulo": f"{roteador_fora['nome']} sem resposta",
                    "detalhe": "Confira a energia e os cabos do roteador.", "desde": roteador_fora.get("mudou_em")}
        if internet and not internet["online"]:
            roteador_ok = any(d.get("tipo") == "roteador" and d["online"] for d in monitorados)
            return {"estado": "critico", "titulo": "Internet fora do ar",
                    "detalhe": ("O roteador responde; a falha parece ser da operadora." if roteador_ok
                                else "Nenhum servidor da internet respondeu."),
                    "desde": internet.get("desde")}
        if fora:
            nomes = ", ".join(d["nome"] for d in fora[:3]) + (f" e mais {len(fora) - 3}" if len(fora) > 3 else "")
            return {"estado": "alerta", "titulo": f"{nomes} sem resposta",
                    "detalhe": "A internet está funcionando.", "desde": fora[0].get("mudou_em")}
        graves = [p for p in self.zabbix.status.get("problemas", []) if p["gravidade"] >= 4]
        if graves:
            p = graves[0]
            return {"estado": "alerta", "titulo": f"Zabbix: {p['nome']}", "detalhe": p.get("host") or "",
                    "desde": p.get("desde")}
        if internet and internet.get("ms") and internet["ms"] > cfg["internet"]["lenta_ms"]:
            return {"estado": "alerta", "titulo": "Internet lenta",
                    "detalhe": f"Resposta em {internet['ms']:.0f} ms (o normal é abaixo de "
                               f"{cfg['internet']['lenta_ms']} ms).", "desde": None}
        online = sum(1 for d in dispositivos if d["online"])
        return {"estado": "ok", "titulo": "Tudo funcionando",
                "detalhe": f"{online} aparelhos na rede" + (
                    f", {len(monitorados)} sob monitoramento" if monitorados else ""), "desde": None}

    def estado(self, local: bool = True) -> dict:
        cfg = self.config.get()
        zbx = self.zabbix.status
        dispositivos = [self._para_tela(d, zbx.get("por_ip", {})) for d in self.banco.dispositivos()]
        dispositivos.sort(key=lambda d: (ORDEM_TIPOS.index(d.get("tipo") or "desconhecido")
                                         if (d.get("tipo") or "desconhecido") in ORDEM_TIPOS else 99,
                                         not d["online"],
                                         tuple(int(p) for p in (d.get("ip") or "0.0.0.0").split("."))))
        internet = self.monitor.status.get("internet")
        acesso_cfg = cfg["acesso"]
        resumo_alertas = self.alertas.resumo()
        return {
            "app": "HomeNOC", "versao": __version__, "agora": time.time(), "iniciado_em": self.iniciado_em,
            "rede": self.rede_info,
            "varredura": dict(self.varredura),
            "internet": internet,
            "monitor": {"ultimo_ciclo": self.monitor.status["ultimo_ciclo"],
                        "intervalo_s": cfg["monitor"]["intervalo_s"], "lenta_ms": cfg["internet"]["lenta_ms"]},
            "dispositivos": dispositivos,
            "caminho": self.caminho,
            "trafego": {**self.trafego.status, "hoje": self._consumo_hoje()},
            "alertas": resumo_alertas,
            "zabbix": {k: zbx.get(k) for k in ("configurado", "ok", "erro", "versao", "hosts", "problemas",
                                                "atualizado_em")},
            "eventos": self.banco.eventos(12),
            "veredito": self._veredito(cfg, internet, dispositivos),
            "primeiros_passos": {
                "varredura": self.varredura["ultima"] is not None or bool(dispositivos),
                "monitorados": sum(1 for d in dispositivos if d["alertar"]),
                "alertas": bool(resumo_alertas["canais"]),
                "celular": acesso_cfg["rede_local"],
                "zabbix": bool(zbx.get("configurado")),
            },
            "acesso": {"local": local, "rede_local": acesso_cfg["rede_local"],
                       "senha_definida": bool(acesso_cfg["senha_hash"]),
                       "urls": self._urls_celular(acesso_cfg["rede_local"])},
            "autostart": {"suportado": autostart.suportado(), "ativo": autostart.ativo()},
            "portas_conhecidas": rede.PORTAS,
            "pasta_dados": str(self.pasta) if local else None,
        }

    def historico(self, alvo: str, periodo: int) -> dict:
        if not (alvo == CHAVE_INTERNET or alvo.startswith(("wan:", "dispositivo:"))):
            raise ErroConfig("Alvo de histórico inválido.")
        agora = time.time()
        desde = agora - periodo
        return {"alvo": alvo, "desde": desde, "ate": agora, "serie": self.banco.serie(alvo, desde, agora),
                "estatisticas": self.banco.estatisticas(alvo, desde)}

    def dados_trafego(self, periodo: int) -> dict:
        agora = time.time()
        desde = agora - periodo
        fuso = int(datetime.now().astimezone().utcoffset().total_seconds())
        return {"periodo": periodo, "desde": desde, "ate": agora,
                "serie": self.banco.serie_trafego(desde, agora),
                "resumo": self.banco.resumo_trafego(desde, agora),
                "dias": self.banco.consumo_por_dia(7, fuso, agora),
                "status": self.trafego.status}

    def inventario_csv(self) -> str:
        saida = io.StringIO()
        w = csv.writer(saida, delimiter=";")
        w.writerow(["Nome", "Tipo", "IP", "MAC", "Fabricante", "Nome DNS", "Online", "Latência (ms)",
                    "Portas abertas", "Visto pela 1ª vez", "Visto por último", "Avisar se cair"])
        data = lambda ts: datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M") if ts else ""  # noqa: E731
        for d in self.estado()["dispositivos"]:
            w.writerow([d["nome"], d["tipo_nome"], d.get("ip") or "", d.get("mac") or "", d.get("fabricante") or "",
                        d.get("nome_dns") or "", "sim" if d["online"] else "não",
                        "" if d.get("latencia") is None else f"{d['latencia']:.1f}".replace(".", ","),
                        " ".join(str(p) for p in d.get("portas") or []), data(d.get("primeira_vez")),
                        data(d.get("ultima_vez")), "sim" if d["alertar"] else "não"])
        return saida.getvalue()


# =====================================================================
# Linha de comando
# =====================================================================

def ja_rodando(porta: int) -> bool:
    """Outra cópia do HomeNOC já responde nessa porta?"""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{porta}/api/saude", headers={"Host": "127.0.0.1"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=2) as r:
            return json.loads(r.read()).get("app") == "HomeNOC"
    except (OSError, ValueError):
        return False


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):     # acento ou emoji nunca derruba o programa
        if fluxo is not None and hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="homenoc", description="HomeNOC: um mini-NOC para a rede de casa.")
    p.add_argument("--porta", type=int, default=PORTA_PADRAO, help="porta da interface (padrão 8765)")
    p.add_argument("--dados", help="pasta dos dados (padrão: dados/ ao lado do programa)")
    p.add_argument("--sem-navegador", action="store_true", help="não abre o navegador ao iniciar")
    p.add_argument("--demo", action="store_true", help="abre a demonstração com uma rede simulada")
    args = p.parse_args(argv)

    url = f"http://127.0.0.1:{args.porta}/" + ("?demo" if args.demo else "")
    if ja_rodando(args.porta):
        print(f"O HomeNOC já está aberto em {url}")
        if not args.sem_navegador:
            webbrowser.open(url)
        return 0

    pasta = Path(tempfile.mkdtemp(prefix="homenoc-demo-")) if args.demo else pasta_de_dados(args.dados)
    configurar_log(pasta, console=True)
    app = App(pasta, args.porta, baixar_fabricantes=not args.demo)
    app.web = ServidorWeb(app, args.porta)
    cfg = app.config.get()["acesso"]
    host = "0.0.0.0" if cfg["rede_local"] and cfg["senha_hash"] and not args.demo else "127.0.0.1"
    try:
        app.web.iniciar(host)
    except OSError as exc:
        print(f"[ERRO] Não consegui usar a porta {args.porta} ({exc}). Feche o outro programa "
              f"ou rode com --porta 8766.", file=sys.stderr)
        return 2
    if not args.demo:
        app.iniciar_rotinas()
    log.info("HomeNOC %s iniciado. Dados em %s", __version__, pasta)
    print(f"HomeNOC rodando em {url}  (Ctrl+C para sair)")
    if not args.sem_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        while not app.parar.wait(1):
            pass
    except KeyboardInterrupt:
        app.encerrar()
    return 0
