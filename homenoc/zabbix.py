"""
Integração (opcional) com o Zabbix: mostra no HomeNOC quais aparelhos o Zabbix
monitora, se o ping de lá responde e os problemas ativos.

Usa um token de API de um usuário SOMENTE LEITURA (passo 6 do guia do Zabbix).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

GRAVIDADES = ["Não classificado", "Informação", "Atenção", "Média", "Alta", "Desastre"]


class ErroZabbix(Exception):
    pass


class ZabbixAPI:
    def __init__(self, url: str, token: str, timeout: float = 8) -> None:
        self.url = url
        self.token = token
        self.timeout = timeout

    def chamar(self, metodo: str, params: dict | list | None = None, autenticar: bool = True):
        corpo = json.dumps({"jsonrpc": "2.0", "method": metodo, "params": params or {}, "id": 1}).encode()
        cabecalhos = {"Content-Type": "application/json-rpc", "User-Agent": "HomeNOC"}
        if autenticar:                        # apiinfo.version precisa ir SEM o cabeçalho
            cabecalhos["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.url, corpo, cabecalhos)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                dados = json.loads(r.read())
        except urllib.error.HTTPError as exc:
            raise ErroZabbix(f"o endereço respondeu HTTP {exc.code}. Confira a URL da API.") from None
        except urllib.error.URLError as exc:
            raise ErroZabbix(f"não consegui falar com o Zabbix ({exc.reason}). A VM está ligada?") from None
        except (OSError, ValueError):
            raise ErroZabbix("o endereço não parece ser a API do Zabbix.") from None
        if "error" in dados:
            detalhe = f"{dados['error'].get('message', '')} {dados['error'].get('data', '')}".strip()
            if "re-login" in detalhe or "Not authori" in detalhe or "token" in detalhe.lower():
                raise ErroZabbix("token inválido ou expirado. Gere outro em Users > API tokens.")
            if "No permissions to call" in detalhe:
                raise ErroZabbix(f"o usuário do token não pode chamar {metodo}. Revise o papel (user role).")
            raise ErroZabbix(detalhe or "erro desconhecido do Zabbix.")
        return dados["result"]

    def versao(self) -> str:
        return self.chamar("apiinfo.version", {}, autenticar=False)

    def resumo(self) -> dict:
        hosts = self.chamar("host.get", {"output": ["hostid", "name"], "selectInterfaces": ["ip"],
                                         "filter": {"status": 0}})
        ids = [h["hostid"] for h in hosts]
        itens = self.chamar("item.get", {"hostids": ids, "filter": {"key_": "icmpping"},
                                         "output": ["hostid", "lastvalue", "lastclock"]}) if ids else []
        problemas = self.chamar("problem.get", {"output": ["eventid", "objectid", "name", "severity", "clock"],
                                                "recent": False, "sortfield": ["eventid"], "sortorder": "DESC"})
        gatilhos = self.chamar("trigger.get", {"triggerids": [p["objectid"] for p in problemas],
                                               "output": ["triggerid"], "selectHosts": ["hostid", "name"]}
                               ) if problemas else []
        host_do_gatilho = {g["triggerid"]: g["hosts"][0] for g in gatilhos if g.get("hosts")}
        lista_problemas = []
        for p in problemas:
            host = host_do_gatilho.get(p["objectid"], {})
            sev = int(p.get("severity") or 0)
            lista_problemas.append({"nome": p["name"], "gravidade": sev, "gravidade_nome": GRAVIDADES[sev],
                                    "host": host.get("name"), "hostid": host.get("hostid"),
                                    "desde": int(p.get("clock") or 0)})
        por_ip = {}
        for h in hosts:
            item = next((i for i in itens if i["hostid"] == h["hostid"] and int(i.get("lastclock") or 0)), None)
            info = {"nome": h["name"], "hostid": h["hostid"],
                    "ping": None if not item else item["lastvalue"] == "1",
                    "problemas": [p["nome"] for p in lista_problemas if p["hostid"] == h["hostid"]]}
            for interface in h.get("interfaces", []):
                if interface.get("ip"):
                    por_ip[interface["ip"]] = info
        return {"hosts": len(hosts), "por_ip": por_ip, "problemas": lista_problemas}


class MonitorZabbix:
    def __init__(self, config, relogio=time.time) -> None:
        self.config = config
        self.relogio = relogio
        self.status: dict = {"configurado": False, "ok": None, "erro": None, "versao": None,
                             "hosts": 0, "por_ip": {}, "problemas": [], "atualizado_em": None}

    def configurado(self) -> bool:
        z = self.config.get()["zabbix"]
        return bool(z["url"] and z["token"])

    def atualizar(self) -> None:
        z = self.config.get()["zabbix"]
        if not (z["url"] and z["token"]):
            self.status = {**self.status, "configurado": False, "ok": None, "erro": None,
                           "por_ip": {}, "problemas": [], "hosts": 0}
            return
        api = ZabbixAPI(z["url"], z["token"])
        try:
            versao = api.versao()
            resumo = api.resumo()
        except ErroZabbix as exc:
            self.status.update(configurado=True, ok=False, erro=str(exc), atualizado_em=self.relogio())
            return
        self.status = {"configurado": True, "ok": True, "erro": None, "versao": versao,
                       "atualizado_em": self.relogio(), **resumo}


def testar(url: str, token: str) -> dict:
    api = ZabbixAPI(url, token)
    try:
        versao = api.versao()
        resumo = api.resumo()
    except ErroZabbix as exc:
        return {"ok": False, "erro": str(exc)}
    return {"ok": True, "versao": versao, "hosts": resumo["hosts"], "problemas": len(resumo["problemas"])}
