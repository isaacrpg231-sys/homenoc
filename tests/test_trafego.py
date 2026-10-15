"""Tráfego: velocidade a partir dos contadores, volta do contador de 32 bits, reinício e consumo por dia."""

import unittest

from apoio import Relogio, config_e_banco

from homenoc import upnp
from homenoc.trafego import Trafego, delta_contador


class RoteadorFalso:
    def __init__(self):
        self.rx, self.tx = 1_000_000, 100_000
        self.erro = None
        self.info = {"ip_publico": "100.64.1.2", "cgnat": True}

    def contadores(self):
        if self.erro:
            raise upnp.UPnPError(self.erro)
        return self.rx, self.tx

    def informacoes(self):
        return self.info


class Contador(unittest.TestCase):
    def test_delta(self):
        self.assertEqual(delta_contador(100, 250), 150)
        self.assertEqual(delta_contador(2**32 - 1000, 500), 1500)    # 32 bits deu a volta
        self.assertIsNone(delta_contador(9_000_000_000, 5_000))       # contador de 64 bits zerou: reinício
        self.assertIsNone(delta_contador(3_000_000, 1_000_000))       # queda pequena: reinício


class Amostragem(unittest.TestCase):
    def setUp(self):
        self.config, self.banco = config_e_banco()
        self.relogio = Relogio()
        self.roteador = RoteadorFalso()
        self.t = Trafego(self.banco, self.config, self.roteador, self.relogio)

    def ler(self, segundos=30, rx=0, tx=0):
        self.relogio.avancar(segundos=segundos)
        self.roteador.rx += rx
        self.roteador.tx += tx
        return self.t.amostrar()

    def test_primeira_leitura_so_guarda_referencia(self):
        self.assertIsNone(self.ler(0))
        self.assertEqual(self.t.status["estado"], "ativo")
        self.assertEqual(self.t.status["roteador"]["ip_publico"], "100.64.1.2")

    def test_velocidade_em_bits_por_segundo(self):
        self.ler(0)
        a = self.ler(30, rx=37_500_000, tx=3_750_000)               # 37,5 MB em 30 s = 10 Mbps
        self.assertEqual((a["rx_bps"], a["tx_bps"]), (10_000_000, 1_000_000))
        r = self.banco.resumo_trafego(0, self.relogio() + 1)
        self.assertEqual((r["rx_bytes"], r["tx_bytes"]), (37_500_000, 3_750_000))

    def test_volta_do_contador_de_32_bits_vira_amostra_certa(self):
        self.roteador.rx = 2**32 - 1_000_000
        self.ler(0)
        self.roteador.rx = 2**32 - 1_000_000                        # zera a soma do helper
        self.relogio.avancar(segundos=10)
        self.roteador.rx = 250_000                                   # passou de 4 GB e deu a volta
        a = self.t.amostrar()
        self.assertEqual(a["rx_bps"], (1_250_000 * 8) / 10)

    def test_reinicio_do_roteador_e_pausa_longa_sao_descartados(self):
        self.ler(0)
        self.roteador.rx = 10                                         # roteador reiniciou
        self.assertIsNone(self.ler(30))
        self.assertIsNotNone(self.ler(30, rx=1000))
        self.assertIsNone(self.ler(3 * 3600, rx=1000))               # o computador dormiu 3 h

    def test_sem_upnp_fica_indisponivel_com_o_motivo(self):
        self.roteador.erro = "nenhum roteador respondeu ao UPnP."
        self.assertIsNone(self.ler(0))
        self.assertEqual(self.t.status["estado"], "indisponivel")
        self.assertIn("nenhum roteador", self.t.status["motivo"])

    def test_desligado_pela_configuracao(self):
        self.config.atualizar({"trafego": {"ativo": False}})
        self.assertIsNone(self.ler(0))
        self.assertEqual(self.t.status["estado"], "desligado")

    def test_consumo_por_dia_e_serie(self):
        self.ler(0)
        for _ in range(4):
            self.ler(30, rx=3_000_000, tx=300_000)
        dias = self.banco.consumo_por_dia(7, 0, self.relogio())
        self.assertEqual(sum(d["rx_bytes"] for d in dias), 12_000_000)
        serie = self.banco.serie_trafego(self.relogio() - 300, self.relogio() + 1, 10)
        self.assertTrue(all(p[1] == 800_000 for p in serie))


if __name__ == "__main__":
    unittest.main(verbosity=2)
