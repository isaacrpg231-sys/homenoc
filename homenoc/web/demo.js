/* HomeNOC: demonstração. Uma rede de casa simulada que responde a todas as rotas
   da API, para mostrar o HomeNOC sem instalar nada (GitHub Pages ou --demo).
   Os números são gerados por modelos simples e determinísticos: o mesmo minuto
   sempre tem o mesmo valor, então os gráficos não "pulam" a cada leitura. */
"use strict";
(function (HN) {
  const MIN = 60, H = 3600, DIA = 86400;
  const VERSAO = "1.0.0";
  const FUSO = -new Date().getTimezoneOffset() * 60;
  const agoraS = () => Date.now() / 1000;
  const QUEDA_S = Math.max(5, Number(new URLSearchParams(location.search).get("queda")) || 40);   // ?queda=12 para gravar vídeos
  const horaDe = (t) => (((t + FUSO) % DIA) + DIA) % DIA / H;
  const diaDe = (t) => Math.floor((t + FUSO) / DIA);
  const arred = (v, c = 1) => (v == null ? null : Math.round(v * 10 ** c) / 10 ** c);

  // ------------------------------------------------------------------ ruído determinístico
  function hash(s) {
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  function ruido(chave, n) {
    let x = (hash(chave) ^ Math.floor(n)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x45d9f3b);
    x = Math.imul(x ^ (x >>> 16), 0x45d9f3b);
    x ^= x >>> 16;
    return (x >>> 0) / 4294967296;
  }
  const sino = (h, centro, largura) => {
    const d = Math.min(Math.abs(h - centro), 24 - Math.abs(h - centro));
    return Math.exp(-(d * d) / (2 * largura * largura));
  };

  // ------------------------------------------------------------------ dados fixos
  const TIPOS = {
    roteador: "Roteador", este_pc: "Este computador", computador: "Computador", celular: "Celular ou tablet",
    tv: "TV ou streaming", impressora: "Impressora", camera: "Câmera", iot: "Dispositivo IoT", servidor: "Servidor", desconhecido: "Aparelho",
  };
  const ORDEM = ["roteador", "este_pc", "computador", "servidor", "tv", "celular", "impressora", "camera", "iot", "desconhecido"];
  const PORTAS = {
    21: "FTP", 22: "SSH", 23: "Telnet", 53: "DNS", 80: "HTTP", 139: "NetBIOS", 443: "HTTPS", 445: "SMB (Windows)", 554: "RTSP (câmera)",
    631: "IPP (impressora)", 1883: "MQTT", 3389: "Área de Trabalho Remota", 5000: "UPnP/Web", 8008: "Chromecast", 8009: "Chromecast",
    8080: "HTTP alternativo", 8443: "HTTPS alternativo", 9100: "Impressão RAW", 10050: "Zabbix agent", 62078: "iPhone/iPad",
  };
  const SO = {
    64: "Linux, Android, iOS, macOS ou embarcado (TTL inicial 64)",
    128: "Windows (TTL inicial 128)",
    255: "Equipamento de rede: roteador, switch ou impressora (TTL inicial 255)",
  };
  const REDE = { ip: "192.168.0.10", gateway: "192.168.0.1", rede: "192.168.0.0/24", mascara: "255.255.255.0", mac: "a4:c3:f0:4a:19:e7", host: "DESKTOP-7F3K2LM" };

  let D = null;     // o estado inteiro da demonstração

  function aparelho(base) {
    return Object.assign({
      apelido: null, nome_dns: null, fabricante: null, motivos: [], portas: [], upnp: null, ttl: 64, mac_aleatorio: false,
      responde_ping: true, alertar: false, ausencias: 0, latencia: null, janelas: null, modelo: { base: 3, var: 8 },
    }, base);
  }

  function criar() {
    const t0 = agoraS();
    const dias = (n) => t0 - n * DIA;
    const ds = [
      aparelho({ id: "mac:50:c7:bf:3e:21:0a", ip: "192.168.0.1", mac: "50:c7:bf:3e:21:0a", fabricante: "TP-LINK TECHNOLOGIES", tipo: "roteador",
        motivos: ["é o gateway padrão da rede"], portas: [53, 80, 443], upnp: { nome: "Archer C6", fabricante: "TP-Link", modelo: "Archer C6", tipo: "InternetGatewayDevice" },
        alertar: true, primeira_vez: dias(6.9), modelo: { base: 0.8, var: 1.4 } }),
      aparelho({ id: "mac:a4:c3:f0:4a:19:e7", ip: "192.168.0.10", mac: "a4:c3:f0:4a:19:e7", fabricante: "Intel Corporate", nome_dns: "DESKTOP-7F3K2LM", tipo: "este_pc",
        motivos: ["é este computador"], portas: [139, 445], ttl: 128, primeira_vez: dias(6.9), modelo: { base: 0, var: 0 } }),
      aparelho({ id: "mac:08:00:27:5d:8e:11", ip: "192.168.0.20", mac: "08:00:27:5d:8e:11", fabricante: "PCS Systemtechnik", nome_dns: "zabbix-server", tipo: "servidor",
        motivos: ["SSH aberto"], portas: [22, 80, 10050], alertar: true, primeira_vez: dias(6.9), modelo: { base: 0.4, var: 0.7 } }),
      aparelho({ id: "mac:f8:bc:12:7a:03:5e", ip: "192.168.0.44", mac: "f8:bc:12:7a:03:5e", fabricante: "Dell", tipo: "computador",
        motivos: ["TTL típico do Windows"], portas: [], ttl: 128, primeira_vez: dias(6.9), modelo: { base: 2, var: 6 },
        janelas: [[dias(6.5), dias(5.8)], [dias(3.6), dias(3.1)], [t0 - 20 * H, t0 - 3 * H]] }),
      aparelho({ id: "mac:8c:79:f5:12:6b:3d", ip: "192.168.0.21", mac: "8c:79:f5:12:6b:3d", fabricante: "Samsung Electronics", apelido: "TV da sala", tipo: "tv",
        motivos: ["serviço de mídia (Chromecast ou DLNA)"], portas: [8080], upnp: { nome: "[TV] Samsung 7 Series (50)", fabricante: "Samsung Electronics", modelo: "UN50TU7000", tipo: "MediaRenderer" },
        alertar: true, primeira_vez: dias(6.9), modelo: { base: 3.5, var: 11 } }),
      aparelho({ id: "mac:f4:f5:d8:31:0c:9e", ip: "192.168.0.52", mac: "f4:f5:d8:31:0c:9e", fabricante: "Google", nome_dns: "Chromecast", tipo: "tv",
        motivos: ["serviço de mídia (Chromecast ou DLNA)"], portas: [8008, 8009], primeira_vez: dias(6.9), modelo: { base: 4, var: 12 } }),
      aparelho({ id: "mac:d2:6e:1a:7c:44:90", ip: "192.168.0.34", mac: "d2:6e:1a:7c:44:90", fabricante: "MAC aleatório (privacidade)", nome_dns: "Galaxy-A54", tipo: "celular",
        motivos: ["MAC aleatório (privacidade de celular)"], mac_aleatorio: true, primeira_vez: dias(6.9), modelo: { base: 11, var: 70 },
        janelas: [[dias(6.9), t0 - 14 * H], [t0 - 6 * H, Infinity]] }),
      aparelho({ id: "mac:5a:1f:c3:9e:02:7b", ip: "192.168.0.37", mac: "5a:1f:c3:9e:02:7b", fabricante: "MAC aleatório (privacidade)", nome_dns: "iPhone", tipo: "celular",
        motivos: ["porta de iPhone/iPad aberta"], portas: [62078], mac_aleatorio: true, primeira_vez: dias(2) - 1.1 * H, modelo: { base: 8, var: 48 } }),
      aparelho({ id: "mac:64:6c:80:aa:51:2c", ip: "192.168.0.40", mac: "64:6c:80:aa:51:2c", fabricante: "HP", tipo: "impressora",
        motivos: ["porta de impressão aberta"], portas: [80, 443, 631, 9100], upnp: { nome: "HP DeskJet 2700 series", fabricante: "HP", modelo: "DeskJet 2700", tipo: "Printer" },
        ttl: 255, primeira_vez: dias(6.9), modelo: { base: 2.5, var: 7 } }),
      aparelho({ id: "mac:bc:32:5f:0e:7d:16", ip: "192.168.0.60", mac: "bc:32:5f:0e:7d:16", fabricante: "Intelbras", apelido: "Câmera do portão", tipo: "camera",
        motivos: ["porta RTSP (vídeo) aberta"], portas: [80, 554], alertar: true, primeira_vez: dias(6.9), modelo: { base: 6, var: 22 } }),
      aparelho({ id: "mac:24:6f:28:a1:9c:40", ip: "192.168.0.71", mac: "24:6f:28:a1:9c:40", fabricante: "Espressif", tipo: "iot",
        motivos: ["fabricante de dispositivos IoT"], responde_ping: false, ttl: null, primeira_vez: dias(6.9) }),
      aparelho({ id: "mac:44:65:0d:2f:b8:93", ip: "192.168.0.73", mac: "44:65:0d:2f:b8:93", fabricante: "Amazon Technologies", apelido: "Alexa da cozinha", tipo: "iot",
        motivos: ["fabricante de dispositivos IoT"], primeira_vez: dias(6.9), modelo: { base: 5, var: 18 } }),
      aparelho({ id: "mac:00:d9:d1:6b:20:f4", ip: "192.168.0.80", mac: "00:d9:d1:6b:20:f4", fabricante: "Sony Interactive Entertainment", tipo: "desconhecido",
        motivos: ["sem pistas suficientes"], primeira_vez: dias(5) - 4 * H, modelo: { base: 2, var: 5 } }),
    ];
    ds.forEach((d) => {
      d.so = d.ttl ? SO[d.ttl] : null;
      d.portas_em = t0 - (1 + 4 * ruido(d.id, 1)) * H;
      d.mudou_em = d.primeira_vez;
    });
    const porId = Object.fromEntries(ds.map((d) => [d.id, d]));
    porId["mac:f8:bc:12:7a:03:5e"].mudou_em = t0 - 3 * H;
    porId["mac:d2:6e:1a:7c:44:90"].mudou_em = t0 - 6 * H;
    porId["mac:bc:32:5f:0e:7d:16"].mudou_em = t0 - 9 * H + 17 * MIN;

    const queda = t0 - 30 * H, quedaCamera = t0 - 9 * H;
    const eventos = [
      [dias(6.9), "sistema", "info", null, "Primeira varredura: 12 aparelhos encontrados", "192.168.0.0/24"],
      [dias(5) - 4 * H, "novo", "aviso", "dispositivo:mac:00:d9:d1:6b:20:f4", "Novo aparelho: Aparelho Sony", "192.168.0.80, 00:d9:d1:6b:20:f4, Sony Interactive Entertainment"],
      [dias(5) - 4 * H + 20, "alerta", "info", null, "Alerta enviado", "NOVO: Aparelho Sony"],
      [dias(2) - 1.1 * H, "novo", "aviso", "dispositivo:mac:5a:1f:c3:9e:02:7b", "Novo aparelho: iPhone", "192.168.0.37, 5a:1f:c3:9e:02:7b, MAC aleatório (privacidade)"],
      [dias(2) - 1.1 * H + 20, "alerta", "info", null, "Alerta enviado", "NOVO: iPhone"],
      [queda, "queda", "critico", "internet", "Internet caiu", "nenhum servidor externo respondeu"],
      [queda + 4 * MIN, "volta", "ok", "internet", "Internet voltou", "Ficou fora por 4 min."],
      [queda + 4 * MIN + 3, "alerta", "info", null, "Alerta enviado", "QUEDA: Internet"],
      [queda + 4 * MIN + 4, "alerta", "info", null, "Alerta enviado", "RESTAURADA: Internet"],
      [t0 - 20 * H, "voltou", "info", "dispositivo:mac:f8:bc:12:7a:03:5e", "Computador Dell voltou para a rede", "192.168.0.44"],
      [t0 - 14 * H, "saiu", "info", "dispositivo:mac:d2:6e:1a:7c:44:90", "Galaxy-A54 saiu da rede", "192.168.0.34"],
      [quedaCamera, "queda", "critico", "dispositivo:mac:bc:32:5f:0e:7d:16", "Câmera do portão (192.168.0.60) caiu", ""],
      [quedaCamera + 2, "alerta", "info", null, "Alerta enviado", "QUEDA: Câmera do portão (192.168.0.60)"],
      [quedaCamera + 17 * MIN, "volta", "ok", "dispositivo:mac:bc:32:5f:0e:7d:16", "Câmera do portão (192.168.0.60) voltou", "Ficou fora por 17 min."],
      [quedaCamera + 17 * MIN + 2, "alerta", "info", null, "Alerta enviado", "RESTAURADA: Câmera do portão (192.168.0.60)"],
      [t0 - 6 * H, "voltou", "info", "dispositivo:mac:d2:6e:1a:7c:44:90", "Galaxy-A54 voltou para a rede", "192.168.0.34"],
      [t0 - 3 * H, "saiu", "info", "dispositivo:mac:f8:bc:12:7a:03:5e", "Computador Dell saiu da rede", "192.168.0.44"],
    ].sort((a, b) => a[0] - b[0]).map(([ts, tipo, gravidade, alvo, titulo, detalhe], i) => ({ id: i + 1, ts, tipo, gravidade, alvo, titulo, detalhe: detalhe || null }));

    D = {
      inicio: t0,
      dispositivos: ds,
      eventos,
      quedas: { internet: [[queda, queda + 4 * MIN]], "dispositivo:mac:bc:32:5f:0e:7d:16": [[quedaCamera, quedaCamera + 17 * MIN]] },
      internetDesde: queda + 4 * MIN,
      ultimoEnvio: quedaCamera + 17 * MIN + 2,
      sim: { internet: null, varredura: null, extras: 0 },
      escaneando: {},
      acesso: { rede_local: false, senha_definida: false },
      autostart: false,
      config: {
        monitor: { intervalo_s: 60, confirmacao_s: 15, tentativas: 2, timeout_ms: 1000 },
        internet: { alvos: ["8.8.8.8", "1.1.1.1"], alertar: true, lenta_ms: 150 },
        descoberta: { intervalo_min: 5, testar_portas: true, avisar_novos: true },
        trafego: { ativo: true, intervalo_s: 30 },
        alertas: {
          telegram: { token: "7123456789:AAHd3m0DemoDemoDemoDemoDemoD3m0x8Kq", chat_id: "812345678" },
          discord: { webhook: "" },
          healthchecks: { url: "https://hc-ping.com/5f0c2a1e-7b2d-4b7e-9d3a-7c1e2b8f2f1c" },
        },
        zabbix: { url: "http://192.168.0.20/zabbix/api_jsonrpc.php", token: "e4b1c07d9f2a46b8a3d5c1e09b7fa91f" },
        retencao_dias: 7,
      },
      zabbix: {
        "192.168.0.1": { nome: "Roteador TP-Link", hostid: "10601", ping: true, problemas: [] },
        "192.168.0.10": { nome: "Notebook (Windows)", hostid: "10602", ping: true, problemas: [] },
        "192.168.0.20": { nome: "Zabbix server", hostid: "10084", ping: true, problemas: [] },
        "192.168.0.21": { nome: "TV da sala", hostid: "10603", ping: true, problemas: [] },
        "192.168.0.60": { nome: "Câmera do portão", hostid: "10604", ping: true, problemas: [] },
      },
    };
  }

  // ------------------------------------------------------------------ modelos
  function emQueda(alvo, t) {
    return (D.quedas[alvo] || []).some(([a, b]) => t >= a && t < b);
  }

  function presente(d, t) {
    if (t < d.primeira_vez) return false;
    return !d.janelas || d.janelas.some(([a, b]) => t >= a && t < b);
  }

  function latenciaInternet(t) {
    const h = horaDe(t), n = t / MIN;
    let v = 13 + 8 * sino(h, 21, 2.2) + 3 * sino(h, 13.5, 2) + 5 * ruido("inet", n) ** 2;
    if (ruido("inet-pico", n) > 0.985) v += 35 + 50 * ruido("inet-pico2", n);
    return v;
  }

  function valor(alvo, t) {
    if (alvo === "internet" || alvo.startsWith("wan:")) {
      if (emQueda("internet", t)) return null;
      return latenciaInternet(t) + (alvo === "wan:1.1.1.1" ? 1.8 : 0);
    }
    const d = D.dispositivos.find((x) => `dispositivo:${x.id}` === alvo);
    if (!d || !presente(d, t) || !d.responde_ping) return undefined;     // sem medição
    if (emQueda(alvo, t)) return null;
    const m = d.modelo, n = t / MIN;
    let v = m.base + m.var * ruido(alvo, n) ** 2.4;
    if (ruido(`${alvo}-p`, n) > 0.99) v += m.var * 3;
    return v;
  }

  function intervaloDe(alvo) {
    if (alvo === "internet" || alvo.startsWith("wan:")) return MIN;
    const d = D.dispositivos.find((x) => `dispositivo:${x.id}` === alvo);
    return d && d.alertar ? MIN : 5 * MIN;
  }

  function serie(alvo, desde, ate, baldes = 240) {
    const passo = (ate - desde) / baldes, int = intervaloDe(alvo);
    const saida = [];
    let soma = 0, n = 0, perdas = 0, min = Infinity, max = -Infinity;
    for (let b = 0; b < baldes; b++) {
      const ini = desde + b * passo, fim = ini + passo;
      let s = 0, k = 0, p = 0;
      for (let t = Math.ceil(ini / int) * int; t < fim; t += int) {
        const v = valor(alvo, t);
        if (v === undefined) continue;
        k++;
        if (v == null) p++;
        else { s += v; min = Math.min(min, v); max = Math.max(max, v); }
      }
      if (k) {
        saida.push([ini + passo / 2, k - p ? arred(s / (k - p), 2) : null, arred((100 * p) / k)]);
        soma += s; n += k; perdas += p;
      }
    }
    const estat = { media: n - perdas ? soma / (n - perdas) : null, minimo: n - perdas ? min : null, maximo: n - perdas ? max : null, amostras: n,
      disponibilidade: n ? arred((100 * (n - perdas)) / n, 2) : null };
    return { serie: saida, estatisticas: estat };
  }

  function trafegoEm(t) {
    const h = horaDe(t), dia = diaDe(t), n = t / 30;
    const r = (k) => ruido(k, n);
    let dl = 0.25 + 0.35 * r("dl0");                                    // fundo: nuvem, celulares, IoT
    dl += 2 * sino(h, 9.5, 1.5) * (0.4 + r("dl1"));                     // manhã
    dl += 3.5 * sino(h, 14.5, 2.2) * (0.4 + r("dl2"));                  // tarde: aulas e vídeos
    dl += 7 * sino(h, 21, 1.8) * (0.5 + 0.7 * r("dl3"));                // noite: streaming
    if (h > 7 && r("rajada") > 0.97) dl += 5 + 15 * r("rajada2");       // páginas, fotos, atualizações de apps
    const inicio = 1.5 + 3.5 * ruido("noturna-h", dia);                 // console e Windows se atualizam de madrugada
    if (ruido("noturna", dia) > 0.6 && h > inicio && h < inicio + 0.2) dl += 110 + 90 * r("dl4");
    const util = ((dia % 7) + 7 + 3) % 7 < 5;                           // 1/1/1970 foi quinta
    let ul = 0.3 + 0.25 * r("ul0");                                     // a câmera envia para a nuvem
    ul += 3 * sino(h, 10.5, 1) * (util ? 1 : 0.15) * (0.7 + 0.5 * r("ul1"));   // videochamada
    ul += 1.2 * sino(h, 21, 2) * r("ul2");
    if (D.sim.internet && t >= D.sim.internet.inicio && t < D.sim.internet.fim) return [0, 0];
    return [dl * 1e6, ul * 1e6];
  }

  function bytesEntre(desde, ate, passo = 120) {
    let rx = 0, tx = 0;
    for (let t = desde; t < ate; t += passo) {
      const [d, u] = trafegoEm(t);
      const dt = Math.min(passo, ate - t);
      rx += (d * dt) / 8;
      tx += (u * dt) / 8;
    }
    return [rx, tx];
  }

  function dadosTrafego(periodo) {
    const ate = agoraS(), desde = ate - periodo, passo = periodo / 240, int = 30;
    const s = [];
    let pico = 0, picoEm = null, picoTx = 0;
    for (let b = 0; b < 240; b++) {
      const ini = desde + b * passo, fim = ini + passo;
      let sd = 0, su = 0, k = 0;
      const salto = Math.max(int, Math.floor(passo / 12 / int) * int);
      for (let t = Math.ceil(ini / int) * int; t < fim; t += salto) {
        const [d, u] = trafegoEm(t);
        sd += d; su += u; k++;
        if (d > pico) { pico = d; picoEm = t; }
        picoTx = Math.max(picoTx, u);
      }
      if (k) s.push([ini + passo / 2, arred(sd / k), arred(su / k)]);
    }
    const [rx, tx] = bytesEntre(desde, ate, Math.max(30, periodo / 1500));
    const n = Math.round(periodo / int);
    const dias = [];
    const meiaNoite = (diaDe(ate) * DIA) - FUSO;
    for (let i = 6; i >= 0; i--) {
      const ini = meiaNoite - i * DIA, fim = Math.min(ini + DIA, ate);
      const [r, t] = bytesEntre(ini, fim, 240);
      const data = new Date((ini + 12 * H) * 1000);
      const dia = `${data.getFullYear()}-${String(data.getMonth() + 1).padStart(2, "0")}-${String(data.getDate()).padStart(2, "0")}`;
      dias.push({ dia, rx_bytes: Math.round(r), tx_bytes: Math.round(t) });
    }
    return {
      periodo, desde, ate, serie: s,
      resumo: { rx_bytes: Math.round(rx), tx_bytes: Math.round(tx), pico_rx_bps: pico, pico_tx_bps: picoTx, pico_em: picoEm, amostras: n },
      dias, status: statusTrafego(),
    };
  }

  function statusTrafego() {
    if (!D.config.trafego.ativo) return { estado: "desligado", motivo: null, agora: null, roteador: null };
    const ts = Math.floor(agoraS() / 30) * 30;
    const [rx, tx] = internetFora(agoraS()) ? [0, 0] : trafegoEm(ts);
    return {
      estado: "ativo", motivo: null, agora: { ts, rx_bps: rx, tx_bps: tx },
      roteador: { nome: "Archer C6", fabricante: "TP-Link", modelo: "Archer C6", ip_publico: "100.71.23.9", conexao: "Connected",
        uptime_s: Math.round(agoraS() - (D.inicio - 4.3 * DIA)), link_down_bps: 1e9, link_up_bps: 1e9, link: "Up", cgnat: true, nat_duplo: false },
    };
  }

  // ------------------------------------------------------------------ simulações e relógio
  function evento(tipo, gravidade, alvo, titulo, detalhe, ts) {
    const id = (D.eventos.length ? D.eventos[D.eventos.length - 1].id : 0) + 1;
    D.eventos.push({ id, ts: ts || agoraS(), tipo, gravidade, alvo, titulo, detalhe: detalhe || null });
  }

  function passarTempo() {
    const t = agoraS(), s = D.sim;
    if (s.internet && !s.internet.encerrada && t >= s.internet.fim) {
      s.internet.encerrada = true;
      D.internetDesde = s.internet.fim;
      evento("volta", "ok", "internet", "Internet voltou", "Ficou fora por menos de 1 min.", s.internet.fim);
      evento("alerta", "info", null, "Alerta enviado", "QUEDA: Internet", s.internet.fim + 1);
      evento("alerta", "info", null, "Alerta enviado", "RESTAURADA: Internet", s.internet.fim + 2);
      D.ultimoEnvio = s.internet.fim + 2;
    }
    if (s.varredura && t - s.varredura.inicio >= 8) {
      s.ultimaVarredura = s.varredura.inicio + 8;
      s.varredura = null;
    }
    Object.keys(D.escaneando).forEach((id) => {
      if (t >= D.escaneando[id]) {
        delete D.escaneando[id];
        const d = D.dispositivos.find((x) => x.id === id);
        if (d) d.portas_em = t;
      }
    });
  }

  function internetFora(t) {
    return Boolean(D.sim.internet && t >= D.sim.internet.inicio && t < D.sim.internet.fim);
  }

  const EXTRAS = [
    { id: "mac:9e:41:d7:20:b3:5a", ip: "192.168.0.91", mac: "9e:41:d7:20:b3:5a", fabricante: "MAC aleatório (privacidade)", nome_dns: "Galaxy-Tab-S6-Lite", tipo: "celular",
      motivos: ["MAC aleatório (privacidade de celular)"], mac_aleatorio: true, modelo: { base: 9, var: 40 } },
    { id: "mac:dc:4f:22:6a:91:0b", ip: "192.168.0.95", mac: "dc:4f:22:6a:91:0b", fabricante: "Espressif", tipo: "iot", apelido: null,
      motivos: ["porta MQTT aberta"], portas: [1883], modelo: { base: 6, var: 20 } },
    { id: "mac:3c:a9:f4:58:e2:17", ip: "192.168.0.97", mac: "3c:a9:f4:58:e2:17", fabricante: "Intel Corporate", nome_dns: "NOTEBOOK-VISITA", tipo: "computador",
      motivos: ["portas de compartilhamento do Windows"], portas: [139, 445], ttl: 128, modelo: { base: 3, var: 9 } },
  ];

  // ------------------------------------------------------------------ montagem do estado
  function nomeDe(d) {
    if (d.apelido) return d.apelido;
    if (d.upnp && d.upnp.nome) return d.upnp.nome;
    if (d.nome_dns) return d.nome_dns.split(".")[0];
    const tipo = TIPOS[d.tipo] || "Aparelho";
    if (d.fabricante && !d.fabricante.startsWith("MAC aleatório")) return `${tipo} ${d.fabricante.split(" ")[0]}`;
    return `${tipo} .${d.ip.split(".").pop()}`;
  }

  function paraTela(d, t) {
    const alvo = `dispositivo:${d.id}`;
    const naRede = presente(d, t) && !(d.alertar && emQueda(alvo, t));
    let latencia = null, ultima = null;
    if (naRede) {
      const int = d.alertar ? MIN : 5 * MIN;
      const v = d.responde_ping ? valor(alvo, Math.floor(t / int) * int) : null;
      latencia = d.tipo === "este_pc" ? 0 : v == null ? null : arred(v);
      ultima = t;
    } else {
      const fim = (d.janelas || []).filter(([, b]) => b <= t).map(([, b]) => b).pop();
      ultima = fim || d.mudou_em;
    }
    const z = D.config.zabbix.url && D.config.zabbix.token ? D.zabbix[d.ip] || null : null;
    const { janelas, modelo, ...resto } = d;
    return Object.assign(resto, {
      online: naRede, latencia, ultima_vez: ultima, ausencias: naRede ? 0 : 2,
      nome: nomeDe(d), tipo_nome: TIPOS[d.tipo] || "Aparelho", zabbix: z, escaneando: Boolean(D.escaneando[d.id]), este_pc: d.ip === REDE.ip,
      portas: d.portas ? [...d.portas] : d.portas, motivos: [...d.motivos],
    });
  }

  function mascarar(v) { return v ? "••••" + (v.length > 8 ? v.slice(-4) : "") : ""; }

  function configMascarada() {
    const c = JSON.parse(JSON.stringify(D.config));
    c.alertas.telegram.token = mascarar(c.alertas.telegram.token);
    c.alertas.discord.webhook = mascarar(c.alertas.discord.webhook);
    c.alertas.healthchecks.url = mascarar(c.alertas.healthchecks.url);
    c.zabbix.token = mascarar(c.zabbix.token);
    c.acesso = { rede_local: D.acesso.rede_local, senha_definida: D.acesso.senha_definida };
    return c;
  }

  function canais() {
    const a = D.config.alertas, lista = [];
    if (a.telegram.token && a.telegram.chat_id) lista.push("Telegram");
    if (a.discord.webhook) lista.push("Discord");
    return lista;
  }

  function veredito(cfg, internet, ds, t) {
    const monitorados = ds.filter((d) => d.alertar && !d.este_pc);
    const fora = monitorados.filter((d) => !d.online).sort((a, b) => (a.tipo !== "roteador") - (b.tipo !== "roteador"));
    const r = fora.find((d) => d.tipo === "roteador");
    if (r) return { estado: "critico", titulo: `${r.nome} sem resposta`, detalhe: "Confira a energia e os cabos do roteador.", desde: r.mudou_em };
    if (internet && !internet.online) {
      const ok = monitorados.some((d) => d.tipo === "roteador" && d.online);
      return { estado: "critico", titulo: "Internet fora do ar", detalhe: ok ? "O roteador responde; a falha parece ser da operadora." : "Nenhum servidor da internet respondeu.", desde: internet.desde };
    }
    if (fora.length) {
      const nomes = fora.slice(0, 3).map((d) => d.nome).join(", ") + (fora.length > 3 ? ` e mais ${fora.length - 3}` : "");
      return { estado: "alerta", titulo: `${nomes} sem resposta`, detalhe: "A internet está funcionando.", desde: fora[0].mudou_em };
    }
    if (internet && internet.ms > cfg.internet.lenta_ms) {
      return { estado: "alerta", titulo: "Internet lenta", detalhe: `Resposta em ${Math.round(internet.ms)} ms (o normal é abaixo de ${cfg.internet.lenta_ms} ms).`, desde: null };
    }
    const online = ds.filter((d) => d.online).length;
    return { estado: "ok", titulo: "Tudo funcionando", detalhe: `${online} aparelhos na rede` + (monitorados.length ? `, ${monitorados.length} sob monitoramento` : ""), desde: null };
  }

  const ipNum = (ip) => ip.split(".").reduce((n, p) => n * 256 + Number(p), 0);

  function estado() {
    const t = agoraS(), cfg = D.config;
    const ciclo = Math.floor(t / MIN) * MIN;
    const ds = D.dispositivos.map((d) => paraTela(d, t)).sort((a, b) =>
      ORDEM.indexOf(a.tipo) - ORDEM.indexOf(b.tipo) || (b.online - a.online) || ipNum(a.ip) - ipNum(b.ip));
    const fora = internetFora(t);
    const nomes = { "8.8.8.8": "Google DNS", "1.1.1.1": "Cloudflare DNS", "8.8.4.4": "Google DNS", "1.0.0.1": "Cloudflare DNS", "9.9.9.9": "Quad9" };
    const servidores = cfg.internet.alvos.map((h, i) => {
      const v = fora ? null : latenciaInternet(ciclo) + i * 1.8;
      return { host: h, nome: nomes[h] || h, online: !fora, ms: v == null ? null : arred(v) };
    });
    const melhor = fora ? null : Math.min(...servidores.map((s) => s.ms));
    const internet = { online: !fora, ms: melhor, desde: fora ? D.sim.internet.inicio : D.internetDesde, servidores };
    const v = D.sim.varredura;
    const progresso = v ? Math.min(99, Math.round(((t - v.inicio) / 8) * 100)) : 100;
    const etapa = !v ? "pronto" : progresso < 10 ? "lendo a configuração da rede" : progresso < 60 ? `pingando ${Math.round((progresso / 60) * 254)} de 254 endereços`
      : progresso < 80 ? "identificando os aparelhos" : progresso < 90 ? "ouvindo anúncios UPnP" : "traçando o caminho até a internet";
    const ultima = v ? v.anterior : Math.max(D.sim.ultimaVarredura || 0, Math.floor(t / 300) * 300);
    const trafego = statusTrafego();
    const meiaNoite = (diaDe(t) * DIA) - FUSO;
    const [hojeRx, hojeTx] = bytesEntre(meiaNoite, t, 300);
    const canaisAtivos = canais();
    const zbxOk = Boolean(cfg.zabbix.url && cfg.zabbix.token);
    return {
      app: "HomeNOC", versao: VERSAO, agora: t, iniciado_em: D.inicio - 4.3 * DIA,
      rede: { ...REDE },
      varredura: { ativa: Boolean(v), etapa, progresso, ultima, proxima: ultima + cfg.descoberta.intervalo_min * 60, duracao_s: 41.3, erro: null },
      internet,
      monitor: { ultimo_ciclo: ciclo, intervalo_s: cfg.monitor.intervalo_s, lenta_ms: cfg.internet.lenta_ms },
      dispositivos: ds,
      caminho: [
        { salto: 1, ip: "192.168.0.1", ms: 1.1 }, { salto: 2, ip: "100.64.0.1", ms: 5.2 }, { salto: 3, ip: "187.62.208.1", ms: 6.9 },
        { salto: 4, ip: null, ms: null }, { salto: 5, ip: "8.8.8.8", ms: 13.1 },
      ],
      trafego: { ...trafego, hoje: { rx_bytes: Math.round(hojeRx), tx_bytes: Math.round(hojeTx) } },
      alertas: {
        canais: canaisAtivos, fila: fora && canaisAtivos.length ? 1 : 0, healthchecks_configurado: Boolean(cfg.alertas.healthchecks.url),
        ultimo_envio: D.ultimoEnvio, ultimo_erro: null,
        healthchecks: cfg.alertas.healthchecks.url ? (fora ? { ok: false, em: ciclo, erro: "sem conexão com a internet" } : { ok: true, em: ciclo }) : null,
      },
      zabbix: zbxOk ? { configurado: true, ok: true, erro: null, versao: "7.0.5", hosts: 6, problemas: [], atualizado_em: ciclo }
        : { configurado: false, ok: null, erro: null, versao: null, hosts: 0, problemas: [], atualizado_em: null },
      eventos: [...D.eventos].reverse().slice(0, 12),
      veredito: veredito(cfg, internet, ds, t),
      primeiros_passos: { varredura: true, monitorados: ds.filter((d) => d.alertar).length, alertas: canaisAtivos.length > 0, celular: D.acesso.rede_local, zabbix: zbxOk },
      acesso: { local: true, rede_local: D.acesso.rede_local, senha_definida: D.acesso.senha_definida, urls: D.acesso.rede_local ? [`http://${REDE.ip}:8765`] : [] },
      autostart: { suportado: true, ativo: D.autostart },
      portas_conhecidas: PORTAS,
      pasta_dados: "C:\\Users\\voce\\HomeNOC\\dados",
    };
  }

  // ------------------------------------------------------------------ validação (a mesma regra do servidor)
  function erro(status, mensagem) { return new HN.ErroApi(status, mensagem); }

  function validar(c) {
    const inteiro = (sec, chave, min, max, nome) => {
      const v = sec[chave];
      if (typeof v !== "number" || !Number.isInteger(v)) throw erro(400, `${nome} deve ser um número inteiro.`);
      if (v < min || v > max) throw erro(400, `${nome} deve ficar entre ${min} e ${max}.`);
    };
    inteiro(c.monitor, "intervalo_s", 15, 3600, "O intervalo do monitoramento (segundos)");
    inteiro(c.monitor, "confirmacao_s", 0, 120, "A espera de confirmação (segundos)");
    inteiro(c.monitor, "tentativas", 1, 5, "O número de tentativas");
    inteiro(c.monitor, "timeout_ms", 300, 5000, "O tempo limite do ping (ms)");
    const alvos = c.internet.alvos;
    if (!Array.isArray(alvos) || alvos.length < 1 || alvos.length > 4) throw erro(400, "Informe de 1 a 4 servidores para testar a internet.");
    alvos.forEach((a) => { if (!/^[a-z0-9.-]{1,253}$/i.test(a)) throw erro(400, `'${a}' não é um IP ou nome de servidor válido.`); });
    if (new Set(alvos).size !== alvos.length) throw erro(400, "Há servidores repetidos na lista da internet.");
    inteiro(c.internet, "lenta_ms", 20, 2000, "O limite de internet lenta (ms)");
    inteiro(c.descoberta, "intervalo_min", 1, 1440, "O intervalo da varredura (minutos)");
    inteiro(c.trafego, "intervalo_s", 10, 600, "O intervalo do tráfego (segundos)");
    inteiro(c, "retencao_dias", 1, 90, "Os dias de histórico");
    const tg = c.alertas.telegram;
    tg.token = String(tg.token || "").trim();
    tg.chat_id = String(tg.chat_id || "").trim();
    if (tg.token && !/^\d{5,}:[\w-]{30,}$/.test(tg.token)) throw erro(400, "O token do Telegram não parece válido (formato 123456789:AAH...).");
    if (tg.chat_id && !/^(-?\d{1,20}|@[A-Za-z0-9_]{4,})$/.test(tg.chat_id)) throw erro(400, "O chat_id do Telegram deve ser um número (ou @nome_do_canal).");
    const dc = c.alertas.discord;
    dc.webhook = String(dc.webhook || "").trim();
    if (dc.webhook && !/^https:\/\/(discord|discordapp)\.com\/api\/webhooks\/\S+$/.test(dc.webhook)) throw erro(400, "O webhook do Discord deve começar com https://discord.com/api/webhooks/");
    const hc = c.alertas.healthchecks;
    hc.url = String(hc.url || "").trim();
    if (hc.url && !/^https?:\/\/\S+$/.test(hc.url)) throw erro(400, "O endereço do Healthchecks deve começar com https://");
    const z = c.zabbix;
    z.url = String(z.url || "").trim();
    if (z.url && !/^https?:\/\//i.test(z.url)) z.url = `http://${z.url}`;
    if (z.url && !/api_jsonrpc\.php\/?$/.test(z.url)) z.url = `${z.url.replace(/\/+$/, "")}/api_jsonrpc.php`;
    z.token = String(z.token || "").trim();
    if (z.token && !/^[A-Za-z0-9]{16,128}$/.test(z.token)) throw erro(400, "O token do Zabbix deve ter só letras e números (como o Zabbix gera).");
    return c;
  }

  function mesclar(base, novo) {
    const saida = JSON.parse(JSON.stringify(base));
    Object.entries(novo || {}).forEach(([k, v]) => {
      if (v && typeof v === "object" && !Array.isArray(v) && saida[k] && typeof saida[k] === "object" && !Array.isArray(saida[k])) saida[k] = mesclar(saida[k], v);
      else saida[k] = v;
    });
    return saida;
  }

  function previa(parcial) {
    const p = JSON.parse(JSON.stringify(parcial || {}));
    delete p.acesso;
    const manter = (obj, caminho) => {
      let o = obj;
      for (const parte of caminho.slice(0, -1)) { if (!o || typeof o !== "object") return; o = o[parte]; }
      const k = caminho[caminho.length - 1];
      if (o && typeof o[k] === "string" && o[k].startsWith("••••")) {
        let atual = D.config;
        caminho.forEach((x) => { atual = atual[x]; });
        o[k] = atual;
      }
    };
    [["alertas", "telegram", "token"], ["alertas", "discord", "webhook"], ["alertas", "healthchecks", "url"], ["zabbix", "token"]].forEach((c) => manter(p, c));
    return validar(mesclar(D.config, p));
  }

  function csv() {
    const linhas = [["Nome", "Tipo", "IP", "MAC", "Fabricante", "Nome DNS", "Online", "Latência (ms)", "Portas abertas", "Visto pela 1ª vez", "Visto por último", "Avisar se cair"]];
    const data = (ts) => (ts ? new Date(ts * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }).replace(",", "") : "");
    estado().dispositivos.forEach((d) => linhas.push([d.nome, d.tipo_nome, d.ip, d.mac || "", d.fabricante || "", d.nome_dns || "", d.online ? "sim" : "não",
      d.latencia == null ? "" : String(d.latencia).replace(".", ","), (d.portas || []).join(" "), data(d.primeira_vez), data(d.ultima_vez), d.alertar ? "sim" : "não"]));
    return linhas.map((l) => l.map((c) => (/[;"\n]/.test(c) ? `"${String(c).replace(/"/g, '""')}"` : c)).join(";")).join("\r\n") + "\r\n";
  }

  // ------------------------------------------------------------------ rotas
  const espera = (ms) => new Promise((r) => setTimeout(r, ms));

  async function api(metodo, caminho, corpo) {
    if (!D) criar();
    const url = new URL(caminho, "http://demo");
    const p = Object.fromEntries(url.searchParams);
    const rota = `${metodo} ${url.pathname}`;
    await espera(rota === "GET /api/estado" ? 40 : 160 + Math.random() * 180);
    passarTempo();
    const periodo = Math.max(600, Math.min(Number(p.periodo) || DIA, 31 * DIA));

    switch (rota) {
      case "GET /api/saude": return { app: "HomeNOC", versao: VERSAO };
      case "GET /api/sessao": return { local: true, autenticado: true, senha_definida: D.acesso.senha_definida };
      case "POST /api/login": return { ok: true };
      case "POST /api/sair": return { ok: true };
      case "GET /api/estado": return estado();
      case "GET /api/historico": {
        const alvo = p.alvo || "internet";
        if (!(alvo === "internet" || alvo.startsWith("wan:") || alvo.startsWith("dispositivo:"))) throw erro(400, "Alvo de histórico inválido.");
        const ate = agoraS(), desde = ate - periodo;
        return { alvo, desde, ate, ...serie(alvo, desde, ate) };
      }
      case "GET /api/trafego": return dadosTrafego(periodo);
      case "GET /api/eventos": {
        const tipos = (p.tipos || "").split(",").filter(Boolean);
        const antes = Number(p.antes) || null, limite = Math.max(1, Math.min(Number(p.limite) || 60, 500));
        return [...D.eventos].reverse().filter((e) => (!antes || e.id < antes) && (!tipos.length || tipos.includes(e.tipo)) && (!p.alvo || e.alvo === p.alvo)).slice(0, limite);
      }
      case "GET /api/dispositivos.csv": return csv();
      case "GET /api/config": return configMascarada();
      case "POST /api/config": {
        D.config = previa(corpo);
        return configMascarada();
      }
      case "POST /api/varrer": {
        if (!D.sim.varredura) D.sim.varredura = { inicio: agoraS(), anterior: Math.max(D.sim.ultimaVarredura || 0, Math.floor(agoraS() / 300) * 300) };
        return { ok: true };
      }
      case "POST /api/alertas/teste": {
        const cfg = previa({ alertas: corpo || {} });
        const r = [];
        const a = cfg.alertas;
        if (a.telegram.token && a.telegram.chat_id) r.push({ canal: "Telegram", ok: true, mensagem: "Na demonstração nada é enviado de verdade, mas no seu computador a mensagem chegaria agora." });
        if (a.discord.webhook) r.push({ canal: "Discord", ok: true, mensagem: "Na demonstração nada é enviado de verdade." });
        if (a.healthchecks.url) r.push({ canal: "Healthchecks.io", ok: true, mensagem: "Sinal recebido (simulado)." });
        if (!r.length) throw erro(400, "Preencha o Telegram, o Discord ou o Healthchecks antes de testar.");
        return { resultados: r };
      }
      case "POST /api/alertas/chat-id": {
        const token = String((corpo && corpo.token) || "");
        if (!token && !D.config.alertas.telegram.token) throw erro(400, "Cole primeiro o token que o @BotFather enviou.");
        return { ok: true, chats: [{ id: "812345678", nome: "Conta de exemplo" }] };
      }
      case "POST /api/zabbix/teste": {
        const url = String((corpo && corpo.url) || D.config.zabbix.url);
        const token = String((corpo && corpo.token) || "");
        if (!url || (!token && !D.config.zabbix.token)) throw erro(400, "Preencha o endereço e o token do Zabbix.");
        return { ok: true, versao: "7.0.5", hosts: 6, problemas: 0 };
      }
      case "POST /api/acesso": {
        const rede = Boolean(corpo && corpo.rede_local), senha = corpo && corpo.senha;
        if (senha && String(senha).length < 6) throw erro(400, "A senha precisa ter pelo menos 6 caracteres.");
        if (rede && !senha && !D.acesso.senha_definida) throw erro(400, "Defina uma senha para liberar o acesso pelo celular.");
        D.acesso.rede_local = rede;
        if (senha) D.acesso.senha_definida = true;
        return { ok: true, rede_local: rede, urls: rede ? [`http://${REDE.ip}:8765`] : [] };
      }
      case "POST /api/autostart": {
        D.autostart = Boolean(corpo && corpo.ativo);
        return { ok: true, ativo: D.autostart, mensagem: D.autostart ? "Pronto: abriria junto com o Windows (na demonstração nada muda no computador)." : "Desligado (simulado)." };
      }
      case "POST /api/encerrar": throw erro(400, "Isto é uma demonstração: não há nada rodando para encerrar.");
      default: break;
    }
    const m = url.pathname.match(/^\/api\/dispositivos\/([^/]+)(\/portas)?$/);
    if (m && metodo === "POST") {
      const id = decodeURIComponent(m[1]);
      const d = D.dispositivos.find((x) => x.id === id);
      if (!d) throw erro(404, "Aparelho não encontrado.");
      if (m[2]) { D.escaneando[id] = agoraS() + 3.5; return { ok: true }; }
      if (corpo && "apelido" in corpo) d.apelido = String(corpo.apelido || "").split(/\s+/).filter(Boolean).join(" ").slice(0, 40) || null;
      if (corpo && "alertar" in corpo) d.alertar = Boolean(corpo.alertar);
      return paraTela(d, agoraS());
    }
    throw erro(404, "Rota não encontrada.");
  }

  HN.demo = {
    iniciar() { if (!D) criar(); },
    api,
    csv() { if (!D) criar(); return csv(); },
    simularQuedaInternet() {
      const t = agoraS();
      if (internetFora(t)) return Math.ceil(D.sim.internet.fim - t);
      D.sim.internet = { inicio: t, fim: t + QUEDA_S };
      D.quedas.internet.push([Math.floor(t / MIN) * MIN, t + QUEDA_S]);     // o teste daquele minuto falhou
      evento("queda", "critico", "internet", "Internet caiu", "nenhum servidor externo respondeu", t);
      return QUEDA_S;
    },
    simularAparelhoNovo() {
      const base = EXTRAS[D.sim.extras];
      if (!base) return null;
      D.sim.extras += 1;
      const t = agoraS();
      const d = aparelho({ ...base, primeira_vez: t, mudou_em: t, portas_em: t });
      d.so = d.ttl ? SO[d.ttl] : null;
      D.dispositivos.push(d);
      const nome = nomeDe(d);
      evento("novo", "aviso", `dispositivo:${d.id}`, `Novo aparelho: ${nome}`, [d.ip, d.mac, d.fabricante].filter(Boolean).join(", "), t);
      if (D.config.descoberta.avisar_novos && canais().length) {
        evento("alerta", "info", null, "Alerta enviado", `NOVO: ${nome}`, t + 1);
        D.ultimoEnvio = t + 1;
      }
      return { nome };
    },
  };
})(window.HN = window.HN || {});
