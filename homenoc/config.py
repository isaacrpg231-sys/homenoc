"""
Configuração do HomeNOC, salva em dados/config.json e editada pela tela de
Configurações. Valida cada campo e nunca devolve segredos (tokens) inteiros
para o navegador.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
import urllib.parse
from pathlib import Path

from . import rede

PADRAO = {
    "monitor": {"intervalo_s": 60, "confirmacao_s": 15, "tentativas": 2, "timeout_ms": 1000},
    "internet": {"alvos": ["8.8.8.8", "1.1.1.1"], "alertar": True, "lenta_ms": 150},
    "descoberta": {"intervalo_min": 5, "testar_portas": True, "avisar_novos": False},
    "trafego": {"ativo": True, "intervalo_s": 30},
    "alertas": {
        "telegram": {"token": "", "chat_id": ""},
        "discord": {"webhook": ""},
        "healthchecks": {"url": ""},
    },
    "zabbix": {"url": "", "token": ""},
    "acesso": {"rede_local": False, "senha_hash": "", "sal": ""},
    "retencao_dias": 7,
}

# Caminhos dos campos secretos: nunca saem inteiros pela API.
SEGREDOS = (("alertas", "telegram", "token"), ("alertas", "discord", "webhook"),
            ("alertas", "healthchecks", "url"), ("zabbix", "token"))
MASCARA = "••••"
_TOKEN_TELEGRAM = re.compile(r"^\d{5,}:[\w-]{30,}$")
_CHAT_ID = re.compile(r"^(-?\d{1,20}|@[A-Za-z0-9_]{4,})$")


class ErroConfig(ValueError):
    """Valor inválido, com mensagem pronta para mostrar na tela."""


def _mesclar(base: dict, novo: dict) -> dict:
    resultado = copy.deepcopy(base)
    for chave, valor in novo.items():
        if isinstance(valor, dict) and isinstance(resultado.get(chave), dict):
            resultado[chave] = _mesclar(resultado[chave], valor)
        else:
            resultado[chave] = copy.deepcopy(valor)
    return resultado


def _pegar(d: dict, caminho: tuple[str, ...]):
    for parte in caminho:
        d = d.get(parte, {}) if isinstance(d, dict) else {}
    return d


def _colocar(d: dict, caminho: tuple[str, ...], valor) -> None:
    for parte in caminho[:-1]:
        d = d.setdefault(parte, {})
    d[caminho[-1]] = valor


def mascarar(valor: str) -> str:
    if not valor:
        return ""
    return MASCARA + (valor[-4:] if len(valor) > 8 else "")


def normalizar_url_zabbix(url: str) -> str:
    """Aceita 'http://192.168.1.60/zabbix' e completa com /api_jsonrpc.php."""
    url = (url or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    if not url.rstrip("/").endswith("api_jsonrpc.php"):
        url = url.rstrip("/") + "/api_jsonrpc.php"
    return url


def _inteiro(secao: dict, chave: str, minimo: int, maximo: int, nome: str) -> None:
    valor = secao.get(chave)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or int(valor) != valor:
        raise ErroConfig(f"{nome} deve ser um número inteiro.")
    if not minimo <= valor <= maximo:
        raise ErroConfig(f"{nome} deve ficar entre {minimo} e {maximo}.")
    secao[chave] = int(valor)


def _booleano(secao: dict, chave: str, nome: str) -> None:
    if not isinstance(secao.get(chave), bool):
        raise ErroConfig(f"{nome} deve ser verdadeiro ou falso.")


def validar(cfg: dict) -> dict:
    """Confere todos os campos; levanta ErroConfig com a primeira mensagem de erro."""
    m = cfg["monitor"]
    _inteiro(m, "intervalo_s", 15, 3600, "O intervalo do monitoramento (segundos)")
    _inteiro(m, "confirmacao_s", 0, 120, "A espera de confirmação (segundos)")
    _inteiro(m, "tentativas", 1, 5, "O número de tentativas")
    _inteiro(m, "timeout_ms", 300, 5000, "O tempo limite do ping (ms)")

    i = cfg["internet"]
    alvos = i.get("alvos")
    if not isinstance(alvos, list) or not 1 <= len(alvos) <= 4:
        raise ErroConfig("Informe de 1 a 4 servidores para testar a internet.")
    i["alvos"] = [str(a).strip() for a in alvos]
    for alvo in i["alvos"]:
        if not rede.host_valido(alvo):
            raise ErroConfig(f"'{alvo}' não é um IP ou nome de servidor válido.")
    if len(set(i["alvos"])) != len(i["alvos"]):
        raise ErroConfig("Há servidores repetidos na lista da internet.")
    _booleano(i, "alertar", "Avisar quando a internet cair")
    _inteiro(i, "lenta_ms", 20, 2000, "O limite de internet lenta (ms)")

    d = cfg["descoberta"]
    _inteiro(d, "intervalo_min", 1, 1440, "O intervalo da varredura (minutos)")
    _booleano(d, "testar_portas", "Testar portas")
    _booleano(d, "avisar_novos", "Avisar sobre aparelhos novos")

    t = cfg["trafego"]
    _booleano(t, "ativo", "Medir o tráfego")
    _inteiro(t, "intervalo_s", 10, 600, "O intervalo do tráfego (segundos)")

    tg = cfg["alertas"]["telegram"]
    tg["token"], tg["chat_id"] = str(tg.get("token") or "").strip(), str(tg.get("chat_id") or "").strip()
    if tg["token"] and not _TOKEN_TELEGRAM.match(tg["token"]):
        raise ErroConfig("O token do Telegram não parece válido (formato 123456789:AAH...).")
    if tg["chat_id"] and not _CHAT_ID.match(tg["chat_id"]):
        raise ErroConfig("O chat_id do Telegram deve ser um número (ou @nome_do_canal).")

    dc = cfg["alertas"]["discord"]
    dc["webhook"] = str(dc.get("webhook") or "").strip()
    if dc["webhook"] and not re.match(r"^https://(discord|discordapp)\.com/api/webhooks/\S+$", dc["webhook"]):
        raise ErroConfig("O webhook do Discord deve começar com https://discord.com/api/webhooks/")

    hc = cfg["alertas"]["healthchecks"]
    hc["url"] = str(hc.get("url") or "").strip()
    if hc["url"] and not re.match(r"^https?://\S+$", hc["url"]):
        raise ErroConfig("O endereço do Healthchecks deve começar com https://")

    z = cfg["zabbix"]
    z["url"] = normalizar_url_zabbix(str(z.get("url") or ""))
    z["token"] = str(z.get("token") or "").strip()
    if z["url"]:
        partes = urllib.parse.urlparse(z["url"])
        if not partes.hostname:
            raise ErroConfig("O endereço do Zabbix não é válido.")
    if z["token"] and not re.fullmatch(r"[A-Za-z0-9]{16,128}", z["token"]):
        raise ErroConfig("O token do Zabbix deve ter só letras e números (como o Zabbix gera).")

    _booleano(cfg["acesso"], "rede_local", "Acesso pela rede")
    _inteiro(cfg, "retencao_dias", 1, 90, "Os dias de histórico")
    return cfg


class Config:
    """Configuração com trava: leitura sempre devolve uma cópia."""

    def __init__(self, arquivo: str | Path) -> None:
        self.arquivo = Path(arquivo)
        self.lock = threading.Lock()
        self._dados = copy.deepcopy(PADRAO)
        self.aviso: str | None = None
        if self.arquivo.exists():
            try:
                lido = json.loads(self.arquivo.read_text(encoding="utf-8-sig"))
                self._dados = validar(_mesclar(PADRAO, lido if isinstance(lido, dict) else {}))
            except (OSError, ValueError) as exc:
                self.aviso = f"config.json ignorado ({exc}); usando os valores padrão."
                self._dados = copy.deepcopy(PADRAO)

    def get(self) -> dict:
        with self.lock:
            return copy.deepcopy(self._dados)

    def _salvar(self) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._dados, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.arquivo)

    def _previa(self, parcial: dict, permitir_acesso: bool) -> dict:
        if not isinstance(parcial, dict):
            raise ErroConfig("Formato inválido.")
        parcial = copy.deepcopy(parcial)
        if not permitir_acesso:
            parcial.pop("acesso", None)
        for caminho in SEGREDOS:
            valor = _pegar(parcial, caminho)
            if isinstance(valor, str) and valor.startswith(MASCARA):
                _colocar(parcial, caminho, _pegar(self._dados, caminho))
        return validar(_mesclar(self._dados, parcial))

    def previa(self, parcial: dict) -> dict:
        """Como ficaria a configuração com essas mudanças, sem salvar (para testar antes)."""
        with self.lock:
            return self._previa(parcial, permitir_acesso=False)

    def atualizar(self, parcial: dict, permitir_acesso: bool = False) -> dict:
        """Mescla, valida e salva. Valores mascarados ('••••1234') mantêm o segredo atual."""
        with self.lock:
            novo = self._previa(parcial, permitir_acesso)
            self._dados = novo
            self._salvar()
            return copy.deepcopy(novo)

    def definir_acesso(self, rede_local: bool, senha_hash: str | None = None, sal: str | None = None) -> None:
        with self.lock:
            self._dados["acesso"]["rede_local"] = bool(rede_local)
            if senha_hash is not None:
                self._dados["acesso"]["senha_hash"] = senha_hash
                self._dados["acesso"]["sal"] = sal or ""
            self._salvar()

    def mascarado(self) -> dict:
        """Cópia segura para o navegador: segredos mascarados, hash da senha removido."""
        cfg = self.get()
        for caminho in SEGREDOS:
            _colocar(cfg, caminho, mascarar(_pegar(cfg, caminho)))
        acesso = cfg["acesso"]
        acesso["senha_definida"] = bool(acesso.pop("senha_hash", ""))
        acesso.pop("sal", None)
        return cfg
