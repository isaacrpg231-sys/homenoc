"""
Tráfego da internet da casa toda, lido do roteador por UPnP.

O roteador informa o TOTAL de bytes desde que ligou. A velocidade é a diferença
entre duas leituras dividida pelo tempo. Muitos roteadores usam contador de
32 bits, que "dá a volta" a cada 4 GB: isso é detectado e corrigido. Se o
contador zerou porque o roteador reiniciou, a leitura é descartada.
"""

from __future__ import annotations

import logging
import time

from . import upnp

log = logging.getLogger("homenoc")
LIMITE_BPS = 10e9          # acima de 10 Gbps é leitura errada: descarta
INFO_A_CADA_S = 600        # IP público e tempo de conexão: a cada 10 min


def delta_contador(antes: int, depois: int) -> int | None:
    """Quantos bytes passaram entre duas leituras, ou None se não dá para saber."""
    if depois >= antes:
        return depois - antes
    if antes < 2**32 and antes - depois > 2**31:      # contador de 32 bits deu a volta
        return depois + 2**32 - antes
    return None                                       # o roteador reiniciou e zerou


class Trafego:
    def __init__(self, banco, config, roteador=None, relogio=time.time) -> None:
        self.banco = banco
        self.config = config
        self.roteador = roteador or upnp.Roteador()
        self.relogio = relogio
        self.anterior: tuple[float, int, int] | None = None
        self.info_em = 0.0
        self.status: dict = {"estado": "procurando", "motivo": None, "agora": None, "roteador": None}

    def amostrar(self) -> dict | None:
        cfg = self.config.get()["trafego"]
        if not cfg["ativo"]:
            self.status.update(estado="desligado", motivo=None, agora=None)
            self.anterior = None
            return None
        try:
            rx, tx = self.roteador.contadores()
        except upnp.UPnPError as exc:
            if self.status["estado"] != "indisponivel":
                log.info("Tráfego indisponível: %s", exc)
            self.status.update(estado="indisponivel", motivo=str(exc), agora=None)
            self.anterior = None
            return None
        agora = self.relogio()
        self.status.update(estado="ativo", motivo=None)
        amostra = None
        if self.anterior:
            t0, rx0, tx0 = self.anterior
            dt = agora - t0
            drx, dtx = delta_contador(rx0, rx), delta_contador(tx0, tx)
            # Pausa longa (computador dormiu) vira uma média enganosa: descarta.
            if 0 < dt <= max(5 * cfg["intervalo_s"], 120) and drx is not None and dtx is not None:
                rx_bps, tx_bps = drx * 8 / dt, dtx * 8 / dt
                if rx_bps <= LIMITE_BPS and tx_bps <= LIMITE_BPS:
                    self.banco.registrar_trafego(agora, rx_bps, tx_bps, drx, dtx)
                    amostra = {"ts": agora, "rx_bps": rx_bps, "tx_bps": tx_bps}
                    self.status["agora"] = amostra
        self.anterior = (agora, rx, tx)
        if agora - self.info_em > INFO_A_CADA_S:
            self.atualizar_info()
        return amostra

    def atualizar_info(self) -> None:
        self.info_em = self.relogio()
        try:
            self.status["roteador"] = self.roteador.informacoes()
        except (upnp.UPnPError, OSError, ValueError) as exc:
            log.info("Informações da internet indisponíveis: %s", exc)
