"""Monitor: quedas, confirmação, fila sem internet e restauração (lógica herdada do NetMon)."""

import unittest
from datetime import datetime
from unittest import mock

from apoio import CanalFalso, PingerFalso, Relogio, config_e_banco

from homenoc.alertas import Alertas
from homenoc.descoberta import Inventario
from homenoc.monitor import Monitor, formatar_duracao

ROTEADOR, TV, GOOGLE, CLOUDFLARE, EU = "192.168.1.1", "192.168.1.50", "8.8.8.8", "1.1.1.1", "192.168.1.10"


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.config, self.banco = config_e_banco()
        self.relogio = Relogio()
        for id_, ip, apelido, alertar in (("mac:aa:aa:aa:aa:aa:01", ROTEADOR, "Roteador", True),
                                          ("mac:aa:aa:aa:aa:aa:02", TV, "Smart TV", False),
                                          ("mac:aa:aa:aa:aa:aa:03", EU, "Notebook", True)):
            self.banco.salvar_dispositivo({"id": id_, "ip": ip, "apelido": apelido, "alertar": alertar,
                                           "online": True, "primeira_vez": self.relogio()})
        self.pinger = PingerFalso({ROTEADOR, TV, GOOGLE, CLOUDFLARE})
        self.canal = CanalFalso()
        self.alertas = Alertas(self.banco, self.config, self.relogio, canais=[self.canal])
        self.pausas = []
        self.monitor = Monitor(self.banco, self.config, self.alertas, self.pinger, self.relogio,
                               dormir=self.pausas.append, hostname="notebook-isaac")
        self.monitor.ip_local_fn = lambda: EU

    def ciclo(self, minutos=1):
        self.relogio.avancar(minutos)
        with self.assertLogs("homenoc", level="INFO") as logs:
            self.monitor.ciclo()
        return "\n".join(logs.output)

    def eventos(self):
        return [(e["tipo"], e["titulo"]) for e in reversed(self.banco.eventos(100))]

    def test_tudo_ok_nao_alerta_e_nao_pinga_quem_nao_e_monitorado(self):
        saida = self.ciclo()
        self.assertEqual(self.canal.enviadas, [])
        self.assertIn("LAN | Roteador", saida)
        self.assertEqual(sorted(self.pinger.chamadas[0]), sorted([GOOGLE, CLOUDFLARE, ROTEADOR]))  # nem TV nem eu
        self.assertTrue(self.monitor.status["internet"]["online"])
        self.assertEqual(self.monitor.status["internet"]["ms"], 12.5)

    def test_queda_total_fica_na_fila_e_chega_quando_volta(self):
        self.ciclo()                                     # tudo ok
        self.pinger.no_ar = {TV}                         # roteador e internet caem
        inicio_queda = self.relogio() + 60
        saida = self.ciclo()
        self.assertEqual(self.pausas, [15])              # confirmou antes de alertar
        self.assertIn("EVENTO | Roteador (192.168.1.1) CAIU", saida)
        self.assertIn("EVENTO | Internet CAIU", saida)
        self.assertIn("aguardando a internet voltar", saida)
        self.assertEqual(self.canal.enviadas, [])       # sem internet: nada enviado ainda
        self.assertEqual(len(self.banco.fila()), 1)

        self.ciclo()                                     # continua fora: sem alerta repetido
        self.assertEqual(len(self.banco.fila()), 1)
        self.assertEqual(self.pausas, [15])              # não reconfirma o que já está fora

        self.pinger.no_ar = {ROTEADOR, TV, GOOGLE, CLOUDFLARE}
        saida = self.ciclo(minutos=14)                   # voltou 15 min depois
        self.assertEqual(len(self.canal.enviadas), 2)
        queda, volta = self.canal.enviadas
        self.assertIn("🔴 ALERTA DE REDE", queda)
        self.assertIn("Roteador (192.168.1.1): OFFLINE", queda)
        self.assertIn("Internet: OFFLINE (nenhum servidor externo respondeu)", queda)
        self.assertIn("Nada respondeu: pode ser o roteador", queda)   # nem o roteador nem a internet
        self.assertIn(datetime.fromtimestamp(inicio_queda).strftime("%d/%m/%Y %H:%M:%S"), queda)
        self.assertIn("📍 Monitor: notebook-isaac", queda)
        self.assertIn("Enviado com atraso", queda)
        self.assertIn("🟢 REDE RESTAURADA", volta)
        self.assertIn("Internet: ONLINE (ficou fora por 15 min, 12 ms)", volta)
        self.assertNotIn("atraso", volta)
        self.assertIn("ALERTA | enviado: QUEDA", saida)
        self.assertEqual(self.banco.fila(), [])
        tipos = [t for t, _ in self.eventos()]
        self.assertEqual(tipos.count("queda"), 2)
        self.assertEqual(tipos.count("volta"), 2)
        self.assertEqual(tipos.count("alerta"), 2)

    def test_dica_aponta_o_aparelho_quando_o_resto_responde(self):
        Inventario(self.banco, relogio=self.relogio).definir_alertar("mac:aa:aa:aa:aa:aa:02", True)
        self.ciclo()
        self.pinger.no_ar -= {ROTEADOR}                  # TV e internet seguem no ar
        self.ciclo()
        self.assertIn("Confira energia e cabos de: Roteador", self.canal.enviadas[0])

    def test_aparelho_monitorado_atualiza_o_inventario(self):
        self.ciclo()
        self.pinger.no_ar -= {ROTEADOR}
        self.ciclo()
        d = self.banco.dispositivo("mac:aa:aa:aa:aa:aa:01")
        self.assertFalse(d["online"])
        self.assertEqual(d["mudou_em"], self.relogio())

    def test_so_a_internet_cai_e_a_dica_aponta_a_operadora(self):
        self.ciclo()
        self.pinger.no_ar = {ROTEADOR, TV}
        self.ciclo()
        self.pinger.no_ar |= {GOOGLE}
        self.ciclo()
        queda, volta = self.canal.enviadas
        self.assertNotIn("Roteador", queda)
        self.assertIn("a falha parece ser da operadora", queda)
        self.assertIn("REDE RESTAURADA", volta)

    def test_falha_momentanea_nao_gera_alerta(self):
        self.ciclo()
        self.pinger.instaveis = {ROTEADOR}               # falha no 1º teste, responde na confirmação
        saida = self.ciclo()
        self.assertEqual(self.pausas, [15])
        self.assertIn("respondeu na confirmação", saida)
        self.assertNotIn("EVENTO", saida)
        self.assertEqual(self.canal.enviadas, [])

    def test_confirmacao_desligada(self):
        self.config.atualizar({"monitor": {"confirmacao_s": 0}})
        self.ciclo()
        self.pinger.no_ar -= {ROTEADOR}
        self.ciclo()
        self.assertEqual(self.pausas, [])
        self.assertEqual(len(self.canal.enviadas), 1)

    def test_um_servidor_externo_fora_nao_derruba_a_internet(self):
        self.ciclo()
        self.pinger.no_ar -= {GOOGLE}
        saida = self.ciclo()
        self.assertIn("1 de 2 servidores responderam", saida)
        self.assertEqual(self.canal.enviadas, [])
        self.assertTrue(self.monitor.status["internet"]["online"])

    def test_roteador_ja_fora_na_primeira_execucao(self):
        self.pinger.no_ar -= {ROTEADOR}
        self.ciclo()
        self.assertEqual(len(self.canal.enviadas), 1)
        self.assertIn("Roteador (192.168.1.1): OFFLINE", self.canal.enviadas[0])

    def test_alerta_da_internet_pode_ser_desligado(self):
        self.config.atualizar({"internet": {"alertar": False}})
        self.ciclo()
        self.pinger.no_ar -= {GOOGLE, CLOUDFLARE}
        self.ciclo()
        self.pinger.no_ar |= {GOOGLE}
        self.ciclo()
        self.assertEqual(self.canal.enviadas, [])
        self.assertIn(("queda", "Internet caiu"), self.eventos())   # mas o evento fica registrado

    def test_falha_do_canal_mantem_alerta_na_fila(self):
        self.ciclo()
        self.canal.quebrado = True
        self.pinger.no_ar -= {ROTEADOR}
        saida = self.ciclo()
        self.assertIn("ALERTA | falha no Falso", saida)
        self.assertEqual(len(self.banco.fila()), 1)
        self.assertIn(("alerta", "Falha ao enviar alerta"), self.eventos())
        self.canal.quebrado = False
        self.ciclo()
        self.assertEqual(len(self.canal.enviadas), 1)
        self.assertEqual(self.banco.fila(), [])

    def test_sem_canal_configurado_nao_acumula_fila(self):
        alertas = Alertas(self.banco, self.config, self.relogio, canais=[])
        monitor = Monitor(self.banco, self.config, alertas, self.pinger, self.relogio, dormir=self.pausas.append)
        monitor.ip_local_fn = lambda: EU
        self.pinger.no_ar -= {ROTEADOR}
        with self.assertLogs("homenoc", level="INFO") as logs:
            monitor.ciclo()
        self.assertIn("CAIU", "\n".join(logs.output))
        self.assertEqual(self.banco.fila(), [])

    def test_fila_tem_limite(self):
        for n in range(30):
            self.alertas.enfileirar(f"alerta {n}", "teste")
        fila = self.banco.fila()
        self.assertEqual(len(fila), Alertas.MAX_FILA)
        self.assertEqual(fila[-1]["texto"], "alerta 29")

    def test_ligar_monitoramento_de_aparelho_ja_desligado_nao_alerta(self):
        inventario = Inventario(self.banco, relogio=self.relogio)
        self.banco.atualizar_dispositivo("mac:aa:aa:aa:aa:aa:02", online=False, mudou_em=self.relogio())
        self.pinger.no_ar -= {TV}
        inventario.definir_alertar("mac:aa:aa:aa:aa:aa:02", True)      # TV em standby
        self.ciclo()
        self.assertEqual(self.canal.enviadas, [])
        self.pinger.no_ar |= {TV}
        self.ciclo()
        self.assertEqual(len(self.canal.enviadas), 1)
        self.assertIn("🟢 REDE RESTAURADA", self.canal.enviadas[0])
        self.assertIn("Smart TV (192.168.1.50): ONLINE", self.canal.enviadas[0])

    def test_historico_de_latencia(self):
        self.ciclo()
        self.pinger.no_ar -= {GOOGLE, CLOUDFLARE}
        self.ciclo()
        serie = self.banco.serie("internet", self.relogio() - 600, self.relogio() + 1, 10)
        self.assertEqual([p[1] for p in serie], [12.5, None])
        self.assertEqual([p[2] for p in serie], [0.0, 100.0])

    def test_erro_inesperado_nao_derruba_o_monitor(self):
        self.pinger.pingar = mock.Mock(side_effect=RuntimeError("boom"))
        with self.assertLogs("homenoc", level="ERROR"):
            self.assertFalse(self.monitor.ciclo_seguro())


class Formatacao(unittest.TestCase):
    def test_duracao(self):
        self.assertEqual(formatar_duracao(20), "menos de 1 min")
        self.assertEqual(formatar_duracao(18 * 60), "18 min")
        self.assertEqual(formatar_duracao(125 * 60), "2 h 05 min")
        self.assertEqual(formatar_duracao(26 * 3600), "1 d 2 h")
        self.assertEqual(formatar_duracao(None), "?")


if __name__ == "__main__":
    unittest.main(verbosity=2)
